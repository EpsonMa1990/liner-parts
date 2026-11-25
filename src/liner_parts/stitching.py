"""Build one ordered, numbered image for each recognition request."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

BATCH_SIZE = 10


def stitch_crops(crops):
    """Keep selection order; numbering lives outside the original crop."""
    if not 1 <= len(crops) <= BATCH_SIZE:
        raise ValueError("每批需要 1 到 10 个截图。")
    images = []
    try:
        for _box_id, data in crops:
            with Image.open(io.BytesIO(data)) as source:
                # Bound large accidental selections without stretching small labels.
                source.thumbnail((1600, 1200), Image.Resampling.LANCZOS)
                rgba = source.convert("RGBA")
                image = Image.new("RGB", rgba.size, "white")
                image.paste(rgba, mask=rgba.getchannel("A"))
                rgba.close()
                images.append(image)
        gutter, padding = 64, 12
        width = max(image.width for image in images) + gutter + padding * 2
        height = sum(max(40, image.height) + padding * 2 for image in images)
        with Image.new("RGB", (width, height), "white") as canvas:
            draw = ImageDraw.Draw(canvas)
            font = ImageFont.load_default(size=24)
            y = 0
            for sequence, image in enumerate(images, 1):
                row_height = max(40, image.height) + padding * 2
                draw.rectangle((0, y, gutter - 1, y + row_height - 1), fill="#edf1f4")
                draw.text((12, y + padding), f"{sequence:02}", fill="#263442", font=font)
                canvas.paste(image, (gutter + padding, y + padding))
                y += row_height
                if y < height:
                    draw.line((0, y - 1, width - 1, y - 1), fill="#b9c3cc", width=2)
            out = io.BytesIO()
            canvas.save(out, format="PNG")
            return out.getvalue()
    except (UnidentifiedImageError, OSError):
        raise ValueError("截图无法读取，请重新框选后重试。") from None
    finally:
        for image in images:
            image.close()
