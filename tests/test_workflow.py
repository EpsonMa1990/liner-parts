import base64
import io
import json
import threading
import time
import zipfile

import httpx
import pytest
from openpyxl import load_workbook
from PIL import Image

from liner_parts.recognition import Recognizer
from liner_parts.service import ConflictError, Service

from .conftest import box


def wait_job(service, job_id):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        job = service.job(job_id)
        if job["status"] not in ("queued", "running", "cancelling"):
            return job
        time.sleep(0.01)
    raise AssertionError("recognition worker did not finish")


def test_import_crop_and_reopen(service, task):
    assert task["page_count"] == 2
    page = task["pages"][0]
    saved = service.save_page(page["id"], [box(x=0.5, y=0.15, width=0.2, height=0.1)], 0)
    cropped = Image.open(io.BytesIO(service.image(page["id"], "box-1")))
    r, g, b = cropped.getpixel((cropped.width // 2, cropped.height // 2))
    assert r > 240 and g < 10 and b < 10  # top-left normalized coordinate must crop red, not blue
    assert cropped.width >= 400
    assert saved["revision"] == 1
    service.close()
    reopened = Service(service.store.root)
    try:
        assert reopened.page(page["id"])["boxes"][0]["id"] == "box-1"
        assert len(reopened.image(page["id"])) > 100
    finally:
        reopened.close()


def test_invalid_pdf_cleanup(service):
    with pytest.raises(ValueError, match="有效"):
        service.import_pdf(io.BytesIO(b"not a pdf"), "bad.pdf")
    assert service.tasks() == []
    assert list((service.store.root / "documents").iterdir()) == []


@pytest.mark.parametrize(
    "invalid", [box(width=-1), box(x=0.9, width=0.3), box(x=float("nan")), box(quantity=0), box(quantity=1.5)]
)
def test_reject_invalid_boxes(service, task, invalid):
    page_id = task["pages"][0]["id"]
    with pytest.raises(ValueError):
        service.save_page(page_id, [invalid], 0)
    assert service.page(page_id)["revision"] == 0


def test_stale_save_and_duplicate_ids(service, task):
    first, second = task["pages"]
    service.save_page(first["id"], [box()], 0)
    with pytest.raises(ConflictError):
        service.save_page(first["id"], [], 0)
    with pytest.raises(ValueError):
        service.save_page(second["id"], [box()], 0)
    assert len(service.page(first["id"])["boxes"]) == 1


def test_recognition_actual_request_mapping_and_resume(service, task):
    page_id = task["pages"][0]["id"]
    service.save_page(
        page_id, [box("first"), box("second"), box("manual", runner="B", part_number="4", status="manual")], 0
    )
    service.settings.save(
        {"model": "test-vision", "api_key": "test-secret", "base_url": "https://example.com/v1"}
    )
    calls = []

    def handler(request):
        data = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-secret"
        assert data["model"] == "test-vision"
        content = data["messages"][1]["content"]
        assert [item["type"] for item in content] == ["text", "image_url"]
        image = Image.open(io.BytesIO(base64.b64decode(content[1]["image_url"]["url"].split(",")[1])))
        assert image.format == "PNG" and image.height > 600
        ids = [row["box_id"] for row in json.loads(content[0]["text"])["rows"]]
        calls.append(ids)
        items = [
            {
                "box_id": i,
                "runner": "A1",
                "part_number": "03" if i == "first" else "12",
                "raw_text": "",
                "status": "recognized",
                "note": "",
            }
            for i in reversed(ids)
        ]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"items": items})}}]})

    service.recognizer_factory = lambda config: Recognizer(config, httpx.MockTransport(handler))
    job = service.recognize(task["id"])
    assert wait_job(service, job["id"])["status"] == "completed"
    boxes = service.page(page_id)["boxes"]
    assert [b["part_number"] for b in boxes] == ["03", "12", "4"]
    assert calls == [["first", "second"]]
    with pytest.raises(ValueError, match="没有需要"):
        service.recognize(task["id"])


def test_ten_crop_batches_keep_page_and_marker_order(service, task):
    # Intentionally not lexical or spatial order: use the saved marker sequence.
    ids = [f"box-{i}" for i in range(23, 0, -1)]
    first, second = task["pages"]
    service.save_page(first["id"], [box(i, y=0.5 if n % 2 else 0.1) for n, i in enumerate(ids[:12])], 0)
    service.save_page(second["id"], [box(i) for i in ids[12:]], 0)
    service.settings.save({"model": "test", "batch_size": 4})
    calls = []

    def handler(request):
        content = json.loads(request.content)["messages"][1]["content"]
        assert [item["type"] for item in content] == ["text", "image_url"]
        rows = json.loads(content[0]["text"])["rows"]
        assert [row["sequence"] for row in rows] == list(range(1, len(rows) + 1))
        calls.append([row["box_id"] for row in rows])
        items = [
            {"box_id": row["box_id"], "runner": "A", "part_number": "03", "status": "recognized"}
            for row in rows
        ]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"items": items})}}]})

    service.recognizer_factory = lambda config: Recognizer(config, httpx.MockTransport(handler))
    job = wait_job(service, service.recognize(task["id"])["id"])
    assert job["status"] == "completed" and job["done"] == 23
    assert calls == [ids[:10], ids[10:20], ids[20:]]
    assert all(
        b["quantity"] == 1 and b["category"] == "头"
        for p in task["pages"]
        for b in service.page(p["id"])["boxes"]
    )


def test_cancel_does_not_overwrite_and_edits_locked(service, task):
    started, release = threading.Event(), threading.Event()

    class BlockingRecognizer:
        def __init__(self, config):
            pass

        def recognize(self, crops, cancel):
            started.set()
            assert release.wait(5)
            return {i: {"runner": "X", "part_number": "99", "status": "recognized"} for i, _ in crops}, {}

        def close(self):
            pass

    page_id = task["pages"][0]["id"]
    service.save_page(page_id, [box(runner="A", part_number="01", status="manual")], 0)
    service.settings.save({"model": "test"})
    service.recognizer_factory = BlockingRecognizer
    job = service.recognize(task["id"], mode="all")
    try:
        assert started.wait(3)
        with pytest.raises(ConflictError):
            service.save_page(page_id, [], 1)
        with pytest.raises(ConflictError):
            service.delete(task["id"])
        service.cancel(job["id"])
    finally:
        release.set()
    assert wait_job(service, job["id"])["status"] == "cancelled"
    assert service.page(page_id)["boxes"][0]["part_number"] == "01"


def test_export_preserves_number_and_escapes_formulas(service, task):
    p1, p2 = task["pages"]
    service.save_page(
        p1["id"], [box("a", runner="A1", part_number="03", quantity=2, status="manual"), box("pending")], 0
    )
    service.save_page(
        p2["id"],
        [
            box("b", runner="A1", part_number="03", quantity=3, status="recognized"),
            box("formula", runner="=2+2", part_number="001", status="manual"),
        ],
        0,
    )
    summary = service.summary(task["id"])
    assert summary["unresolved"] == 1
    row = next(r for r in summary["items"] if r["runner"] == "A1")
    assert row["quantity"] == 5 and row["pages"] == [1, 2]
    wb = load_workbook(io.BytesIO(service.export_excel(task["id"])), data_only=False)
    assert wb.sheetnames == ["取件汇总", "识别明细"]
    all_cells = [c for sheet in wb for row in sheet for c in row]
    assert any(c.value == "03" and c.data_type == "s" for c in all_cells)
    assert any(c.value == "=2+2" and c.data_type == "s" for c in all_cells)
    assert not any(c.data_type == "f" for c in all_cells)


def test_project_roundtrip_and_no_credentials(service, task):
    service.settings.save({"api_key": "private-secret", "model": "example"})
    service.save_page(task["pages"][0]["id"], [box(runner="A", part_number="12", status="manual")], 0)
    exported = service.export_project(task["id"])
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        assert set(archive.namelist()) == {"manual.pdf", "manifest.json"}
        assert b"private-secret" not in archive.read("manifest.json")
    restored = service.import_project(io.BytesIO(exported))
    assert restored["id"] != task["id"]
    assert service.summary(restored["id"])["items"] == service.summary(task["id"])["items"]
    assert service.page(restored["pages"][0]["id"])["boxes"][0]["id"] != "box-1"


def test_malicious_archive_rejected(service):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("../settings.json", "{}")
        archive.writestr("manual.pdf", "bad")
    with pytest.raises(ValueError):
        service.import_project(io.BytesIO(out.getvalue()))
    assert service.tasks() == []


def test_interrupted_jobs_recover(service, task):
    with service.store.connect() as db:
        db.execute(
            "INSERT INTO jobs(id,task_id,status,total,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("interrupted", task["id"], "running", 4, "2026", "2026"),
        )
    service.close()
    reopened = Service(service.store.root)
    try:
        assert reopened.job("interrupted")["status"] == "interrupted"
    finally:
        reopened.close()
