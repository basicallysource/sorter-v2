"""Overlay that renders persistent track IDs + velocity vectors.

Reads the latest track list from a callable so the overlay stays decoupled
from the VisionManager — inject via
``TrackOverlay(lambda: vm.getFeederTracks(role))``.
"""

from __future__ import annotations

from typing import Callable

import cv2
import numpy as np


# BGR to match OpenCV.
COLOR_ACTIVE = (0, 200, 0)       # green
COLOR_COASTING = (0, 200, 200)   # amber
COLOR_HANDOFF = (220, 80, 220)   # magenta pop for fresh cross-camera pickup
COLOR_LABEL_BG = (0, 0, 0)

LABEL_FONT = cv2.FONT_HERSHEY_SIMPLEX
LABEL_SCALE = 0.6
LABEL_THICKNESS = 1
BOX_THICKNESS = 1
LABEL_PAD_PX = 3

CENTER_MARKER_RADIUS = 4
CENTER_MARKER_ARM_PX = 9

VELOCITY_MIN_MAGNITUDE_PX_S = 40.0
VELOCITY_VECTOR_SCALE_S = 0.25

# 4-digit zero-padded display code wraps after this many IDs — a short,
# readable label that stays the same length forever. 10 000 is plenty for a
# single session; once it wraps, collisions with earlier long-dead tracks are
# cosmetic only (the internal ``global_id`` stays unique).
DISPLAY_ID_MODULO = 10_000


def format_track_label(global_id: int) -> str:
    """Deterministic 4-digit display code for a track's ``global_id``.

    Uses Knuth's multiplicative hash before taking the modulo so consecutive
    IDs scatter across the label space instead of showing ``#0001 #0002 …``
    (which reads as "obviously sequential" and draws the eye to the running
    count). Still fully deterministic — same ``global_id`` → same label.
    """
    mixed = (int(global_id) * 2654435761) & 0xFFFFFFFF
    return f"{mixed % DISPLAY_ID_MODULO:04d}"


def _label_color_for(track) -> tuple[int, int, int]:
    # Pieces that inherited their ID from an upstream camera stay magenta for
    # their whole lifetime — makes handoff events easy to spot while they ride
    # the downstream channel toward the carousel.
    if track.handoff_from is not None:
        return COLOR_HANDOFF
    if track.coasting:
        return COLOR_COASTING
    return COLOR_ACTIVE


def _draw_center_marker(
    frame: np.ndarray,
    center: tuple[float, float],
    color: tuple[int, int, int],
) -> tuple[int, int]:
    cx = int(round(center[0]))
    cy = int(round(center[1]))
    cv2.circle(frame, (cx, cy), CENTER_MARKER_RADIUS + 2, COLOR_LABEL_BG, 2, cv2.LINE_AA)
    cv2.circle(frame, (cx, cy), CENTER_MARKER_RADIUS, color, -1, cv2.LINE_AA)
    cv2.line(
        frame,
        (cx - CENTER_MARKER_ARM_PX, cy),
        (cx + CENTER_MARKER_ARM_PX, cy),
        COLOR_LABEL_BG,
        3,
        cv2.LINE_AA,
    )
    cv2.line(
        frame,
        (cx, cy - CENTER_MARKER_ARM_PX),
        (cx, cy + CENTER_MARKER_ARM_PX),
        COLOR_LABEL_BG,
        3,
        cv2.LINE_AA,
    )
    cv2.line(
        frame,
        (cx - CENTER_MARKER_ARM_PX, cy),
        (cx + CENTER_MARKER_ARM_PX, cy),
        color,
        1,
        cv2.LINE_AA,
    )
    cv2.line(
        frame,
        (cx, cy - CENTER_MARKER_ARM_PX),
        (cx, cy + CENTER_MARKER_ARM_PX),
        color,
        1,
        cv2.LINE_AA,
    )
    return cx, cy


class TrackOverlay:
    """Thin green bbox + compact #id pill + optional velocity arrow."""

    category = "detections"

    def __init__(self, get_tracks: Callable[[], list]):
        self._get_tracks = get_tracks

    def annotate(self, frame: np.ndarray) -> np.ndarray:
        tracks = self._get_tracks() or []
        for track in tracks:
            bbox = getattr(track, "bbox", None)
            if bbox is None:
                continue
            x1, y1, x2, y2 = [int(round(v)) for v in bbox]
            color = _label_color_for(track)

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, BOX_THICKNESS, cv2.LINE_AA)
            center = getattr(track, "center", None)
            if center is not None:
                _draw_center_marker(frame, center, color)

            label = f"#{format_track_label(track.global_id)}"
            (tw, th), baseline = cv2.getTextSize(label, LABEL_FONT, LABEL_SCALE, LABEL_THICKNESS)
            pad = LABEL_PAD_PX
            pill_w = tw + pad * 2
            pill_h = th + pad * 2
            pill_x1 = x1
            pill_y1 = max(0, y1 - pill_h - 1)
            pill_x2 = pill_x1 + pill_w
            pill_y2 = pill_y1 + pill_h

            # Dark background pill → readable over any background.
            cv2.rectangle(frame, (pill_x1, pill_y1), (pill_x2, pill_y2), COLOR_LABEL_BG, -1)
            cv2.putText(
                frame,
                label,
                (pill_x1 + pad, pill_y2 - pad - 1),
                LABEL_FONT,
                LABEL_SCALE,
                color,
                LABEL_THICKNESS,
                cv2.LINE_AA,
            )

            vx, vy = track.velocity_px_per_s
            magnitude = float(np.hypot(vx, vy))
            if magnitude >= VELOCITY_MIN_MAGNITUDE_PX_S:
                cx, cy = track.center
                end_x = int(round(cx + vx * VELOCITY_VECTOR_SCALE_S))
                end_y = int(round(cy + vy * VELOCITY_VECTOR_SCALE_S))
                cv2.arrowedLine(
                    frame,
                    (int(round(cx)), int(round(cy))),
                    (end_x, end_y),
                    color,
                    1,
                    cv2.LINE_AA,
                    tipLength=0.3,
                )

        return frame

    def metadata(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for track in self._get_tracks() or []:
            bbox = getattr(track, "bbox", None)
            if bbox is None:
                continue
            center = getattr(track, "center", None)
            velocity = getattr(track, "velocity_px_per_s", (0.0, 0.0))
            global_id = int(getattr(track, "global_id", 0))
            items.append({
                "type": "track_bbox",
                "category": self.category,
                "global_id": global_id,
                "label": format_track_label(global_id),
                "bbox": [int(round(value)) for value in bbox],
                "center": [float(center[0]), float(center[1])] if center is not None else None,
                "velocity_px_per_s": [float(velocity[0]), float(velocity[1])],
                "coasting": bool(getattr(track, "coasting", False)),
                "handoff_from": getattr(track, "handoff_from", None),
            })
        return items
