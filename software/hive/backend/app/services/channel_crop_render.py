"""Derive the channel-cropped view of a sample's full frame from the machine's
per-sample channel geometry. The sorter uploads the FULL (unmasked) frame plus
the region polygon; Hive reconstructs the masked crop here so we can train on
full frames while distilling the teacher on the masked channel region — the mask
is never baked into the stored pixels.
"""

from __future__ import annotations

import math
from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw


def _scaled_polygon(geom: Any, width: int, height: int) -> list[tuple[float, float]] | None:
    xs = list(geom.polygon_x or [])
    ys = list(geom.polygon_y or [])
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    # The polygon was drawn against frame_width/height; rescale to the actual
    # uploaded frame so it lands on the right pixels (same transform the sorter's
    # perception layer applies when the camera streams a different resolution).
    frame_w = geom.frame_width or width
    frame_h = geom.frame_height or height
    scale_x = (width / frame_w) if frame_w else 1.0
    scale_y = (height / frame_h) if frame_h else 1.0
    return [(float(x) * scale_x, float(y) * scale_y) for x, y in zip(xs, ys)]


def render_channel_crop(
    full_frame_bytes: bytes,
    geom: Any,
    *,
    mask_outside: bool = True,
    jpeg_quality: int = 90,
) -> bytes | None:
    """Return JPEG bytes of the full frame cropped to the channel region's
    bounding box. With mask_outside the pixels outside the polygon are filled
    white (the distillation view); without it the raw crop rectangle is kept.
    Returns None when the geometry can't produce a valid region.
    """
    try:
        img = Image.open(BytesIO(full_frame_bytes)).convert("RGB")
    except Exception:
        return None
    width, height = img.size

    points = _scaled_polygon(geom, width, height)
    if points is None:
        return None

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0 = max(0, int(math.floor(min(xs))))
    y0 = max(0, int(math.floor(min(ys))))
    x1 = min(width, int(math.ceil(max(xs))))
    y1 = min(height, int(math.ceil(max(ys))))
    if x1 <= x0 or y1 <= y0:
        return None

    if mask_outside:
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).polygon(points, fill=255)
        white = Image.new("RGB", (width, height), (255, 255, 255))
        img = Image.composite(img, white, mask)

    crop = img.crop((x0, y0, x1, y1))
    out = BytesIO()
    crop.save(out, format="JPEG", quality=jpeg_quality)
    return out.getvalue()
