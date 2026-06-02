"""Rendering for perception detections.

Perception owns the drawing of its own results so the live camera feed and
the perception-debug page share one renderer fed by ONE inference. The frame
handed in here is the exact frame the model inferred against (from
``InferenceWorker.latest_debug``), so boxes are glued to their own pixels —
no last-detection-on-latest-frame drift.
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

_ZONE_OVERLAY_CACHE: dict[tuple, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}


def channelZoneOverlay(
    channel: Any,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    if channel is None:
        return None
    exit_only_sections = frozenset(channel.exit_sections - channel.precise_sections)
    key = (
        int(channel.channel_id),
        tuple(int(v) for v in channel.mask.shape[:2]),
        round(float(channel.center[0]), 3),
        round(float(channel.center[1]), 3),
        round(float(channel.radius1_angle_image), 3),
        tuple(sorted(int(v) for v in channel.drop_sections)),
        tuple(sorted(int(v) for v in exit_only_sections)),
        tuple(sorted(int(v) for v in channel.precise_sections)),
    )
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
    zone_overlay = channelZoneOverlay(channel)
    if zone_overlay is not None:
        overlay_img, drop_mask, exit_mask, precise_mask = zone_overlay
        zone_pixels = np.any(overlay_img != 0, axis=2)
        blended = img.copy()
        blended[zone_pixels] = overlay_img[zone_pixels]
        img[:] = cv2.addWeighted(blended, 0.22, img, 0.78, 0)
        for zone_mask, color in (
            (drop_mask, ZONE_DROP_COLOR),
            (exit_mask, ZONE_EXIT_COLOR),
            (precise_mask, ZONE_PRECISE_COLOR),
        ):
            contours, _ = cv2.findContours(
                zone_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            if contours:
                cv2.drawContours(img, contours, -1, color, max(1, thick - 1))
    if channel is not None:
        contours, _ = cv2.findContours(
            channel.mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        cv2.drawContours(img, contours, -1, CHANNEL_OUTLINE_COLOR, thick)


def drawDetectionBoxes(
    img: np.ndarray, bboxes: list, color: tuple[int, int, int], scale: float, thick: int
) -> None:
    for b in bboxes:
        x1, y1, x2, y2 = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
        cv2.rectangle(img, (x1, y1), (x2, y2), color, thick)
        cv2.circle(
            img, ((x1 + x2) // 2, (y1 + y2) // 2), max(4, int(5 * scale)), color, -1
        )


def drawSecondaryZones(img: np.ndarray, channel: Any, thick: int) -> None:
    """Outline each foreign (secondary) zone the camera observes. Outline only —
    no fill, no text label — so it's visually distinct from the channel's own
    acted-on zones without cluttering the operating feed."""
    zones = getattr(channel, "secondary_zones", None)
    if not zones:
        return
    line_thick = max(1, thick - 1)
    for zone in zones:
        color = SECONDARY_ZONE_COLORS.get(zone.zone_type, SECONDARY_ZONE_DEFAULT_COLOR)
        mask = np.asarray(zone.mask)
        if mask.ndim != 2 or mask.size == 0:
            continue
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            continue
        # Outline only on the video stream — no text label (the zone identity is
        # shown in the editor UI, not on the operating feed).
        cv2.drawContours(img, contours, -1, color, line_thick)


def renderFeedOverlay(
    frame_bgr: np.ndarray, channel: Any, on_bboxes: list, detections: list | None = None
) -> np.ndarray:
    """The clean operating-feed look: zone outlines plus the green on-channel
    boxes the machine acts on. No spec panel, no rejected (orange) boxes — that
    diagnostic detail stays on the perception-debug page.

    ``detections`` (tagged ``Detection`` objects) is optional; when present, any
    detection that fell in a secondary zone is boxed in cyan to show "seen but
    not acted on." Primary on-channel boxes stay green."""
    img = frame_bgr.copy()
    w = img.shape[1]
    s = max(1.0, w / 1280.0)
    thick = max(2, int(round(2 * s)))
    drawChannelZones(img, channel, thick)
    drawSecondaryZones(img, channel, thick)
    if detections:
        secondary_hits = [
            d.bbox for d in detections if not d.in_primary and d.secondary_zone_ids
        ]
        drawDetectionBoxes(img, secondary_hits, SECONDARY_DETECTION_COLOR, s, thick)
    drawDetectionBoxes(img, on_bboxes, ON_CHANNEL_COLOR, s, thick)
    return img
