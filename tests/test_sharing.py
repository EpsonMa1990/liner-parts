import io
import json
import threading
import time
import zipfile

import httpx
import pytest
from PIL import Image

from liner_parts.server import create_app
from liner_parts.sharing import API_URL

from .conftest import box


def completed(service, task):
    p1, p2 = task["pages"]
    page = service.save_page(p1["id"], [box(runner="A1", part_number="003", status="manual", quantity=2)], 0)
    service.sharing.confirm_page(p1["id"], {"revision": page["revision"]})
    service.sharing.confirm_page(p2["id"], {"revision": 0, "no_parts_reason": "工具介绍"})
    return p1, p2


def test_whole_model_completion_and_invalidation(service, task):
    p1, p2 = task["pages"]
    sharing = service.sharing
    assert sharing.readiness(task["id"])["pending_pages"] == [1, 2]
    with pytest.raises(ValueError, match="原因"):
        sharing.confirm_page(p2["id"], {"revision": 0})
    service.save_page(p1["id"], [box()], 0)
    with pytest.raises(ValueError, match="全部标记"):
        sharing.confirm_page(p1["id"], {"revision": 1})
    page = service.save_page(p1["id"], [box(runner="A1", part_number="03", status="manual", category="")], 1)
    with pytest.raises(ValueError, match="分类"):
        sharing.confirm_page(p1["id"], {"revision": page["revision"]})
    page = service.save_page(p1["id"], [box(runner="A1", part_number="03", status="manual")], 2)
    sharing.confirm_page(p1["id"], {"revision": 3})
    sharing.confirm_page(p2["id"], {"revision": 0, "no_parts_reason": "封底"})
    assert sharing.readiness(task["id"])["ready"]
    service.save_page(p1["id"], page["boxes"], 3)
    assert sharing.readiness(task["id"])["pending_pages"] == [1]
    with pytest.raises(ValueError, match="页面已修改"):
        sharing.confirm_page(p1["id"], {"revision": 3})


def test_package_pages_crops_results_and_no_credentials(service, task):
    completed(service, task)
    service.settings.save({"api_key": "PRIVATE-MODEL-KEY", "prompt": "PRIVATE-PROMPT"})
    pages = [service.page(p["id"]) for p in task["pages"]]
    pages[0]["boxes"][0]["note"] = "PRIVATE-NOTE"
    raw = service.sharing.package("MG 测试模型", pages)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "pages/0001.png",
            "pages/0002.png",
            "crops/0001-0001.png",
        }
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["all_model_complete"] is True
        assert manifest["pages"][1]["no_parts_reason"] == "工具介绍"
        first = manifest["pages"][0]["boxes"][0]
        assert first["runner"] == "A1" and first["part_number"] == "003" and first["quantity"] == 2
        for name in archive.namelist():
            assert b"PRIVATE" not in archive.read(name)
            if name.endswith("png"):
                Image.open(io.BytesIO(archive.read(name))).verify()


def test_login_jwt_verified_and_memory_only(service):
    requests = []

    def mock(req):
        requests.append(req)
        if req.url.path.endswith("/login"):
            assert json.loads(req.content)["password"] == "secret-password"
            return httpx.Response(200, json={"code": 200, "data": {"token": "test-jwt"}})
        assert req.headers["Authorization"] == "Bearer test-jwt"
        return httpx.Response(
            200, json={"code": 200, "data": {"id": 7, "name": "作者", "has_password": True}}
        )

    service.sharing.transport = httpx.MockTransport(mock)
    user = service.sharing.login({"account": "name", "password": "secret-password"})
    assert user["user"]["id"] == 7 and "token" not in user
    assert all(str(req.url).startswith(API_URL) for req in requests)
    service.sharing.logout()
    assert service.sharing.session()["user"] is None
    service.sharing.login({"token": "Bearer test-jwt"})
    for path in service.store.root.rglob("*"):
        if path.is_file():
            assert b"test-jwt" not in path.read_bytes() and b"secret-password" not in path.read_bytes()


def test_submission_is_async_and_uses_immutable_snapshot(service, task):
    p1, _ = completed(service, task)
    entered, release = threading.Event(), threading.Event()
    captured = []

    def mock(req):
        if req.url.path.endswith("/capabilities"):
            entered.set()
            assert release.wait(10)
            return httpx.Response(200, json={"code": 200, "data": {"version": 1, "reward_cards": 5}})
        assert req.method == "POST"
        captured.append(req.content)
        return httpx.Response(
            200,
            json={"code": 200, "data": {"id": 41, "model_name": "测试", "status": "pending", "post_id": 0}},
        )

    sharing = service.sharing
    sharing.transport = httpx.MockTransport(mock)
    sharing.token = "platform-jwt"
    sharing.user = {"id": 7, "name": "作者"}
    try:
        state = sharing.start(task["id"], {"model_name": "测试", "all_model_complete": True})
        assert state["job"]["status"] == "packing" and entered.wait(2)
        with pytest.raises(ValueError, match="打包分享"):
            service.delete(task["id"])
        service.save_page(p1["id"], [box(runner="CHANGED", part_number="99", status="manual")], 1)
        release.set()
        deadline = time.monotonic() + 10
        while (
            sharing.state(task["id"])["job"]["status"] in ("packing", "uploading")
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        state = sharing.state(task["id"])
        assert state["job"]["status"] == "submitted" and state["receipt"]["id"] == 41
        assert not state["ready"]
        body = captured[0]
        raw = body[body.index(b"PK\x03\x04") : body.rfind(b"\r\n--")]
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            m = json.loads(archive.read("manifest.json"))
            assert m["pages"][0]["boxes"][0]["runner"] == "A1"
        sharing.logout()
        assert sharing.state(task["id"])["receipt"] is None
    finally:
        release.set()


@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_platform_errors_are_actionable(service, status):
    service.sharing.transport = httpx.MockTransport(lambda _: httpx.Response(status))
    with pytest.raises(ValueError, match="登录|接口|连接"):
        service.sharing.login({"token": "expired"})
    assert service.sharing.session()["user"] is None


def test_share_routes_require_completion_login_and_declaration(service, task):
    app = create_app(service, "local")
    client = app.test_client()
    client.get("/session?token=local")
    headers = {"X-Liner-Client": "desktop"}
    url = f"/api/tasks/{task['id']}/share"
    assert client.post(url, json={}, headers=headers).status_code == 400
    data = {"model_name": "测试", "all_model_complete": True}
    assert "逐页" in client.post(url, json=data, headers=headers).json["error"]
    completed(service, task)
    assert "登录" in client.post(url, json=data, headers=headers).json["error"]
    assert client.post(url, json=data).status_code == 403


def test_active_recognition_prevents_completion_and_sharing(service, task):
    p1, _ = completed(service, task)
    with service.store.connect() as db:
        db.execute("INSERT INTO jobs VALUES('running',?,'running',1,0,0,'','now','now')", (task["id"],))
        db.execute("INSERT INTO job_pages VALUES('running',?)", (p1["id"],))
    assert not service.sharing.readiness(task["id"])["ready"]
    with pytest.raises(ValueError, match="本页正在"):
        service.sharing.confirm_page(p1["id"], {"revision": 1})
