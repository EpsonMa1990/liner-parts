from __future__ import annotations

import hmac
import io
from pathlib import Path

from flask import Flask, jsonify, redirect, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException

from .documents import IMAGE_EXTENSIONS
from .service import MAX_FILE, ConflictError


def create_app(service, token):
    assets = Path(__file__).parent / "web_dist"
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = MAX_FILE + 1024 * 1024
    app.config["LOCAL_HOST"] = "localhost"
    cookie_name = "liner_" + token[:12]

    @app.before_request
    def local_session():
        if request.host != app.config["LOCAL_HOST"]:
            return jsonify(error="请求来源无效。"), 403
        origin = request.headers.get("Origin")
        if origin and origin != "http://" + request.host:
            return jsonify(error="请求来源无效。"), 403
        if request.path == "/session" and request.method == "GET":
            if not hmac.compare_digest(request.args.get("token", ""), token):
                return jsonify(error="本地会话已失效，请重新打开应用。"), 401
            response = redirect("/")
            response.set_cookie(cookie_name, token, httponly=True, samesite="Strict")
            return response
        if not hmac.compare_digest(request.cookies.get(cookie_name, ""), token):
            return jsonify(error="本地会话已失效，请重新打开应用。"), 401
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and request.headers.get("X-Liner-Client") != "desktop"
        ):
            return jsonify(error="请求校验失败。"), 403

    @app.after_request
    def response_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    @app.errorhandler(Exception)
    def error_response(exc):
        if isinstance(exc, ConflictError):
            code, message = 409, str(exc)
        elif isinstance(exc, LookupError):
            code, message = 404, str(exc)
        elif isinstance(exc, ValueError):
            code, message = 400, str(exc)
        elif isinstance(exc, HTTPException):
            code = exc.code
            message = "文件超过 128 MB。" if code == 413 else "请求格式无效。"
        else:
            code, message = 500, "操作失败，请检查文件是否可用及磁盘空间后重试。"
        return jsonify(error=message), code

    def body():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError("请求需要为 JSON 对象。")
        return data

    @app.get("/")
    def index():
        if not (assets / "index.html").exists():
            return "界面尚未构建，请先在 frontend 目录运行 npm ci 和 npm run build。", 503
        return send_from_directory(assets, "index.html")

    @app.get("/assets/<path:name>")
    def asset(name):
        return send_from_directory(assets / "assets", name)

    @app.get("/api/tasks")
    def tasks():
        return jsonify(service.tasks())

    @app.post("/api/tasks/import")
    def import_task():
        files = request.files.getlist("file")
        if not files:
            raise ValueError("请选择 PDF、说明书图片或 .liner 项目文件。")
        if all(Path(file.filename or "").suffix.lower() in IMAGE_EXTENSIONS for file in files):
            return jsonify(
                service.import_images(
                    [(file.stream, file.filename) for file in files], request.form.get("title", "")
                )
            )
        if len(files) != 1:
            raise ValueError("PDF 或项目文件每次只能选一个；多张图片可以一起导入。")
        file = files[0]
        if (file.filename or "").lower().endswith(".liner"):
            return jsonify(service.import_project(file.stream))
        return jsonify(
            service.import_pdf(file.stream, file.filename or "说明书.pdf", request.form.get("title", ""))
        )

    @app.post("/api/tasks/<task_id>/images")
    def append_images(task_id):
        files = request.files.getlist("file")
        return jsonify(
            service.import_images([(file.stream, file.filename or "") for file in files], task_id=task_id)
        )

    @app.post("/api/tasks/demo")
    def demo():
        return jsonify(service.demo())

    @app.get("/api/tasks/<task_id>")
    def task(task_id):
        return jsonify(service.task(task_id))

    @app.patch("/api/tasks/<task_id>")
    def rename_task(task_id):
        return jsonify(service.rename(task_id, body().get("title", "")))

    @app.delete("/api/tasks/<task_id>")
    def delete_task(task_id):
        service.delete(task_id)
        return jsonify(ok=True)

    @app.get("/api/pages/<page_id>")
    def page(page_id):
        return jsonify(service.page(page_id))

    @app.put("/api/pages/<page_id>")
    def save_page(page_id):
        data = body()
        return jsonify(service.save_page(page_id, data.get("boxes"), data.get("revision")))

    @app.get("/api/pages/<page_id>/image")
    def page_image(page_id):
        return send_file(
            io.BytesIO(service.image(page_id, request.args.get("box"), request.args.get("thumb") == "1")),
            mimetype="image/png",
        )

    @app.get("/api/pages/<page_id>/crop")
    def crop_preview(page_id):
        try:
            geometry = {key: float(request.args[key]) for key in ("x", "y", "width", "height")}
        except (KeyError, ValueError):
            raise ValueError("截图坐标无效。") from None
        return send_file(io.BytesIO(service.crop_preview(page_id, geometry)), mimetype="image/png")

    @app.get("/api/tasks/<task_id>/summary")
    def summary(task_id):
        return jsonify(service.summary(task_id))

    @app.get("/api/tasks/<task_id>/export/<kind>")
    def export(task_id, kind):
        if kind not in ("xlsx", "liner"):
            raise ValueError("导出格式无效。")
        data = service.export_excel(task_id) if kind == "xlsx" else service.export_project(task_id)
        return send_file(
            io.BytesIO(data),
            as_attachment=True,
            download_name=service.task(task_id)["title"] + "." + kind,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if kind == "xlsx"
            else "application/zip",
        )

    @app.get("/api/settings")
    def settings():
        return jsonify(service.settings.public())

    @app.put("/api/settings")
    def save_settings():
        return jsonify(service.settings.save(body()))

    @app.post("/api/settings/test")
    def test_connection():
        return jsonify(service.test_connection())

    @app.get("/api/settings/models")
    def models():
        return jsonify(service.models())

    @app.post("/api/tasks/<task_id>/recognize")
    def recognize(task_id):
        data = body()
        return jsonify(
            service.recognize(task_id, data.get("page_id"), data.get("box_ids"), data.get("mode", "pending"))
        )

    @app.get("/api/jobs/<job_id>")
    def job(job_id):
        return jsonify(service.job(job_id))

    @app.get("/api/tasks/<task_id>/recognition-state")
    def recognition_state(task_id):
        return jsonify(service.recognition_state(task_id, request.args.get("page_id")))

    @app.post("/api/jobs/<job_id>/cancel")
    def cancel_job(job_id):
        return jsonify(service.cancel(job_id))

    @app.get("/api/platform/session")
    def platform_session():
        return jsonify(service.sharing.session())

    @app.post("/api/platform/login")
    def platform_login():
        return jsonify(service.sharing.login(body()))

    @app.post("/api/platform/logout")
    def platform_logout():
        return jsonify(service.sharing.logout())

    @app.post("/api/pages/<page_id>/confirm")
    def confirm_page(page_id):
        return jsonify(service.sharing.confirm_page(page_id, body()))

    @app.get("/api/tasks/<task_id>/share")
    def share_state(task_id):
        return jsonify(service.sharing.state(task_id, request.args.get("refresh") == "1"))

    @app.post("/api/tasks/<task_id>/share")
    def share_task(task_id):
        return jsonify(service.sharing.start(task_id, body()))

    return app
