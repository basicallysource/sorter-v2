"""Traditional pixel-average color guess for a synced piece.

Independent of any external model: it averages the actual crop pixels the machine
already stored and matches that to the nearest BrickLink catalog color. Nothing is
persisted — the guess is recomputed on demand (cheap, and cached per crop).

Algorithm ("pixel average"): for up to N crops of a piece (preferring the ones the
machine marked `used`), take the mean RGB of each crop's central region (trims the
channel background), average those, then pick the nearest BrickLink color by CIE-Lab
(deltaE76).
"""

from __future__ import annotations

import io
from functools import lru_cache
from typing import Any

import numpy as np
from PIL import Image

from app.services.profile_catalog import get_profile_catalog_service
from app.services.storage_backend import get_backend

METHOD = "pixel_average"
MAX_SAMPLES = 5
CENTER_FRACTION = 0.6  # keep the middle 60% box to de-weight background
THUMB = 48


def _srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """rgb: (...,3) in 0-255 -> Lab (...,3). Vectorized (D65)."""
    c = rgb.astype(np.float64) / 255.0
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = lin[..., 0], lin[..., 1], lin[..., 2]
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883
    xyz = np.stack([x, y, z], axis=-1)
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    fx, fy, fz = f[..., 0], f[..., 1], f[..., 2]
    return np.stack([116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)], axis=-1)


@lru_cache(maxsize=1)
def _palette() -> tuple[np.ndarray, tuple[dict[str, Any], ...]]:
    colors = get_profile_catalog_service().list_bricklink_colors()
    rgbs = []
    meta = []
    for c in colors:
        # Keep non-answers out of the auto-match (they still exist in the full
        # palette for manual selection): id<=0 is "(Not Applicable)"/[Unknown],
        # and Modulex ("Mx ...") is a separate non-Lego brick system.
        if not isinstance(c.get("id"), int) or c["id"] <= 0:
            continue
        if str(c.get("name", "")).startswith("Mx "):
            continue
        hex_rgb = c.get("rgb")
        if not isinstance(hex_rgb, str) or len(hex_rgb.replace("#", "")) < 6:
            continue
        h = hex_rgb.replace("#", "")
        try:
            rgbs.append([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)])
        except ValueError:
            continue
        meta.append(c)
    if not rgbs:
        return np.empty((0, 3)), tuple()
    return _srgb_to_lab(np.array(rgbs, dtype=np.float64)), tuple(meta)


def _nearest_color(avg_rgb: tuple[float, float, float]) -> dict[str, Any] | None:
    labs, meta = _palette()
    if len(meta) == 0:
        return None
    target = _srgb_to_lab(np.array(avg_rgb, dtype=np.float64))
    idx = int(np.argmin(np.linalg.norm(labs - target, axis=1)))
    c = meta[idx]
    return {"color_id": c["id"], "color_name": c["name"], "match_rgb": c.get("rgb")}


@lru_cache(maxsize=8192)
def _crop_average(image_key: str) -> tuple[float, float, float] | None:
    try:
        data = get_backend().read_bytes(image_key)
        with Image.open(io.BytesIO(data)) as im:
            im = im.convert("RGB")
            w, h = im.size
            bx = int(w * (1 - CENTER_FRACTION) / 2)
            by = int(h * (1 - CENTER_FRACTION) / 2)
            if w - 2 * bx >= 2 and h - 2 * by >= 2:
                im = im.crop((bx, by, w - bx, h - by))
            im.thumbnail((THUMB, THUMB))
            arr = np.asarray(im, dtype=np.float64).reshape(-1, 3)
    except Exception:
        return None
    r, g, b = arr.mean(axis=0)
    return (float(r), float(g), float(b))


def guess_piece_color(images: list) -> dict[str, Any] | None:
    """images: MachinePieceImage rows for one piece. Returns the pixel-average
    guess, or None if no crop was readable."""
    with_key = [im for im in images if im.image_key]
    used = [im for im in with_key if im.used]
    chosen = (used or with_key)[:MAX_SAMPLES]
    samples = [avg for im in chosen if (avg := _crop_average(im.image_key)) is not None]
    if not samples:
        return None
    r = sum(s[0] for s in samples) / len(samples)
    g = sum(s[1] for s in samples) / len(samples)
    b = sum(s[2] for s in samples) / len(samples)
    nearest = _nearest_color((r, g, b))
    if nearest is None:
        return None
    return {
        "method": METHOD,
        "rgb": "%02X%02X%02X" % (round(r), round(g), round(b)),
        "sample_count": len(samples),
        **nearest,
    }
