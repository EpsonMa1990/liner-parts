import threading

import pytest

from liner_parts.server import create_app
from liner_parts.service import ConflictError, Service

from .conftest import box
from .test_images import picture
from .test_workflow import wait_job


@pytest.fixture
def parallel_manual(service, task):
    task = service.import_images([(picture(), "3.png"), (picture(), "4.png")], task_id=task["id"])
    for index, page in enumerate(task["pages"], 1):
        service.save_page(page["id"], [box(f"box-{index}")], 0)
    service.settings.save({"model": "held"})
    started = {f"box-{i}": threading.Event() for i in range(1, 5)}
    release = {key: threading.Event() for key in started}
    calls = []

    class HeldRecognizer:
        def __init__(self, config):
            pass

        def recognize(self, crops, cancel):
            key = crops[0][0]
            calls.append([box_id for box_id, _ in crops])
            started[key].set()
            assert release[key].wait(15), "test must release the simulated model"
            return {
                box_id: {"runner": "A", "part_number": box_id, "status": "recognized"} for box_id, _ in crops
            }, {}

        def close(self):
            pass

    service.recognizer_factory = HeldRecognizer
    try:
        yield task, started, release, calls
    finally:
        for event in release.values():
            event.set()


def test_other_page_editing_two_parallel_jobs_and_queue_start(service, parallel_manual):
    task, started, release, calls = parallel_manual
    p1, p2, p3, p4 = task["pages"]
    first = service.recognize(task["id"], p1["id"])
    assert started["box-1"].wait(3)
    # Saving a different page must succeed while page 1's request remains blocked.
    service.save_page(p2["id"], [box("box-2", category="背包2", quantity=4)], 1)
    second = service.recognize(task["id"], p2["id"])
    assert started["box-2"].wait(3)
    third = service.recognize(task["id"], p3["id"])
    state = service.recognition_state(task["id"], p2["id"])
    assert [job["status"] for job in state["jobs"]] == ["running", "running", "queued"]
    assert [job["page_numbers"] for job in state["jobs"]] == [[1], [2], [3]]
    assert state["workers"] == 2 and state["page"]["boxes"][0]["quantity"] == 4
    service.save_page(p4["id"], [box("box-4", quantity=7)], 1)
    for page in (p1, p2, p3):
        with pytest.raises(ConflictError, match="本页"):
            service.save_page(page["id"], [], service.page(page["id"])["revision"])
        with pytest.raises(ConflictError, match="重复"):
            service.recognize(task["id"], page["id"])
    release["box-1"].set()
    assert wait_job(service, first["id"])["status"] == "completed"
    assert started["box-3"].wait(3)  # queued request starts without waiting for page 2
    assert service.job(second["id"])["status"] == "running"
    service.save_page(p1["id"], [box("box-1", runner="PC", part_number="003", status="manual")], 2)
    release["box-2"].set()
    release["box-3"].set()
    assert wait_job(service, second["id"])["status"] == "completed"
    assert wait_job(service, third["id"])["status"] == "completed"
    second_box = service.page(p2["id"])["boxes"][0]
    assert (second_box["part_number"], second_box["category"], second_box["quantity"]) == (
        "box-2",
        "背包2",
        4,
    )
    assert service.page(p1["id"])["boxes"][0]["part_number"] == "003"
    assert service.page(p4["id"])["boxes"][0]["quantity"] == 7
    assert calls == [["box-1"], ["box-2"], ["box-3"]]


def test_cancel_queued_job_unlocks_immediately_without_model_request(service, parallel_manual):
    task, started, release, calls = parallel_manual
    jobs = []
    for i, page in enumerate(task["pages"][:3], 1):
        jobs.append(service.recognize(task["id"], page["id"]))
        if i < 3:
            assert started[f"box-{i}"].wait(3)
    assert service.cancel(jobs[2]["id"])["status"] == "cancelled"
    third_page = task["pages"][2]
    service.save_page(third_page["id"], [box("box-3", quantity=8)], 1)
    assert service.cancel(jobs[0]["id"])["status"] == "cancelling"
    release["box-1"].set()
    release["box-2"].set()
    assert wait_job(service, jobs[0]["id"])["status"] == "cancelled"
    assert wait_job(service, jobs[1]["id"])["status"] == "completed"
    assert service.page(task["pages"][0]["id"])["boxes"][0]["status"] == "pending"
    assert not started["box-3"].is_set()
    assert calls == [["box-1"], ["box-2"]]


def test_whole_manual_skips_pages_already_submitted(service, parallel_manual):
    task, started, release, calls = parallel_manual
    first = service.recognize(task["id"], task["pages"][0]["id"])
    assert started["box-1"].wait(3)
    remaining = service.recognize(task["id"])
    assert remaining["page_numbers"] == [2, 3, 4] and remaining["total"] == 3
    assert started["box-2"].wait(3)
    with pytest.raises(ValueError, match="没有需要"):
        service.recognize(task["id"])
    release["box-1"].set()
    release["box-2"].set()
    assert wait_job(service, first["id"])["status"] == "completed"
    assert wait_job(service, remaining["id"])["status"] == "completed"
    assert calls == [["box-1"], ["box-2", "box-3", "box-4"]]


def test_reopened_queue_does_not_leave_page_locks(service, task):
    page = task["pages"][0]
    with service.store.connect() as db:
        db.execute(
            "INSERT INTO jobs(id,task_id,status,total,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            ("abandoned", task["id"], "queued", 1, "now", "now"),
        )
        db.execute("INSERT INTO job_pages VALUES (?,?)", ("abandoned", page["id"]))
    reopened = Service(service.store.root)
    try:
        assert reopened.job("abandoned")["status"] == "interrupted"
        reopened.save_page(page["id"], [box()], 0)
    finally:
        reopened.close()


def test_state_endpoint_rejects_page_from_another_task(service, task):
    other = service.import_images([(picture(), "other.png")])
    client = create_app(service, "state-token").test_client()
    client.get("/session?token=state-token")
    assert (
        client.get(f"/api/tasks/{task['id']}/recognition-state?page_id={other['pages'][0]['id']}").status_code
        == 400
    )
    state = client.get(f"/api/tasks/{task['id']}/recognition-state?page_id={task['pages'][0]['id']}").json
    assert state["page"]["id"] == task["pages"][0]["id"] and state["jobs"] == []
