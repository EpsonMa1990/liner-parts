from __future__ import annotations

import io
import threading
from contextlib import closing
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

# PDFium is process-global and must never be called concurrently, even for different documents.
PDF_LOCK = threading.RLock()
MAX_PAGES = 500
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def normalize_image(source: Path, destination: Path):
    """Store an oriented, opaque PNG without recompressing small text as JPEG."""
    try:
        with Image.open(source) as original:
            if original.format not in {"PNG", "JPEG", "WEBP", "BMP"}:
                raise ValueError("图片仅支持 PNG、JPG、JPEG、WebP 和 BMP。")
            if getattr(original, "n_frames", 1) != 1:
                raise ValueError("请选择静态图片，每张图片对应一页说明书。")
            if original.width * original.height > 40_000_000:
                raise ValueError("单张图片超过 4000 万像素，请缩小后导入。")
            with ImageOps.exif_transpose(original) as oriented, oriented.convert("RGBA") as rgba:
                with Image.new("RGB", rgba.size, "white") as image:
                    image.paste(rgba, mask=rgba.getchannel("A"))
                    image.save(destination, "PNG")
                    return image.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("无法读取图片，请确认文件完整且为支持的图片格式。") from None


def render_image(path: Path, box=None, thumbnail=False):
    with Image.open(path) as source:
        if box:
            left, top = int(box["x"] * source.width), int(box["y"] * source.height)
            right = min(source.width, max(left + 1, round((box["x"] + box["width"]) * source.width)))
            bottom = min(source.height, max(top + 1, round((box["y"] + box["height"]) * source.height)))
            image = source.crop((left, top, right, bottom))
        else:
            image = source.copy()
        with image:
            limit = 2400 if box else 220 if thumbnail else 1500
            image.thumbnail((limit, limit), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            image.save(out, "PNG")
            return out.getvalue()


def inspect_pdf(path: Path):
    with PDF_LOCK:
        try:
            with closing(pdfium.PdfDocument(path)) as doc:
                if not 1 <= len(doc) <= MAX_PAGES:
                    raise ValueError(f"说明书需要包含 1–{MAX_PAGES} 页。")
                sizes = []
                for index in range(len(doc)):
                    with closing(doc[index]) as page:
                        width, height = page.get_size()
                        if width <= 0 or height <= 0:
                            raise ValueError("PDF 包含无效页面。")
                        sizes.append((width, height))
                return sizes
        except pdfium.PdfiumError:
            raise ValueError("无法打开 PDF，请确认文件完整且未加密。") from None


def render(path: Path, index: int, box=None, thumbnail=False):
    with PDF_LOCK:
        with closing(pdfium.PdfDocument(path)) as doc, closing(doc[index]) as page:
            width, height = page.get_size()
            if box:
                x, y, w, h = (box[k] for k in ("x", "y", "width", "height"))
                # Normalized top-left coordinates -> PDFium crop amounts (left, bottom, right, top).
                crop = (x * width, max(0, 1 - y - h) * height, max(0, 1 - x - w) * width, y * height)
                scale = min(4.0, 2400 / max(w * width, h * height))
            else:
                crop = (0, 0, 0, 0)
                scale = min(2.0, (220 if thumbnail else 1500) / max(width, height))
            bitmap = page.render(scale=scale, crop=crop)
            try:
                img = bitmap.to_pil().convert("RGB")
                output = io.BytesIO()
                img.save(output, "PNG")
                img.close()
                return output.getvalue()
            finally:
                bitmap.close()


def demo_pdf():
    """An original, copyright-free manual page for learning the workflow."""
    img = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(img)
    try:
        heading = ImageFont.truetype("arial.ttf", 52)
        body = ImageFont.truetype("arial.ttf", 30)
        small = ImageFont.truetype("arial.ttf", 22)
    except OSError:
        heading = ImageFont.load_default(size=52)
        body = ImageFont.load_default(size=30)
        small = ImageFont.load_default(size=22)
    ink, muted, accent = "#223644", "#657985", "#307565"
    draw.text((95, 85), "LINER / PRACTICE MANUAL", font=heading, fill=ink)
    draw.text((95, 165), "Original sample - no real model kit", font=small, fill=muted)
    draw.line((95, 230, 1145, 230), fill=ink, width=3)
    for index, (runner, number) in enumerate([("A", "12"), ("A1", "03"), ("B", "7"), ("PC", "2")]):
        col, row = index % 2, index // 2
        left, top = 95 + col * 560, 305 + row * 560
        draw.text((left, top), f"STEP {index + 1:02d}", font=body, fill=accent)
        draw.rounded_rectangle((left + 40, top + 90, left + 270, top + 260), radius=20, outline=ink, width=5)
        draw.rectangle((left + 100, top + 140, left + 205, top + 210), outline=muted, width=3)
        draw.line((left + 270, top + 160, left + 330, top + 100), fill=muted, width=3)
        draw.text((left + 220, top + 45), f"{runner}({number})", font=body, fill=ink)
        draw.ellipse((left + 330, top + 170, left + 400, top + 240), outline=ink, width=4)
        draw.text((left + 45, top + 330), "Frame the part label above.", font=small, fill=muted)
    draw.line((95, 1510, 1145, 1510), fill=ink, width=2)
    draw.text((95, 1545), "Select a label > Recognize > Review > Export", font=body, fill=accent)
    draw.text((95, 1630), "LINER PARTS   /   01", font=small, fill=muted)
    output = io.BytesIO()
    img.save(output, "PDF", resolution=150)
    return output.getvalue()
