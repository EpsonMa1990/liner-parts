from __future__ import annotations

import argparse
import re
import secrets
import sys
import threading
import webbrowser
from pathlib import Path

from platformdirs import user_data_path
from waitress import create_server

from .instance import InstanceLock
from .server import create_app
from .service import Service


class DesktopBridge:
    def __init__(self, service):
        self._service = service
        self._window = None
        self._ready = False
        self._allow_close = False

    def ready(self):
        self._ready = True

    def finish_close(self):
        self._allow_close = True
        self._window.destroy()

    def _on_closing(self):
        if self._allow_close or not self._ready:
            return True
        # FormClosing runs on the UI thread. Queue JS on a worker so WebView2 can
        # process it after this event returns, rather than deadlocking its message loop.
        threading.Thread(
            target=self._window.run_js,
            args=('window.dispatchEvent(new Event("liner-request-close"))',),
            daemon=True,
        ).start()
        return False

    def save_export(self, task_id, kind):
        import webview

        try:
            if kind not in ("xlsx", "liner"):
                raise ValueError("导出格式无效。")
            task = self._service.task(task_id)
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", task["title"]).strip(". ") or "取件表"
            result = self._window.create_file_dialog(
                webview.FileDialog.SAVE,
                save_filename=name + "." + kind,
                file_types=(f"Liner export (*.{kind})",),
            )
            if not result:
                return {"cancelled": True}
            path = Path(result if isinstance(result, str) else result[0])
            if path.suffix.lower() != "." + kind:
                path = path.with_name(path.name + "." + kind)
            data = (
                self._service.export_excel(task_id)
                if kind == "xlsx"
                else self._service.export_project(task_id)
            )
            path.write_bytes(data)
            return {"saved": True, "name": path.name}
        except Exception:
            return {"error": "导出失败，请确认文件未被其他应用占用，并选择可写入的目录。"}


def main():
    parser = argparse.ArgumentParser(description="Agamaship取件表制作工作台")
    parser.add_argument("--data-dir", type=Path, help="本地项目和设置保存目录")
    parser.add_argument("--browser", action="store_true", help="使用本机浏览器打开（开发或桌面组件不可用时）")
    parser.add_argument(
        "--no-open", action="store_true", help="只启动本地服务并输出访问地址，需同时使用 --browser"
    )
    parser.add_argument("--port", type=int, default=0, help="本地端口，默认随机空闲端口")
    parser.add_argument(
        "--self-check", type=Path, help="运行离线 Windows 桌面自检，并将结果写入指定 JSON 文件"
    )
    args = parser.parse_args()
    if args.self_check:
        from .diagnostics import main as self_check

        self_check(args.self_check)
        return
    root = args.data_dir or user_data_path("LinerParts", appauthor=False)
    instance_lock = InstanceLock(root)
    service = Service(root)
    token = secrets.token_urlsafe(32)
    app = create_app(service, token)
    server = create_server(
        app, host="127.0.0.1", port=args.port, threads=6, max_request_body_size=130 * 1024 * 1024
    )
    app.config["LOCAL_HOST"] = f"127.0.0.1:{server.effective_port}"
    url = f"http://127.0.0.1:{server.effective_port}/session?token={token}"
    try:
        if args.browser:
            print(f"Agamaship: {url}", flush=True)
            print(f"Data: {service.store.root}", flush=True)
            if not args.no_open:
                webbrowser.open(url)
            server.run()
        else:
            import webview

            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            bridge = DesktopBridge(service)
            window = webview.create_window(
                "Agamaship取件表制作工作台",
                url,
                js_api=bridge,
                width=1480,
                height=940,
                min_size=(1000, 680),
                background_color="#F5F7FB",
            )
            bridge._window = window
            window.events.closing += bridge._on_closing
            icon = Path(__file__).parent / "web_dist" / ("logo.ico" if sys.platform == "win32" else "logo.png")
            webview.start(
                gui="edgechromium" if sys.platform == "win32" else None,
                icon=str(icon),
                debug=False,
            )
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        service.close()
        instance_lock.close()


if __name__ == "__main__":
    main()
