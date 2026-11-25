import io

import pytest
from PIL import Image

from liner_parts.stitching import stitch_crops


def crop(size, color, mode="RGB"):
    with Image.new(mode, size, color) as image:
        out = io.BytesIO()
        image.save(out, "PNG")
        return out.getvalue()


def test_stitch_preserves_top_to_bottom_order_and_unequal_crop_shapes():
    colors = [(220, 20, 30), (10, 200, 60), (20, 60, 230)]
    sizes = [(200, 80), (120, 160), (180, 100)]
    crops = [(str(i), crop(size, color)) for i, (size, color) in enumerate(zip(sizes, colors))]
    with Image.open(io.BytesIO(stitch_crops(crops))) as image:
        # Inspect actual colored pixels, independently of the layout constants.
        bounds = []
        for color, size in zip(colors, sizes):
            points = [
                (x, y)
                for y in range(image.height)
                for x in range(image.width)
                if image.getpixel((x, y)) == color
            ]
            xs, ys = zip(*points)
            assert max(xs) - min(xs) + 1 == size[0]
            assert max(ys) - min(ys) + 1 == size[1]
            assert len(points) == size[0] * size[1]
            bounds.append((min(ys), max(ys)))
        assert bounds[0][1] < bounds[1][0] < bounds[1][1] < bounds[2][0]


def test_stitch_bounds_large_images_and_flattens_transparency():
    crops = [(str(i), crop((2000, 1800), (0, 0, 0, 0), "RGBA")) for i in range(10)]
    with Image.open(io.BytesIO(stitch_crops(crops))) as image:
        assert image.width < 1700 and image.height < 12500
        assert image.mode == "RGB"
        assert image.getpixel((image.width - 30, 30)) == (255, 255, 255)


@pytest.mark.parametrize("count", [0, 11])
def test_stitch_rejects_invalid_batch_size(count):
    with pytest.raises(ValueError, match="1 到 10"):
        stitch_crops([("a", b"invalid")] * count)
