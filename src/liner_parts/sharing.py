"""Completed-model snapshots and authenticated, moderated platform sharing.

The platform JWT stays in memory and is independent of the recognition API key.
Only the explicit manifest fields and PNG images leave the local project.
"""

from __future__ import annotations

import io
import json
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor

import httpx

PLATFORM_URL = "https://agamaship.com"
API_URL = PLATFORM_URL + "/api/liner"
MAX_SHARE = 128 * 1024 * 1024
BOX_FIELDS = ("x", "y", "width", "height", "category", "quantity", "runner", "part_number", "status")


def complete_boxes(boxes):
    return all(
        b["status"] in ("recognized", "manual")
        and all(b[k].strip() for k in ("category", "runner", "part_number"))
        for b in boxes
    )


class Sharing:
    def __init__(self, service, transport=None):
        self.service = service
        self.transport = transport
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="share")
        self.token = ""
        self.user = None
        self.jobs = {}

    def close(self):
        self.executor.shutdown(wait=True)
        self.token = ""

    def request(self, method, path, token="", **kwargs):
        try:
            timeout = httpx.Timeout(600 if path == "/square/desktop-submissions" else 30, connect=15)
            with httpx.Client(transport=self.transport, timeout=timeout, follow_redirects=False) as client:
                r = client.request(
                    method,
                    API_URL + path,
                    headers={"Authorization": "Bearer " + token} if token else {},
                    **kwargs,
                )
            if r.status_code in (401, 403):
                raise ValueError("平台登录已失效或无权限，请重新登录；新账号请先在网站设置密码。")
            if r.status_code == 404:
                raise ValueError("平台尚未开放桌面分享接口，请等待网站更新后重试。")
            r.raise_for_status()
            data = r.json()
            if data.get("code") != 200:
                raise ValueError(str(data.get("msg", "平台操作失败"))[:300])
            return data["data"]
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError):
            raise ValueError("平台连接失败，请检查网络后重试。重复提交同一内容不会重复发卡。") from None

    def session(self):
        with self.lock:
            return {"user": self.user, "platform_url": PLATFORM_URL}

    def login(self, data):
        token = str(data.get("token", "")).strip().removeprefix("Bearer ")
        if not token:
            result = self.request(
                "POST",
                "/auth/password/login",
                json={
                    "account": str(data.get("account", "")).strip(),
                    "password": str(data.get("password", "")),
                },
            )
            token = result.get("token", "")
        if not token or len(token) > 8192 or "\r" in token or "\n" in token:
            raise ValueError("平台 JWT 无效。")
        user = self.request("GET", "/auth/me", token)
        if not user.get("has_password"):
            raise ValueError("请先在官网完成账号设置并设置登录密码，再提交分享。")
        with self.lock:
            self.token = token
            self.user = {k: user.get(k) for k in ("id", "name")}
        return self.session()

    def logout(self):
        with self.lock:
            self.token, self.user = "", None
        return self.session()

    def confirm_page(self, page_id, data):
        s = self.service
        with s.lock:
            page = s.page(page_id)
            s._assert_page_idle(page)
            if data.get("revision") != page["revision"]:
                raise ValueError("页面已修改，请保存并重新确认。")
            if not complete_boxes(page["boxes"]):
                raise ValueError("请处理本页全部标记，并填写分类、板件、零件号和数量后确认。")
            reason = str(data.get("no_parts_reason", "")).strip()[:200]
            if not page["boxes"] and not reason:
                raise ValueError("无标记的页面请说明原因，例如封面、目录或无取件内容。")
            with s.store.connect() as db:
                db.execute(
                    "UPDATE pages SET confirmed_revision=revision,no_parts_reason=? WHERE id=?",
                    (reason if not page["boxes"] else "", page_id),
                )
            return s.page(page_id)

    def readiness(self, task_id):
        s = self.service
        with s.lock:
            task = s.task(task_id)
            pending = []
            for p in task["pages"]:
                boxes = s.store.boxes(p["id"])
                if (
                    p["confirmed_revision"] != p["revision"]
                    or not complete_boxes(boxes)
                    or (not boxes and not p["no_parts_reason"])
                ):
                    pending.append(p["page_index"] + 1)
            running = bool(s._busy_pages(task_id))
            return {
                "ready": not pending and not running and task["box_count"] > 0,
                "pending_pages": pending,
                "confirmed": len(task["pages"]) - len(pending),
                "total": len(task["pages"]),
                "running": running,
                "box_count": task["box_count"],
            }

    def assert_not_building(self, task_id):
        with self.lock:
            if self.jobs.get(task_id, {}).get("status") in ("packing", "uploading"):
                raise ValueError("此任务正在打包分享，请等待提交结束后删除。")

    def start(self, task_id, data):
        s = self.service
        name = str(data.get("model_name", "")).strip()
        if not name or len(name) > 120:
            raise ValueError("请填写模型名称，最多 120 字。")
        if data.get("all_model_complete") is not True:
            raise ValueError("请确认已完成整个模型的取件表。")
        # The snapshot is taken while the same lock guards page edits and recognition writes.
        with s.lock:
            if not self.readiness(task_id)["ready"]:
                raise ValueError("只有整份说明书逐页校对确认完成，且没有识别任务时，才可以提交分享。")
            self.assert_not_building(task_id)
            pages = [s.page(p["id"]) for p in s.task(task_id)["pages"]]
            if sum(len(p["boxes"]) for p in pages) > 10000:
                raise ValueError("单份分享最多包含 10000 个零件标记。")
            with self.lock:
                if not self.token or not self.user:
                    raise ValueError("请先登录线上平台。")
                token, user_id = self.token, self.user["id"]
                self.jobs[task_id] = {"status": "packing", "message": "正在准备完整模型分享包…"}
            self.executor.submit(self._submit, task_id, name, pages, token, user_id)
        return self.state(task_id)

    def package(self, name, pages):
        output = io.BytesIO()
        manifest = {
            "format": "liner-desktop-share",
            "version": 1,
            "model_name": name,
            "all_model_complete": True,
            "pages": [],
        }
        total = 0
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:

            def put(path, raw):
                nonlocal total
                total += len(raw)
                if total > MAX_SHARE or len(raw) > 20 * 1024 * 1024:
                    raise ValueError("分享包超过 128 MB 或单张图片超过 20 MB，请缩小源图片后重试。")
                archive.writestr(path, raw)

            for i, page in enumerate(pages, 1):
                image_file = f"pages/{i:04d}.png"
                put(image_file, self.service._page_image(page))
                entry = {
                    "index": i,
                    "image_file": image_file,
                    "confirmed": True,
                    "no_parts_reason": page["no_parts_reason"],
                    "boxes": [],
                }
                for j, box in enumerate(page["boxes"], 1):
                    crop_file = f"crops/{i:04d}-{j:04d}.png"
                    put(crop_file, self.service._page_image(page, geometry=box))
                    entry["boxes"].append(
                        {"sequence": j, "crop_file": crop_file, **{k: box[k] for k in BOX_FIELDS}}
                    )
                manifest["pages"].append(entry)
            put("manifest.json", json.dumps(manifest, ensure_ascii=False).encode())
        if output.tell() > MAX_SHARE:
            raise ValueError("分享包超过 128 MB，请缩小源图片后重试。")
        return output.getvalue()

    def _submit(self, task_id, name, pages, token, user_id):
        try:
            capability = self.request("GET", "/square/desktop-submissions/capabilities", token)
            if capability.get("version") != 1 or capability.get("reward_cards") != 5:
                raise ValueError("平台分享协议已变更，请更新桌面软件后重试。")
            raw = self.package(name, pages)
            with self.lock:
                self.jobs[task_id] = {"status": "uploading", "message": "正在提交审核，请保持应用打开…"}
            receipt = self.request(
                "POST",
                "/square/desktop-submissions",
                token,
                files={"file": ("parts.zip", raw, "application/zip")},
            )
            with self.service.store.connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO share_receipts VALUES(?,?,?,?)",
                    (task_id, receipt["id"], user_id, json.dumps(receipt, ensure_ascii=False)),
                )
            with self.lock:
                self.jobs[task_id] = {"status": "submitted", "message": "提交已完成，可刷新查看审核状态。"}
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else "分享打包或提交失败，请重试。"
            with self.lock:
                self.jobs[task_id] = {"status": "failed", "message": message}

    def state(self, task_id, refresh=False):
        self.service.task_exists(task_id)
        row = self.service.store.one("SELECT * FROM share_receipts WHERE task_id=?", (task_id,))
        with self.lock:
            job = dict(self.jobs.get(task_id, {}))
            token, user_id = self.token, (self.user or {}).get("id")
        receipt = json.loads(row["data"]) if row and row["user_id"] == user_id else None
        if refresh and receipt and token:
            receipt = self.request("GET", f"/square/desktop-submissions/{receipt['id']}", token)
            with self.service.store.connect() as db:
                db.execute(
                    "UPDATE share_receipts SET data=? WHERE task_id=? AND user_id=?",
                    (json.dumps(receipt, ensure_ascii=False), task_id, user_id),
                )
        return {"job": job, "receipt": receipt, **self.readiness(task_id)}
