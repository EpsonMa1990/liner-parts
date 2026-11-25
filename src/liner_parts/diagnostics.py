"""Exercise the real WebView2 engine and close-save bridge without any external API."""

import io
import json
import secrets
import tempfile
import threading
import time
import zipfile
from pathlib import Path

import httpx
import webview
from PIL import Image
from waitress import create_server

from liner_parts.__main__ import DesktopBridge
from liner_parts.server import create_app
from liner_parts.service import Service


class SmokeBridge(DesktopBridge):
    def __init__(self, service):
        super().__init__(service)
        self._report = None
        self._received = threading.Event()

    def report_test(self, data):
        self._report = data
        self._received.set()


def check_parallel_recognition(service, task):
    """Use a held local fake to prove both packaged worker threads really start."""
    started = [threading.Event(), threading.Event()]
    release = threading.Event()
    factory = service.recognizer_factory
    original_model = service.settings.data["model"]

    class OfflineRecognizer:
        def __init__(self, config):
            pass

        def recognize(self, crops, cancel):
            index = int(crops[0][0][-1])
            started[index].set()
            assert release.wait(10), "Offline smoke requests were not released"
            return {
                box_id: {"runner": "A", "part_number": "03", "status": "recognized"} for box_id, _ in crops
            }, {}

        def close(self):
            pass

    service.recognizer_factory = OfflineRecognizer
    service.settings.data["model"] = "offline-smoke"
    submitted = []
    try:
        for index, page in enumerate(task["pages"]):
            service.save_page(
                page["id"], [{"id": f"offline-{index}", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1}], 0
            )
            submitted.append(service.recognize(task["id"], page["id"]))
        assert all(event.wait(4) for event in started), "Both recognition workers must start concurrently"
    finally:
        release.set()
        deadline = time.monotonic() + 5
        while (
            any(service.job(job["id"])["status"] in ("queued", "running", "cancelling") for job in submitted)
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)
        service.recognizer_factory = factory
        service.settings.data["model"] = original_model
    assert all(service.job(job["id"])["status"] == "completed" for job in submitted)


def check_sharing(service, task):
    for page in task["pages"]:
        page = service.page(page["id"])
        boxes = [{**box, "category": "头"} for box in page["boxes"]]
        page = service.save_page(page["id"], boxes, page["revision"])
        service.sharing.confirm_page(page["id"], {"revision": page["revision"]})
    raw = service.sharing.package("离线分享自检", [service.page(p["id"]) for p in task["pages"]])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert len(manifest["pages"]) == 2
        assert "crops/0001-0001.png" in archive.namelist()

    def platform(request):
        assert request.headers.get("Authorization") == "Bearer offline-platform-jwt"
        if request.url.path.endswith("/auth/me"):
            data = {"id": 1, "name": "离线用户", "has_password": True}
        elif request.url.path.endswith("/capabilities"):
            data = {"version": 1, "reward_cards": 5}
        else:
            assert request.method == "POST" and b"PK\x03\x04" in request.content
            data = {"id": 1, "status": "pending", "post_id": 0, "model_name": "离线分享自检"}
        return httpx.Response(200, json={"code": 200, "data": data})

    service.sharing.transport = httpx.MockTransport(platform)
    service.sharing.login({"token": "offline-platform-jwt"})
    service.sharing.start(task["id"], {"model_name": "离线分享自检", "all_model_complete": True})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        state = service.sharing.state(task["id"])
        if state["job"]["status"] not in ("packing", "uploading"):
            break
        time.sleep(0.05)
    assert state["job"]["status"] == "submitted", state
    assert state["receipt"]["status"] == "pending"
    service.sharing.logout()
    service.sharing.transport = None


def main(report_path=None):
    failures = []
    with tempfile.TemporaryDirectory(prefix="liner-native-smoke-") as directory:
        service = Service(Path(directory))
        task = service.demo()
        # Exercise the packaged image decoders, source storage, crop path and v2 backup too.
        sample = service.image(task["pages"][0]["id"])
        image_task = service.import_images([(io.BytesIO(sample), "native-image.png")])
        image_task = service.import_images(
            [(io.BytesIO(sample), "native-page2.png")], task_id=image_task["id"]
        )
        preview = service.crop_preview(
            image_task["pages"][0]["id"], {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.2}
        )
        with Image.open(io.BytesIO(preview)) as image:
            assert image.width > 0 and image.height > 0
        restored = service.import_project(io.BytesIO(service.export_project(image_task["id"])))
        assert restored["source_type"] == "images" and restored["page_count"] == 2
        assert service.image(restored["pages"][0]["id"]) == sample
        check_parallel_recognition(service, image_task)
        check_sharing(service, image_task)
        service.delete(restored["id"])
        service.delete(image_task["id"])
        token = secrets.token_urlsafe(32)
        app = create_app(service, token)
        server = create_server(app, host="127.0.0.1", port=0, threads=4)
        app.config["LOCAL_HOST"] = f"127.0.0.1:{server.effective_port}"
        threading.Thread(target=server.run, daemon=True).start()
        bridge = SmokeBridge(service)
        window = webview.create_window(
            "Liner native integration test",
            f"http://{app.config['LOCAL_HOST']}/session?token={token}",
            js_api=bridge,
            width=1280,
            height=850,
            hidden=True,
        )
        bridge._window = window
        window.events.closing += bridge._on_closing

        def driver():
            try:
                print("Desktop integration driver started", flush=True)
                deadline = time.monotonic() + 20
                while not bridge._ready and time.monotonic() < deadline:
                    time.sleep(0.1)
                assert bridge._ready, "Vue did not connect to the Python bridge"
                print("Vue connected to Python bridge", flush=True)
                window.run_js("""
                    (async () => {
                        const pause = () => new Promise(resolve => setTimeout(resolve, 100));
                        for(let i=0; i<100 && !document.querySelector('.task-open'); i++) await pause();
                        document.querySelector('.task-open').click();
                        for(let i=0; i<100 && !document.querySelector('.inspector-header .icon-btn'); i++) await pause();
                        document.querySelector('.inspector-header .icon-btn').click();
                        await pause();
                        const runner = document.querySelector('input[aria-label="板件"]');
                        const part = document.querySelector('input[aria-label="零件号"]');
                        runner.value = 'A1'; runner.dispatchEvent(new Event('input', {bubbles:true}));
                        await pause();
                        part.value = '003'; part.dispatchEvent(new Event('input', {bubbles:true}));
                        await window.pywebview.api.report_test({title: document.querySelector('.work-title h1').textContent, bridge: true});
                    })().catch(e => window.pywebview.api.report_test({error: String(e)}));
                """)
                assert bridge._received.wait(20), "Desktop UI test did not report back"
                assert not bridge._report.get("error"), bridge._report
                assert bridge._report["bridge"]
                print("Native edits submitted; checking close-save", flush=True)
                # Close while edits are still inside the debounce interval.
                window.destroy()
            except BaseException as exc:
                failures.append(str(exc))
                bridge._allow_close = True
                window.destroy()

        webview.start(driver, gui="edgechromium", debug=False)
        server.close()
        page = service.page(task["pages"][0]["id"])
        service.close()
        assert not failures, failures
        assert len(page["boxes"]) == 1, "Closing lost unsaved box"
        assert page["boxes"][0]["part_number"] == "003", "Closing lost last text edit"
        report = {
            "webview2": "passed",
            "python_bridge": "passed",
            "save_before_close": "passed",
            "image_pages": "passed",
            "image_backup": "passed",
            "crop_preview": "passed",
            "parallel_recognition": "passed",
            "desktop_sharing": "passed",
        }
        if report_path:
            Path(report_path).write_text(json.dumps(report, indent=2), "utf-8")
        print(json.dumps(report))


if __name__ == "__main__":
    main()
