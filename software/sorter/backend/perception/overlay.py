"""Perception's zones, as pictures and as shapes.

The perception-debug page and recordings draw the zones into pixels here. The
live feed does not: it sends the zones as shapes (``feedZoneShapes``) and the
page draws them, with the boxes, over each frame.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np


ZONE_DROP_COLOR = (255, 128, 0)
ZONE_EXIT_COLOR = (0, 64, 255)
ZONE_PRECISE_COLOR = (255, 0, 255)
ON_CHANNEL_COLOR = (0, 255, 0)
REJECTED_COLOR = (0, 165, 255)
CHANNEL_OUTLINE_COLOR = (255, 255, 0)
# A box we synthesised by MERGING the detector's over-segmented output (several
# overlapping/adjacent boxes for one physical piece) — what the machine actually
# acts on. Drawn distinctly + thicker over the green originals so it's clear what
# the model drew vs. what we treat as one piece.
MERGED_COLOR = (255, 0, 128)

# Secondary (foreign) zones: same hue family as the matching primary zone type
# but drawn as a thin desaturated outline (no fill) so they read as "observed,
# not acted on." A detection that lands in any secondary zone is boxed in cyan.
SECONDARY_ZONE_COLORS = {
    "drop": (200, 160, 120),
    "exit": (120, 140, 220),
    "precise": (200, 120, 200),
}
SECONDARY_ZONE_DEFAULT_COLOR = (180, 180, 180)
SECONDARY_DETECTION_COLOR = (255, 255, 0)
# A piece just past a feeder channel's exit: seen, no longer on the channel.
EXIT_MARGIN_COLOR = (160, 160, 160)

_ZONE_OVERLAY_CACHE: dict[tuple, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
# The zone overlay is static per channel config, so we cache the full-res build
# AND its downscaled copies: resizing the cached arrays to a picture's size once
# is far cheaper than compositing the overlay on a 4K frame each time.
_SCALED_ZONE_CACHE: dict[tuple, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
_SCALED_MASK_CACHE: dict[tuple, np.ndarray] = {}


def _zoneKey(channel: Any) -> tuple:
    exit_only_sections = frozenset(channel.exit_sections - channel.precise_sections)
    return (
        int(channel.channel_id),
        tuple(int(v) for v in channel.mask.shape[:2]),
        round(float(channel.center[0]), 3),
        round(float(channel.center[1]), 3),
        round(float(channel.radius1_angle_image), 3),
        tuple(sorted(int(v) for v in channel.drop_sections)),
        tuple(sorted(int(v) for v in exit_only_sections)),
        tuple(sorted(int(v) for v in channel.precise_sections)),
    )


def _scaledZoneArrays(
    channel: Any, target_h: int, target_w: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    base = channelZoneOverlay(channel)
    if base is None:
        return None
    if base[0].shape[0] == target_h and base[0].shape[1] == target_w:
        return base
    key = (_zoneKey(channel), target_h, target_w)
    cached = _SCALED_ZONE_CACHE.get(key)
    if cached is not None:
        return cached
    res = tuple(
        cv2.resize(a, (target_w, target_h), interpolation=cv2.INTER_NEAREST) for a in base
    )
    _SCALED_ZONE_CACHE[key] = res  # type: ignore[assignment]
    return res  # type: ignore[return-value]


def _scaledMask(mask: np.ndarray, target_h: int, target_w: int, cache_key: tuple) -> np.ndarray:
    if mask.shape[0] == target_h and mask.shape[1] == target_w:
        return mask
    key = (cache_key, target_h, target_w)
    cached = _SCALED_MASK_CACHE.get(key)
    if cached is not None:
        return cached
    res = cv2.resize(mask, (target_w, target_h), interpolation=cv2.INTER_NEAREST)
    _SCALED_MASK_CACHE[key] = res
    return res


def channelZoneOverlay(
    channel: Any,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    if channel is None:
        return None
    exit_only_sections = frozenset(channel.exit_sections - channel.precise_sections)
    key = _zoneKey(channel)
    cached = _ZONE_OVERLAY_CACHE.get(key)
    if cached is not None:
        return cached

    mask = np.asarray(channel.mask)
    if mask.ndim != 2 or mask.size == 0:
        return None
    on_channel = mask > 0
    ys, xs = np.nonzero(on_channel)
    h, w = mask.shape[:2]
    overlay = np.zeros((h, w, 3), dtype=np.uint8)
    drop_mask = np.zeros((h, w), dtype=np.uint8)
    exit_mask = np.zeros((h, w), dtype=np.uint8)
    precise_mask = np.zeros((h, w), dtype=np.uint8)
    if xs.size == 0:
        result = (overlay, drop_mask, exit_mask, precise_mask)
        _ZONE_OVERLAY_CACHE[key] = result
        return result

    rel = (
        np.degrees(
            np.arctan2(
                ys.astype(np.float64) - float(channel.center[1]),
                xs.astype(np.float64) - float(channel.center[0]),
            )
        )
        - float(channel.radius1_angle_image)
    ) % 360.0
    sections = np.floor(rel).astype(np.int32) % 360

    precise_sections = set(int(v) for v in channel.precise_sections)
    exit_only = set(int(v) for v in exit_only_sections)
    drop_sections = set(int(v) for v in channel.drop_sections)

    if precise_sections:
        precise_hit = np.isin(sections, list(precise_sections))
        precise_mask[ys[precise_hit], xs[precise_hit]] = 255
        overlay[ys[precise_hit], xs[precise_hit]] = ZONE_PRECISE_COLOR
    if exit_only:
        exit_hit = np.isin(sections, list(exit_only))
        exit_mask[ys[exit_hit], xs[exit_hit]] = 255
        overlay[ys[exit_hit], xs[exit_hit]] = ZONE_EXIT_COLOR
    if drop_sections:
        drop_hit = np.isin(sections, list(drop_sections))
        drop_mask[ys[drop_hit], xs[drop_hit]] = 255
        overlay[ys[drop_hit], xs[drop_hit]] = ZONE_DROP_COLOR

    result = (overlay, drop_mask, exit_mask, precise_mask)
    _ZONE_OVERLAY_CACHE[key] = result
    return result


def drawChannelZones(img: np.ndarray, channel: Any, thick: int) -> None:
    # Render to whatever resolution ``img`` is. The static zone arrays are built
    # full-res once and cached, then resized to match (also cached).
    th, tw = img.shape[:2]
    zone_overlay = _scaledZoneArrays(channel, th, tw)
    if zone_overlay is not None:
        # Zones are shown as a low-opacity colour fill only — no outlines.
        overlay_img = zone_overlay[0]
        zone_pixels = np.any(overlay_img != 0, axis=2)
        if zone_pixels.any():
            blended = img.copy()
            blended[zone_pixels] = overlay_img[zone_pixels]
            img[:] = cv2.addWeighted(blended, 0.15, img, 0.85, 0)
    if channel is not None:
        # Thin outermost channel outline.
        outline = _scaledMask(channel.mask, th, tw, (_zoneKey(channel), "outline"))
        contours, _ = cv2.findContours(
            outline, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        cv2.drawContours(img, contours, -1, CHANNEL_OUTLINE_COLOR, thick, cv2.LINE_AA)
        # The exit margin: where a piece that has left the channel is still seen.
        margin_mask = getattr(channel, "exit_margin_mask", None)
        if margin_mask is not None:
            margin = _scaledMask(margin_mask, th, tw, (_zoneKey(channel), "margin"))
            contours, _ = cv2.findContours(margin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(img, contours, -1, EXIT_MARGIN_COLOR, thick, cv2.LINE_AA)


def _rings(mask: np.ndarray, mode: int, width: int, height: int) -> list[list[float]]:
    """The contours of ``mask`` as flat ``[x0, y0, x1, y1, ...]`` lists in 0..1
    frame coordinates, simplified to within a pixel at this size."""
    contours, _ = cv2.findContours(mask, mode, cv2.CHAIN_APPROX_SIMPLE)
    rings = []
    for contour in contours:
        if len(contour) < 3:
            continue
        points = cv2.approxPolyDP(contour, 0.75, True).reshape(-1, 2).astype(np.float64)
        if len(points) < 3:
            continue
        points[:, 0] = (points[:, 0] + 0.5) / width
        points[:, 1] = (points[:, 1] + 0.5) / height
        rings.append([round(float(v), 4) for v in points.reshape(-1)])
    return rings


def feedZoneShapes(channel: Any, width: int) -> dict[str, Any] | None:
    """The live feed's zones as shapes: each zone's area (``drop``, ``exit``,
    ``precise``, filled even-odd so a hole stays a hole), the channel's
    ``outline``, the exit ``margin`` and the ``secondary`` (foreign) zones'
    outlines. Traced at ``width`` pixels across, the size the feed is sent at;
    the same sections as ``channelZoneOverlay``, without its full-resolution
    pass."""
    mask = np.asarray(channel.mask)
    if mask.ndim != 2 or mask.size == 0:
        return None
    src_h, src_w = mask.shape[:2]
    scale = min(1.0, width / float(src_w)) if width > 0 else 1.0
    w, h = max(1, int(round(src_w * scale))), max(1, int(round(src_h * scale)))

    def small(m: np.ndarray) -> np.ndarray:
        m = (np.asarray(m) > 0).astype(np.uint8) * 255
        return cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST) if (w, h) != (src_w, src_h) else m

    on_channel = small(mask)
    ys, xs = np.nonzero(on_channel)
    rel = (
        np.degrees(
            np.arctan2(
                ys.astype(np.float64) / scale - float(channel.center[1]),
                xs.astype(np.float64) / scale - float(channel.center[0]),
            )
        )
        - float(channel.radius1_angle_image)
    ) % 360.0
    sections = np.floor(rel).astype(np.int32) % 360

    # Where zones overlap, the drop zone shows, then the exit zone, then the
    # precise zone: each pixel belongs to one, as in channelZoneOverlay.
    taken = np.zeros(len(xs), dtype=bool)
    areas: dict[str, list[list[float]]] = {}
    for name, picked in (
        ("drop", channel.drop_sections),
        ("exit", channel.exit_sections - channel.precise_sections),
        ("precise", channel.precise_sections),
    ):
        hit = np.isin(sections, [int(v) for v in picked]) & ~taken
        taken |= hit
        area = np.zeros((h, w), dtype=np.uint8)
        area[ys[hit], xs[hit]] = 255
        areas[name] = _rings(area, cv2.RETR_CCOMP, w, h)

    margin_mask = getattr(channel, "exit_margin_mask", None)
    secondary = []
    for zone in getattr(channel, "secondary_zones", None) or ():
        zone_mask = np.asarray(zone.mask)
        if zone_mask.ndim != 2 or zone_mask.size == 0:
            continue
        secondary.append(
            {"type": str(zone.zone_type), "rings": _rings(small(zone_mask), cv2.RETR_EXTERNAL, w, h)}
        )
    return {
        **areas,
        "outline": _rings(on_channel, cv2.RETR_EXTERNAL, w, h),
        "margin": _rings(small(margin_mask), cv2.RETR_EXTERNAL, w, h) if margin_mask is not None else [],
        "secondary": secondary,
    }
