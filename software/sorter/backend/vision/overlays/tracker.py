"""Overlay that renders persistent track IDs + velocity vectors.

Reads the latest track list from a callable so the overlay stays decoupled
from the VisionManager — inject via
``TrackOverlay(lambda: vm.getFeederTracks(role))``.
"""

from __future__ import annotations

from typing import Callable

import cv2
import numpy as np

from .scaling import overlay_scale_for_frame, scaled_px


# BGR to match OpenCV.
COLOR_ACTIVE = (0, 200, 0)       # green
COLOR_COASTING = (0, 200, 200)   # amber
COLOR_HANDOFF = (220, 80, 220)   # magenta pop for fresh cross-camera pickup
# Dim grey for tracks the whitelist has not yet confirmed as real — lets
# operators see that the detector is firing on apparatus without the
# overlay implying a real piece is present.
COLOR_UNCONFIRMED = (120, 120, 120)
# Ghosts are white — "Geister sind weiß". Distinct from real (green) and
# pending (gray) without stealing attention when debug-visible.
COLOR_GHOST = (255, 255, 255)
COLOR_LABEL_BG = (0, 0, 0)

LABEL_FONT = cv2.FONT_HERSHEY_SIMPLEX
LABEL_SCALE = 0.6
LABEL_THICKNESS = 1
BOX_THICKNESS = 1
LABEL_PAD_PX = 3

VELOCITY_MIN_MAGNITUDE_PX_S = 40.0
VELOCITY_VECTOR_SCALE_S = 0.25

# 4-digit zero-padded display code wraps after this many IDs — a short,
# readable label that stays the same length forever. 10 000 is plenty for a
# single session; once it wraps, collisions with earlier long-dead tracks are
# cosmetic only (the internal ``global_id`` stays unique). 4-char base36
# gives ~1.68M distinct codes, so collisions are rare for a single session.
_LABEL_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
_LABEL_LENGTH = 4
DISPLAY_ID_MODULO = len(_LABEL_ALPHABET) ** _LABEL_LENGTH


def format_track_label(global_id: int) -> str:
    """Deterministic 4-char base36 display code for a track's ``global_id``.

    Uses Knuth's multiplicative hash before reducing so consecutive IDs
    scatter across the label space instead of showing ``#0001 #0002 …``
    (which reads as "obviously sequential" and draws the eye to the running
    count). Still fully deterministic — same ``global_id`` → same label.
    """
    mixed = (int(global_id) * 2654435761) & 0xFFFFFFFF
    value = mixed % DISPLAY_ID_MODULO
    digits: list[str] = []
    for _ in range(_LABEL_LENGTH):
        digits.append(_LABEL_ALPHABET[value % len(_LABEL_ALPHABET)])
        value //= len(_LABEL_ALPHABET)
    return "".join(reversed(digits))


def _label_color_for(track) -> tuple[int, int, int]:
    # Unconfirmed (whitelist-pending) tracks render in dim grey so
    # operators can see the detector is firing without the overlay
    # implying a real piece is there. Handoff-backed tracks inherit
    # confirmed_real from the upstream so this branch only ever hits
    # apparatus ghosts / very fresh births.
    if not bool(getattr(track, "confirmed_real", False)):
        return COLOR_UNCONFIRMED
    # Pieces that inherited their ID from an upstream camera stay magenta for
    # their whole lifetime — makes handoff events easy to spot while they ride
    # the downstream channel toward the carousel.
    if track.handoff_from is not None:
        return COLOR_HANDOFF
    if track.coasting:
        return COLOR_COASTING
    return COLOR_ACTIVE


class TrackOverlay:
    """Thin green bbox + compact #id pill + optional velocity arrow."""

    category = "detections"

    def __init__(self, get_tracks: Callable[[], list]):
        self._get_tracks = get_tracks

    def annotate(self, frame: np.ndarray) -> np.ndarray:
        tracks = self._get_tracks() or []
        scale = overlay_scale_for_frame(frame)
        label_scale = LABEL_SCALE * scale
        label_thickness = scaled_px(LABEL_THICKNESS, scale)
        box_thickness = scaled_px(BOX_THICKNESS, scale)
        label_pad = scaled_px(LABEL_PAD_PX, scale)
        arrow_thickness = scaled_px(1, scale)
        for track in tracks:
            bbox = getattr(track, "bbox", None)
            if bbox is None:
                continue
            x1, y1, x2, y2 = [int(round(v)) for v in bbox]
            color = _label_color_for(track)
            confirmed = bool(getattr(track, "confirmed_real", False))

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, box_thickness, cv2.LINE_AA)

            # Whitelist gate: only show the track-id chip for
            # confirmed-real tracks. Unconfirmed boxes stay visible (so
            # operators see the detector is still firing on the
            # apparatus) but without a label that would imply a real
            # tracked piece is there.
            if confirmed:
                label = f"#{format_track_label(track.global_id)}"
                (tw, th), baseline = cv2.getTextSize(label, LABEL_FONT, label_scale, label_thickness)
                pad = label_pad
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
                    label_scale,
                    color,
                    label_thickness,
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
                    arrow_thickness,
                    cv2.LINE_AA,
                    tipLength=0.3,
                )

        return frame
