import io
import json
import sqlite3
import zipfile

import pytest
from PIL import Image, ImageDraw

from liner_parts.server import create_app
from liner_parts.service import Service
from liner_parts.storage import Store

from .conftest import box


def picture(color="red", size=(320, 240), format="PNG", **kwargs):
    out = io.BytesIO()
    with Image.new("RGB", size, "white") as image:
        ImageDraw.Draw(image).rectangle((0, 0, size[0] // 2 - 1, size[1] - 1), fill=color)
        image.save(out, format, **kwargs)
    out.seek(0)
    return out


def test_images_import_crop_unsaved_preview_and_reopen(service):
    task = service.import_images([(picture("red"), "页2.png"), (picture("blue"), "页10.png")])
    assert task["source_type"] == "images" and task["page_count"] == 2
    assert not service.document_path(task["id"]).exists()
    page = task["pages"][0]
    geometry = dict(x=0, y=0, width=0.5, height=1)
    raw = service.crop_preview(page["id"], geometry)
    with Image.open(io.BytesIO(raw)) as image:
        assert image.size == (160, 240) and image.getpixel((80, 120)) == (255, 0, 0)
    assert service.page(page["id"])["boxes"] == []  # previews never create markers
    service.save_page(page["id"], [box(**geometry)], 0)
    assert service.image(page["id"], "box-1") == raw
    with Image.open(io.BytesIO(service.image(task["pages"][1]["id"]))) as image:
        assert image.getpixel((80, 120)) == (0, 0, 255)
    reopened = Service(service.store.root)
    try:
        assert reopened.image(page["id"], "box-1") == raw
    finally:
        reopened.close()


@pytest.mark.parametrize("format,ext", [("JPEG", "jpg"), ("PNG", "png"), ("WEBP", "webp"), ("BMP", "bmp")])
def test_supported_image_formats(service, format, ext):
    task = service.import_images([(picture(format=format), "test." + ext)])
    assert task["pages"][0]["width"] == 320
    with Image.open(io.BytesIO(service.image(task["pages"][0]["id"]))) as image:
        assert image.format == "PNG"


def test_image_orientation_and_transparency(service):
    exif = Image.Exif()
    exif[274] = 6  # rotate 90 degrees clockwise, as on a phone photo
    transparent = io.BytesIO()
    with Image.new("RGBA", (40, 30), (0, 0, 0, 0)) as image:
        image.save(transparent, "PNG")
    transparent.seek(0)
    task = service.import_images(
        [(picture(size=(80, 40), format="JPEG", exif=exif), "phone.jpg"), (transparent, "alpha.png")]
    )
    assert (task["pages"][0]["width"], task["pages"][0]["height"]) == (40, 80)
    with Image.open(io.BytesIO(service.image(task["pages"][1]["id"]))) as image:
        assert image.getpixel((10, 10)) == (255, 255, 255)


@pytest.mark.parametrize("mixed", [False, True])
def test_append_images_backup_and_restore(service, pdf_bytes, mixed):
    task = (
        service.import_pdf(io.BytesIO(pdf_bytes), "manual.pdf")
        if mixed
        else service.import_images([(picture(), "page1.png")])
    )
    original_page = task["pages"][0]
    service.save_page(original_page["id"], [box(runner="A", part_number="03", status="manual")], 0)
    task = service.import_images([(picture("blue"), "page2.png")], task_id=task["id"])
    assert task["source_type"] == ("mixed" if mixed else "images")
    assert task["pages"][0]["id"] == original_page["id"]
    assert service.page(original_page["id"])["revision"] == 1
    added = task["pages"][-1]
    service.save_page(added["id"], [box("new", runner="B", part_number="07", status="manual")], 0)
    exported = service.export_project(task["id"])
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        assert json.loads(archive.read("manifest.json"))["version"] == 2
        assert ("manual.pdf" in archive.namelist()) == mixed
    restored = service.import_project(io.BytesIO(exported))
    assert restored["id"] != task["id"]
    assert restored["source_type"] == task["source_type"]
    assert service.summary(restored["id"])["items"] == service.summary(task["id"])["items"]
    assert service.image(restored["pages"][-1]["id"]) == service.image(added["id"])
    assert service.page(restored["pages"][-1]["id"])["boxes"][0]["id"] != "new"


def test_invalid_image_batch_is_atomic_and_recognition_allows_append(service, task):
    before = list((service.store.root / "documents").iterdir())
    for task_id in [None, task["id"]]:
        with pytest.raises(ValueError, match="无法读取图片"):
            service.import_images([(picture(), "good.png"), (io.BytesIO(b"bad"), "bad.jpg")], task_id=task_id)
    assert list((service.store.root / "documents").iterdir()) == before
    assert service.task(task["id"])["page_count"] == 2
    assert not list(service.store.root.glob("image-import-*"))
    with service.store.connect() as db:
        db.execute(
            "INSERT INTO jobs(id,task_id,status,total,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("busy", task["id"], "running", 1, "now", "now"),
        )
    service.import_images([(picture(), "page.png")], task_id=task["id"])
    assert service.task(task["id"])["page_count"] == 3


def test_image_api_import_append_and_invalid_crop(service):
    client = create_app(service, "image-test-token").test_client()
    client.get("/session?token=image-test-token")
    headers = {"X-Liner-Client": "desktop"}
    response = client.post(
        "/api/tasks/import", data={"file": [(picture(), "one.png"), (picture(), "two.png")]}, headers=headers
    )
    assert response.status_code == 200
    task = response.json
    assert task["page_count"] == 2
    assert (
        client.get(f"/api/pages/{task['pages'][0]['id']}/crop?x=0&y=0&width=.5&height=1").mimetype
        == "image/png"
    )
    for query in ["x=nan&y=0&width=1&height=1", "x=0&y=0&width=2&height=1", "x=0"]:
        assert client.get(f"/api/pages/{task['pages'][0]['id']}/crop?{query}").status_code == 400
    response = client.post(
        f"/api/tasks/{task['id']}/images", data={"file": (picture(), "three.png")}, headers=headers
    )
    assert response.status_code == 200 and response.json["page_count"] == 3
    response = client.post(
        "/api/tasks/import",
        data={"file": [(picture(), "one.png"), (io.BytesIO(b"pdf"), "two.pdf")]},
        headers=headers,
    )
    assert response.status_code == 400


def test_image_project_rejects_traversal_and_missing_files(service):
    task = service.import_images([(picture(), "one.png")])
    exported = service.export_project(task["id"])
    for bad_name in ["../escape.png", "f" * 32 + ".png"]:
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(exported)) as source, zipfile.ZipFile(out, "w") as target:
            manifest = json.loads(source.read("manifest.json"))
            manifest["pages"][0]["image_file"] = bad_name
            for name in source.namelist():
                target.writestr(name, json.dumps(manifest) if name == "manifest.json" else source.read(name))
        with pytest.raises(ValueError):
            service.import_project(io.BytesIO(out.getvalue()))
    assert len(service.tasks()) == 1


def test_migrate_old_database_preserves_pages(tmp_path):
    store = Store(tmp_path)
    with sqlite3.connect(store.path) as db:
        db.execute("ALTER TABLE pages DROP COLUMN image_file")
        db.execute("ALTER TABLE pages DROP COLUMN confirmed_revision")
        db.execute("ALTER TABLE pages DROP COLUMN no_parts_reason")
        db.execute("INSERT INTO tasks VALUES ('old','Old','old.pdf','now','now',1)")
        db.execute("INSERT INTO pages VALUES ('page','old',0,600,800,4)")
    reopened = Store(tmp_path)
    assert reopened.one("SELECT image_file,revision FROM pages WHERE id='page'") == {
        "image_file": "",
        "revision": 4,
    }
