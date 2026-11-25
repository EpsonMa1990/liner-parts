from __future__ import annotations

import io
import json
import math
import re
import shutil
import tempfile
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from . import documents
from .recognition import Recognizer
from .settings import Settings
from .sharing import Sharing
from .stitching import BATCH_SIZE
from .storage import Store

MAX_FILE = 128 * 1024 * 1024
ACTIVE = ("queued", "running", "cancelling")
RECOGNITION_WORKERS = 2
STATES = {"pending", "recognized", "review", "manual", "error"}


class ConflictError(ValueError):
    pass


def now():
    return datetime.now(UTC).isoformat(timespec="microseconds")


def identifier():
    return uuid.uuid4().hex


def clean_text(value, limit=500):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"文字字段需要为字符串且不超过 {limit} 字符。")
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value).strip()


def validate_box(item):
    if not isinstance(item, dict) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", str(item.get("id", ""))):
        raise ValueError("标记框 ID 无效。")
    result = {"id": item["id"]}
    for field in ("x", "y", "width", "height"):
        value = item.get(field)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError("标记框坐标无效。")
        if value < 0 or value > 1:
            raise ValueError("标记框必须位于页面内。")
        result[field] = value
    if result["width"] < 0.001 or result["height"] < 0.001:
        raise ValueError("标记框太小，请重新框选。")
    if result["x"] + result["width"] > 1.00001 or result["y"] + result["height"] > 1.00001:
        raise ValueError("标记框超出页面范围。")
    quantity = item.get("quantity", 1)
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 9999:
        raise ValueError("数量需要为 1–9999 的整数。")
    result["quantity"] = quantity
    for field in ("category", "runner", "part_number", "raw_text", "note"):
        result[field] = clean_text(item.get(field, ""))
    status = item.get("status", "pending")
    if status not in STATES:
        raise ValueError("标记框状态无效。")
    if status in ("recognized", "manual") and not (result["runner"] and result["part_number"]):
        status = "review"
    result["status"] = status
    return result


class Service:
    def __init__(self, root: Path, recognizer_factory=Recognizer):
        self.store = Store(root)
        self.settings = Settings(self.store.root)
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=RECOGNITION_WORKERS, thread_name_prefix="recognition")
        self.cancellations = {}
        self.recognizer_factory = recognizer_factory
        self.sharing = Sharing(self)

    def close(self):
        with self.lock:
            for event in self.cancellations.values():
                event.set()
        self.executor.shutdown(wait=True, cancel_futures=False)
        self.sharing.close()

    def task(self, task_id):
        task = self.store.one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not task:
            raise LookupError("任务不存在或已删除。")
        task["pages"] = self.store.all("SELECT * FROM pages WHERE task_id=? ORDER BY page_index", (task_id,))
        total = ready = review = 0
        for page in task["pages"]:
            boxes = self.store.boxes(page["id"])
            page["box_count"] = len(boxes)
            page["ready_count"] = sum(b["status"] in ("recognized", "manual") for b in boxes)
            page["review_count"] = sum(b["status"] in ("review", "error") for b in boxes)
            total += len(boxes)
            ready += page["ready_count"]
            review += page["review_count"]
        task.update(box_count=total, ready_count=ready, review_count=review)
        image_count = sum(bool(p["image_file"]) for p in task["pages"])
        task["source_type"] = (
            "images" if image_count == len(task["pages"]) else "mixed" if image_count else "pdf"
        )
        task["status"] = "ready" if total and ready == total else "review" if review else "draft"
        task["job"] = self.store.one(
            "SELECT * FROM jobs WHERE task_id=? ORDER BY created_at DESC LIMIT 1", (task_id,)
        )
        task["jobs"] = self.jobs(task_id)
        return task

    def tasks(self):
        return [
            self.task(row["id"]) for row in self.store.all("SELECT id FROM tasks ORDER BY updated_at DESC")
        ]

    def page(self, page_id):
        page = self.store.one("SELECT * FROM pages WHERE id=?", (page_id,))
        if not page:
            raise LookupError("页面不存在。")
        page["boxes"] = self.store.boxes(page_id)
        return page

    def document_path(self, task_id):
        self.task_exists(task_id)
        return self.store.root / "documents" / task_id / "manual.pdf"

    def task_exists(self, task_id):
        if not self.store.one("SELECT id FROM tasks WHERE id=?", (task_id,)):
            raise LookupError("任务不存在。")

    def _assert_idle(self, task_id):
        job = self.store.one(
            "SELECT id FROM jobs WHERE task_id=? AND status IN ('queued','running','cancelling')", (task_id,)
        )
        if job:
            raise ConflictError("此任务正在识别，请先取消识别并等待当前请求结束。")

    def _busy_pages(self, task_id):
        return {
            row["page_id"]
            for row in self.store.all(
                "SELECT jp.page_id FROM job_pages jp JOIN jobs j ON j.id=jp.job_id "
                "WHERE j.task_id=? AND j.status IN ('queued','running','cancelling')",
                (task_id,),
            )
        }

    def _assert_page_idle(self, page):
        if page["id"] in self._busy_pages(page["task_id"]):
            raise ConflictError("本页正在识别或排队，请等待完成或取消后再编辑；其他页面可以继续操作。")

    def import_pdf(self, stream, filename, title=""):
        title = clean_text(title, 120) or Path(filename).stem[:120] or "未命名说明书"
        task_id = identifier()
        folder = self.store.root / "documents" / task_id
        folder.mkdir()
        try:
            path = folder / "manual.pdf"
            size = 0
            with path.open("wb") as out:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_FILE:
                        raise ValueError("文件超过 128 MB，请先压缩或拆分说明书。")
                    out.write(chunk)
            with path.open("rb") as source:
                if not source.read(1024).lstrip().startswith(b"%PDF-"):
                    raise ValueError("请选择有效的 PDF 说明书。")
            pages = documents.inspect_pdf(path)
            with self.store.connect() as db:
                db.execute(
                    "INSERT INTO tasks VALUES (?,?,?,?,?,?)",
                    (task_id, title, Path(filename).name[:200], now(), now(), len(pages)),
                )
                for index, (width, height) in enumerate(pages):
                    db.execute(
                        "INSERT INTO pages(id, task_id, page_index, width, height) VALUES (?,?,?,?,?)",
                        (identifier(), task_id, index, width, height),
                    )
            return self.task(task_id)
        except Exception:
            # folder is generated here, never accepted from a user or manifest.
            if folder.resolve().parent == (self.store.root / "documents").resolve():
                shutil.rmtree(folder)
            raise

    def import_images(self, files, title="", task_id=None):
        """Create an image manual, or append images atomically to an existing manual."""
        if not 1 <= len(files) <= documents.MAX_PAGES:
            raise ValueError(f"请选择 1 到 {documents.MAX_PAGES} 张图片。")
        title = clean_text(title, 120) or Path(files[0][1]).stem[:120] or "图片说明书"
        with tempfile.TemporaryDirectory(prefix="image-import-", dir=self.store.root) as temp:
            staged, input_bytes, stored_bytes = [], 0, 0
            for stream, filename in files:
                if Path(filename).suffix.lower() not in documents.IMAGE_EXTENSIONS:
                    raise ValueError("图片仅支持 PNG、JPG、JPEG、WebP 和 BMP，不能与 PDF 混选。")
                source = Path(temp) / "input"
                with source.open("wb") as out:
                    while chunk := stream.read(1024 * 1024):
                        input_bytes += len(chunk)
                        if input_bytes > MAX_FILE:
                            raise ValueError("本次所选图片合计超过 128 MB，请分批导入。")
                        out.write(chunk)
                page_id = identifier()
                image_file = page_id + ".png"
                destination = Path(temp) / image_file
                width, height = documents.normalize_image(source, destination)
                stored_bytes += destination.stat().st_size
                if stored_bytes > MAX_FILE:
                    raise ValueError("图片保存后超过 128 MB，请缩小图片后导入。")
                staged.append((page_id, image_file, width, height))
            with self.lock:
                existing = self.task(task_id) if task_id else None
                offset = existing["page_count"] if existing else 0
                if offset + len(staged) > documents.MAX_PAGES:
                    raise ValueError(f"每份说明书最多 {documents.MAX_PAGES} 页。")
                task_id = task_id or identifier()
                folder = self.store.root / "documents" / task_id
                existing_files = (
                    {p["image_file"] or "manual.pdf" for p in existing["pages"]} if existing else set()
                )
                if stored_bytes + sum((folder / name).stat().st_size for name in existing_files) > MAX_FILE:
                    raise ValueError("本项目说明书合计超过 128 MB，请缩小图片或新建任务。")
                folder.mkdir(exist_ok=True)
                created = []
                try:
                    with self.store.connect() as db:
                        if not existing:
                            db.execute(
                                "INSERT INTO tasks VALUES (?,?,?,?,?,?)",
                                (task_id, title, Path(files[0][1]).name[:200], now(), now(), len(staged)),
                            )
                        for index, (page_id, image_file, width, height) in enumerate(staged, offset):
                            target = folder / image_file
                            (Path(temp) / image_file).replace(target)
                            created.append(target)
                            db.execute(
                                "INSERT INTO pages(id,task_id,page_index,width,height,image_file) VALUES(?,?,?,?,?,?)",
                                (page_id, task_id, index, width, height, image_file),
                            )
                        db.execute(
                            "UPDATE tasks SET page_count=?,updated_at=? WHERE id=?",
                            (offset + len(staged), now(), task_id),
                        )
                except Exception:
                    for path in created:
                        path.unlink(missing_ok=True)
                    if not existing:
                        folder.rmdir()
                    raise
                return self.task(task_id)

    def demo(self):
        return self.import_pdf(
            io.BytesIO(documents.demo_pdf()), "练习说明书.pdf", "练习 · 认识你的第一张取件表"
        )

    def rename(self, task_id, title):
        title = clean_text(title, 120)
        if not title:
            raise ValueError("任务名称不能为空。")
        with self.lock, self.store.connect() as db:
            self.task_exists(task_id)
            db.execute("UPDATE tasks SET title=?, updated_at=? WHERE id=?", (title, now(), task_id))
        return self.task(task_id)

    def delete(self, task_id):
        with self.lock:
            self.task_exists(task_id)
            self._assert_idle(task_id)
            self.sharing.assert_not_building(task_id)
            folder = self.store.root / "documents" / task_id
            if folder.resolve().parent != (self.store.root / "documents").resolve():
                raise ValueError("任务目录无效。")
            if folder.exists():
                shutil.rmtree(folder)
            with self.store.connect() as db:
                db.execute("DELETE FROM tasks WHERE id=?", (task_id,))

    def save_page(self, page_id, boxes, revision):
        if not isinstance(boxes, list) or len(boxes) > 1000:
            raise ValueError("每页最多保存 1000 个标记框。")
        validated = [validate_box(box) for box in boxes]
        if len({b["id"] for b in validated}) != len(validated):
            raise ValueError("同一页面不能包含重复的标记框 ID。")
        with self.lock:
            page = self.page(page_id)
            self._assert_page_idle(page)
            if page["revision"] != revision:
                raise ConflictError("页面已更新，请重新打开页面后再编辑。")
            with self.store.connect() as db:
                for box in validated:
                    existing = db.execute("SELECT page_id FROM boxes WHERE id=?", (box["id"],)).fetchone()
                    if existing and existing["page_id"] != page_id:
                        raise ValueError("标记框 ID 与其他页面冲突。")
                db.execute("DELETE FROM boxes WHERE page_id=?", (page_id,))
                db.executemany(
                    "INSERT INTO boxes VALUES(?,?,?,?)",
                    [
                        (box["id"], page_id, i, json.dumps(box, ensure_ascii=False))
                        for i, box in enumerate(validated)
                    ],
                )
                db.execute("UPDATE pages SET revision=revision+1 WHERE id=?", (page_id,))
                db.execute("UPDATE tasks SET updated_at=? WHERE id=?", (now(), page["task_id"]))
        return self.page(page_id)

    def image(self, page_id, box_id=None, thumbnail=False):
        page = self.page(page_id)
        return self._page_image(page, box_id, thumbnail)

    def crop_preview(self, page_id, geometry):
        box = validate_box({"id": "preview", **geometry})
        return self._page_image(self.page(page_id), geometry=box)

    def _page_image(self, page, box_id=None, thumbnail=False, geometry=None):
        path = self.document_path(page["task_id"]).parent / (page["image_file"] or "manual.pdf")

        def render(**kwargs):
            if page["image_file"]:
                return documents.render_image(path, **kwargs)
            return documents.render(path, page["page_index"], **kwargs)

        box = geometry
        if box_id:
            box = next((b for b in page["boxes"] if b["id"] == box_id), None)
            if not box:
                raise LookupError("标记框不存在。")
        if box is None:
            cache = path.parent / f"page-{page['page_index']}-{'thumb' if thumbnail else 'preview'}.png"
            with documents.PDF_LOCK:
                if cache.exists():
                    return cache.read_bytes()
                data = render(thumbnail=thumbnail)
                cache.write_bytes(data)
                return data
        return render(box=box)

    def _rows(self, task_id):
        return [
            {**box, "page": page["page_index"] + 1, "page_id": page["id"]}
            for page in self.task(task_id)["pages"]
            for box in self.store.boxes(page["id"])
        ]

    def summary(self, task_id):
        groups = {}
        rows = self._rows(task_id)
        for row in rows:
            if row["status"] not in ("recognized", "manual"):
                continue
            key = (row["category"] or "未分类", row["runner"], row["part_number"])
            if key not in groups:
                groups[key] = {
                    "category": key[0],
                    "runner": key[1],
                    "part_number": key[2],
                    "quantity": 0,
                    "pages": set(),
                }
            groups[key]["quantity"] += row["quantity"]
            groups[key]["pages"].add(row["page"])
        result = [{**r, "pages": sorted(r["pages"])} for r in groups.values()]

        def natural(value):
            return [(0, int(p)) if p.isdigit() else (1, p.casefold()) for p in re.split(r"(\d+)", value)]

        result.sort(key=lambda r: (natural(r["category"]), natural(r["runner"]), natural(r["part_number"])))

        def grouped(by_category):
            collected = {}
            for item in result:
                key = (item["category"], item["runner"]) if by_category else (item["runner"],)
                group = collected.setdefault(
                    key,
                    {
                        "category": item["category"] if by_category else "",
                        "runner": item["runner"],
                        "parts": {},
                        "quantity": 0,
                        "pages": set(),
                        "categories": set(),
                    },
                )
                number = item["part_number"]
                group["parts"][number] = group["parts"].get(number, 0) + item["quantity"]
                group["quantity"] += item["quantity"]
                group["pages"].update(item["pages"])
                group["categories"].add(item["category"])
            return [
                {
                    **group,
                    "parts": [
                        {"part_number": number, "quantity": quantity}
                        for number, quantity in sorted(group["parts"].items(), key=lambda p: natural(p[0]))
                    ],
                    "pages": sorted(group["pages"]),
                    "categories": sorted(group["categories"], key=natural),
                }
                for key, group in sorted(
                    collected.items(), key=lambda pair: tuple(natural(value) for value in pair[0])
                )
            ]

        return {
            "items": result,
            "by_category": grouped(True),
            "by_runner": grouped(False),
            "total_quantity": sum(item["quantity"] for item in result),
            "part_kinds": len({(item["runner"], item["part_number"]) for item in result}),
            "rows": rows,
            "unresolved": sum(r["status"] not in ("manual", "recognized") for r in rows),
        }

    def export_excel(self, task_id):
        task, summary = self.task(task_id), self.summary(task_id)
        wb = Workbook()
        ws = wb.active
        ws.title = "取件汇总"
        ws.append([task["title"]])
        ws.append([f"未计入汇总的待处理标记：{summary['unresolved']}；请对照说明书校对数量。"])
        ws.append([])
        ws.append(["部件分类", "板件", "零件号 × 数量", "合计数量", "来源页码"])

        def part_text(item):
            return "、".join(f"{p['part_number']} × {p['quantity']}" for p in item["parts"])

        for item in summary["by_category"]:
            ws.append(
                [
                    item["category"],
                    item["runner"],
                    part_text(item),
                    item["quantity"],
                    ", ".join(map(str, item["pages"])),
                ]
            )
        runners = wb.create_sheet("按板件汇总")
        runners.append([task["title"]])
        runners.append(["跨部件分类合并同一板件的零件；相同编号的数量累加。"])
        runners.append([])
        runners.append(["板件", "零件号 × 数量", "合计数量", "涉及部件分类", "来源页码"])
        for item in summary["by_runner"]:
            runners.append(
                [
                    item["runner"],
                    part_text(item),
                    item["quantity"],
                    "、".join(item["categories"]),
                    ", ".join(map(str, item["pages"])),
                ]
            )
        detail = wb.create_sheet("识别明细")
        detail.append(["页码", "分类", "板件", "零件号", "数量", "状态", "原文", "备注"])
        names = {
            "pending": "待识别",
            "recognized": "已识别",
            "manual": "已校对",
            "review": "待复核",
            "error": "识别失败",
        }
        for row in summary["rows"]:
            detail.append(
                [
                    row["page"],
                    row["category"],
                    row["runner"],
                    row["part_number"],
                    row["quantity"],
                    names[row["status"]],
                    row["raw_text"],
                    row["note"],
                ]
            )
        for sheet, header, widths in [
            (ws, 4, [20, 18, 60, 14, 20]),
            (runners, 4, [18, 60, 14, 28, 20]),
            (detail, 1, [12, 20, 18, 18, 14, 18, 28, 45]),
        ]:
            for row in sheet:
                for cell in row:
                    if isinstance(cell.value, str):
                        # Preserve identifiers and prevent formula interpretation of model/user text.
                        cell.data_type = "s"
                    cell.alignment = Alignment(vertical="center", wrap_text=True)
            for cell in sheet[header]:
                cell.fill = PatternFill("solid", fgColor="285E52")
                cell.font = Font(color="FFFFFF", bold=True)
            for index, width in enumerate(widths, 1):
                sheet.column_dimensions[sheet.cell(header, index).column_letter].width = width
            sheet.freeze_panes = f"A{header + 1}"
            sheet.auto_filter.ref = (
                f"A{header}:{sheet.cell(max(header, sheet.max_row), sheet.max_column).coordinate}"
            )
        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()

    def export_project(self, task_id):
        task = self.task(task_id)
        has_images = task["source_type"] != "pdf"
        manifest = {
            "format": "liner-parts",
            "version": 2 if has_images else 1,
            "title": task["title"],
            "pages": [{"index": p["page_index"], "boxes": self.store.boxes(p["id"])} for p in task["pages"]],
        }
        if has_images:
            for page, source in zip(manifest["pages"], task["pages"]):
                page["image_file"] = source["image_file"]
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            folder = self.document_path(task_id).parent
            for name in sorted({p["image_file"] or "manual.pdf" for p in task["pages"]}):
                archive.write(folder / name, name)
        return out.getvalue()

    def import_project(self, stream):
        try:
            with zipfile.ZipFile(stream) as archive:
                entries = archive.infolist()
                names = {i.filename for i in entries}
                if len(names) != len(entries) or "manifest.json" not in names:
                    raise ValueError("项目包内容无效。")
                if (
                    any(i.file_size > MAX_FILE for i in entries)
                    or sum(i.file_size for i in entries) > MAX_FILE + 10 * 1024 * 1024
                    or archive.getinfo("manifest.json").file_size > 10 * 1024 * 1024
                ):
                    raise ValueError("项目包过大。")
                manifest = json.loads(archive.read("manifest.json"))
                if (
                    not isinstance(manifest, dict)
                    or manifest.get("format") != "liner-parts"
                    or manifest.get("version") not in (1, 2)
                ):
                    raise ValueError("不支持此项目文件版本。")
                pages = manifest["pages"]
                if (
                    not isinstance(pages, list)
                    or not 1 <= len(pages) <= documents.MAX_PAGES
                    or not all(isinstance(p, dict) for p in pages)
                ):
                    raise ValueError("项目页码无效。")
                # Validate all geometry before creating any persistent data.
                normalized = []
                image_names, pdf_count = [], 0
                for index, page in enumerate(pages):
                    if (
                        page["index"] != index
                        or not isinstance(page["boxes"], list)
                        or len(page["boxes"]) > 1000
                    ):
                        raise ValueError("项目页码或标记无效。")
                    normalized.append([validate_box({**b, "id": identifier()}) for b in page["boxes"]])
                    name = page.get("image_file", "") if manifest["version"] == 2 else ""
                    if name:
                        if (
                            not isinstance(name, str)
                            or not re.fullmatch(r"[a-f0-9]{32}\.png", name)
                            or name in image_names
                        ):
                            raise ValueError("项目图片文件名无效。")
                        image_names.append(name)
                    else:
                        if image_names:
                            raise ValueError("项目页面顺序无效。")
                        pdf_count += 1
                expected = {"manifest.json", *image_names}
                if pdf_count:
                    expected.add("manual.pdf")
                if names != expected:
                    raise ValueError("项目包内容与页面不一致。")
                raw = archive.read("manual.pdf") if pdf_count else None
                images = [(io.BytesIO(archive.read(name)), name) for name in image_names]
                title = clean_text(manifest["title"], 120)
        except (zipfile.BadZipFile, KeyError, TypeError, json.JSONDecodeError, RuntimeError):
            raise ValueError("无法打开项目包，请选择本工具导出的 .liner 文件。") from None
        task = None
        try:
            if raw is not None:
                task = self.import_pdf(io.BytesIO(raw), title + ".pdf", title)
                if task["page_count"] != pdf_count:
                    raise ValueError("项目页数与说明书不一致。")
            if images:
                task = self.import_images(images, title, task["id"] if task else None)
            if len(task["pages"]) != len(pages):
                raise ValueError("项目页数与说明书不一致。")
            for page, boxes in zip(task["pages"], normalized):
                self.save_page(page["id"], boxes, 0)
        except Exception:
            if task:
                self.delete(task["id"])
            raise
        return self.task(task["id"])

    def _config(self):
        config = self.settings.snapshot()
        if not config["model"]:
            raise ValueError("请先在接口设置中填写支持图片输入的模型名称。")
        return config

    def test_connection(self):
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (240, 120), "white")
        ImageDraw.Draw(image).text((25, 30), "A(12)", fill="black", font_size=40)
        out = io.BytesIO()
        image.save(out, "PNG")
        client = self.recognizer_factory(self._config())
        try:
            results, _ = client.recognize([("connection-test", out.getvalue())], threading.Event())
            item = results["connection-test"]
            if item["runner"] != "A" or item["part_number"] != "12":
                raise ValueError("接口已响应，但没有正确读出测试图片 A(12)。请确认模型支持图片输入。")
            return {"message": "图片输入与结构化识别测试通过。"}
        finally:
            client.close()

    def models(self):
        client = self.recognizer_factory(self.settings.snapshot())
        try:
            return client.models()
        finally:
            client.close()

    def recognize(self, task_id, page_id=None, box_ids=None, mode="pending"):
        if mode not in ("pending", "all", "review"):
            raise ValueError("识别模式无效。")
        if box_ids is not None and (
            not isinstance(box_ids, list) or not all(isinstance(i, str) for i in box_ids)
        ):
            raise ValueError("标记框选择无效。")
        with self.lock:
            config = self._config()
            pages = self.task(task_id)["pages"]
            if page_id and page_id not in {p["id"] for p in pages}:
                raise ValueError("页面不属于当前任务。")
            busy_pages = self._busy_pages(task_id)
            if page_id in busy_pages:
                raise ConflictError("本页已在识别队列中，请勿重复提交。其他页面可以继续提交。")
            selected = []
            for page in pages:
                if page_id and page["id"] != page_id:
                    continue
                if page["id"] in busy_pages:
                    continue
                for box in self.store.boxes(page["id"]):
                    if box_ids is not None and box["id"] not in box_ids:
                        continue
                    if mode == "pending" and box["status"] in ("recognized", "manual"):
                        continue
                    if mode == "review" and box["status"] not in ("review", "error"):
                        continue
                    selected.append((page, box))
            if not selected:
                raise ValueError("没有需要识别的标记框，相关页面可能已完成或已在识别队列中。")
            job_id, stamp = identifier(), now()
            with self.store.connect() as db:
                db.execute(
                    "INSERT INTO jobs(id,task_id,status,total,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (job_id, task_id, "queued", len(selected), stamp, stamp),
                )
                db.executemany(
                    "INSERT INTO job_pages(job_id,page_id) VALUES(?,?)",
                    [(job_id, page_id) for page_id in {page["id"] for page, _box in selected}],
                )
            event = threading.Event()
            self.cancellations[job_id] = event
            self.executor.submit(self._run_job, job_id, task_id, selected, config, event)
            return self.job(job_id)

    def _job_pages(self, jobs):
        if not jobs:
            return jobs
        by_id = {job["id"]: job for job in jobs}
        for job in jobs:
            job["page_ids"], job["page_numbers"] = [], []
        # All jobs here belong to the same task; fetch the relations once.
        for row in self.store.all(
            "SELECT jp.job_id,p.id,p.page_index FROM job_pages jp JOIN pages p ON p.id=jp.page_id "
            "WHERE p.task_id=? ORDER BY p.page_index",
            (jobs[0]["task_id"],),
        ):
            if row["job_id"] in by_id:
                by_id[row["job_id"]]["page_ids"].append(row["id"])
                by_id[row["job_id"]]["page_numbers"].append(row["page_index"] + 1)
        return jobs

    def jobs(self, task_id):
        return self._job_pages(
            self.store.all(
                "SELECT * FROM jobs WHERE task_id=? AND (status IN ('queued','running','cancelling') "
                "OR id IN (SELECT id FROM jobs WHERE task_id=? ORDER BY created_at DESC LIMIT 5)) "
                "ORDER BY created_at",
                (task_id, task_id),
            )
        )

    def recognition_state(self, task_id, page_id=None):
        # Return progress and page revision from one snapshot, so the UI never unlocks stale data.
        with self.lock:
            self.task_exists(task_id)
            page = self.page(page_id) if page_id else None
            if page and page["task_id"] != task_id:
                raise ValueError("页面不属于当前任务。")
            return {"jobs": self.jobs(task_id), "page": page, "workers": RECOGNITION_WORKERS}

    def job(self, job_id):
        job = self.store.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job:
            raise LookupError("识别任务不存在。")
        return self._job_pages([job])[0]

    def cancel(self, job_id):
        with self.lock:
            job = self.job(job_id)
            if job["status"] in ACTIVE:
                self.cancellations[job_id].set()
                if job["status"] == "queued":
                    self._update_job(job_id, status="cancelled", message="已取消排队，未发送识别请求。")
                else:
                    self._update_job(
                        job_id,
                        status="cancelling",
                        message="正在停止；当前请求结束后取消，已保存的结果保留。",
                    )
        return self.job(job_id)

    def _update_job(self, job_id, **values):
        values["updated_at"] = now()
        with self.store.connect() as db:
            db.execute(
                "UPDATE jobs SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?",
                (*values.values(), job_id),
            )

    def _run_job(self, job_id, task_id, selected, config, cancel):
        done = errors = 0
        client = None
        try:
            with self.lock:
                if cancel.is_set():
                    self._update_job(job_id, status="cancelled", message="已取消，未处理项可以继续识别。")
                    return
                self._update_job(job_id, status="running", message="正在按序号拼接截图并识别…")
            client = self.recognizer_factory(config)
            for offset in range(0, len(selected), BATCH_SIZE):
                if cancel.is_set():
                    break
                batch = selected[offset : offset + BATCH_SIZE]
                try:
                    crops = [(box["id"], self.image(page["id"], box["id"])) for page, box in batch]
                    results, _usage = client.recognize(crops, cancel)
                    error = ""
                except ValueError as exc:
                    results, error = {}, str(exc)
                if cancel.is_set():
                    break
                with self.lock, self.store.connect() as db:
                    if cancel.is_set():
                        break
                    for page, box in batch:
                        if error:
                            box.update(status="error", note=error)
                            errors += 1
                        else:
                            box.update(results[box["id"]])
                        box = validate_box(box)
                        db.execute(
                            "UPDATE boxes SET data=? WHERE id=? AND page_id=?",
                            (json.dumps(box, ensure_ascii=False), box["id"], page["id"]),
                        )
                    for page_id in {p["id"] for p, _ in batch}:
                        db.execute("UPDATE pages SET revision=revision+1 WHERE id=?", (page_id,))
                    db.execute("UPDATE tasks SET updated_at=? WHERE id=?", (now(), task_id))
                done += len(batch)
                self._update_job(
                    job_id,
                    done=done,
                    errors=errors,
                    message=error or f"已处理 {done} / {len(selected)} 个标记",
                )
            status = (
                "cancelled"
                if cancel.is_set()
                else "failed"
                if errors == len(selected)
                else "partial"
                if errors
                else "completed"
            )
            message = (
                "已取消，已完成的结果已保存。" if cancel.is_set() else "识别完成，请检查结果并校对用量。"
            )
            if errors and not cancel.is_set():
                message = f"{errors} 个标记识别失败，可重试未完成项。"
            self._update_job(job_id, status=status, done=done, errors=errors, message=message)
        except Exception:
            self._update_job(
                job_id,
                status="failed",
                done=done,
                errors=errors,
                message="识别中断，已完成结果已保存，请重试未完成项。",
            )
        finally:
            try:
                if client:
                    client.close()
            finally:
                with self.lock:
                    self.cancellations.pop(job_id, None)
