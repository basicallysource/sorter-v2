"""Immutable per-channel definition consumed by the perception package.

A ``ChannelDef`` is built from a channel's saved zones (``zones``) at the live
frame's size. It carries everything an ``InferenceWorker`` needs to turn a
bbox into (``in_drop``, ``in_exit``): the mask of the channel's area, the
ring's center and reference angle, and the 1-degree sections of each zone.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# Lone exception to the standalone rule: the C4 travel-direction flag is a pure
# boolean shared with the feeder/SM sites so all three can never disagree.
from defs.consts import CLASSIFICATION_CHANNEL_CLOCKWISE
from zones.model import CAMERA_ROLE, ChannelZones, Span, channelPolygon, sectionsFor


SECTION_COUNT = 360
SECTION_DEG = 360.0 / SECTION_COUNT


# The feeder channels: their exits drop onto the next channel.
FEEDER_CHANNELS: frozenset[int] = frozenset({2, 3})


# Channels whose piece travel runs REVERSE (decreasing relative angle / negative
# motor degrees) toward the exit instead of forward. C4 travels reverse only in
# the counter-clockwise build; clockwise makes it forward like C2/C3. Driven by
# the single source of truth in defs.consts.
REVERSE_TRAVEL_CHANNELS: frozenset[int] = (
    frozenset() if CLASSIFICATION_CHANNEL_CLOCKWISE else frozenset({4})
)


@dataclass(frozen=True)
class ChannelDef:
    channel_id: int
    camera_source_id: str
    center: tuple[float, float]
    radius1_angle_image: float
    mask: np.ndarray
    drop_sections: frozenset[int]
    # ``exit_sections`` unions the exit and precise arcs — this is what the
    # cascade reads as "in_exit" and what gates the precise-pulse decision.
    # ``precise_sections`` is the precise sub-arc on its own, kept separate so
    # callers that need "exit but not precise" (e.g. jitter-unstick dwell) can
    # tell the two apart.
    exit_sections: frozenset[int]
    precise_sections: frozenset[int] = frozenset()
    # When True the piece travels REVERSE (decreasing relative angle) toward the
    # exit, so the forward-distance arc math measures the gap to the FAR edge of
    # the exit-only arc instead of the near edge (see ``arcs._leadingExitApproach``).
    # Set per channel from ``REVERSE_TRAVEL_CHANNELS``; C2/C3 stay forward.
    reverse: bool = False
    # A band just past the exit's edge, across the exit's angles (feeder
    # channels). A detection wholly inside it is kept and shown, but it is not
    # on this channel: the piece has left it.
    exit_margin_mask: np.ndarray | None = None

    @property
    def has_zones(self) -> bool:
        return bool(self.drop_sections) and bool(self.exit_sections)


# ---------------------------------------------------------------------------
# ChannelDef construction
# ---------------------------------------------------------------------------


def buildChannelDef(
    *,
    channel_id: int,
    polygon: np.ndarray,
    frame_shape: tuple[int, int],
    section_zero_angle: float,
    drop_arc: tuple[float, float] | None,
    exit_arc: tuple[float, float] | None,
    precise_arc: tuple[float, float] | None,
    arc_center: tuple[float, float] | None = None,
) -> ChannelDef:
    """Pure builder, in frame coordinates. ``arc_center`` is the ring's center,
    the pivot every angle is measured from; without it (tests) the polygon's
    centroid stands in."""
    if channel_id not in CAMERA_ROLE:
        raise ValueError(f"unknown perception channel_id={channel_id}")
    h, w = frame_shape
    mask = np.zeros((h, w), dtype=np.uint8)
    polygon_centroid: tuple[float, float] | None = None
    if polygon is not None and len(polygon) >= 3:
        points = np.asarray(polygon, dtype=np.float64)
        cv2.fillPoly(mask, [np.round(points).astype(np.int32)], 255)
        polygon_centroid = (float(np.mean(points[:, 0])), float(np.mean(points[:, 1])))
    if arc_center is not None:
        center = (float(arc_center[0]), float(arc_center[1]))
    elif polygon_centroid is not None:
        center = polygon_centroid
    else:
        center = (w / 2.0, h / 2.0)

    def sections(arc: tuple[float, float] | None) -> frozenset[int]:
        if arc is None or (arc[1] - arc[0]) % 360.0 == 0:
            return frozenset()
        return sectionsFor(Span(*arc), section_zero_angle)

    precise_sections = sections(precise_arc)
    return ChannelDef(
        channel_id=channel_id,
        camera_source_id=CAMERA_ROLE[channel_id],
        center=center,
        radius1_angle_image=float(section_zero_angle),
        mask=mask,
        drop_sections=sections(drop_arc),
        exit_sections=sections(exit_arc) | precise_sections,
        precise_sections=precise_sections,
        reverse=channel_id in REVERSE_TRAVEL_CHANNELS,
        exit_margin_mask=(
            _exitMarginMask(mask, center, exit_arc)
            if channel_id in FEEDER_CHANNELS and exit_arc is not None
            else None
        ),
    )


def channelDefFor(zones: ChannelZones, frame_shape: tuple[int, int]) -> ChannelDef:
    """The production entry point: a channel's saved zones at the live frame's
    size (``frame_shape`` is (height, width))."""
    h, w = frame_shape
    live = zones.scaledTo((w, h))
    precise = live.precise
    return buildChannelDef(
        channel_id=live.channel,
        polygon=np.asarray(channelPolygon(live), dtype=np.float64),
        frame_shape=(h, w),
        section_zero_angle=live.reference_angle,
        drop_arc=(live.drop.start, live.drop.end),
        exit_arc=(live.exit.start, live.exit.end),
        precise_arc=(precise.start, precise.end) if precise is not None else None,
        arc_center=live.ring.center,
    )


# How far past the exit's edge the margin reaches, as a share of the frame's width.
EXIT_MARGIN_FRACTION = 0.05


def _exitMarginMask(
    mask: np.ndarray,
    center: tuple[float, float],
    exit_arc: tuple[float, float],
) -> np.ndarray:
    h, w = mask.shape[:2]
    px = max(3, int(round(EXIT_MARGIN_FRACTION * w)))
    grown = cv2.dilate(mask, np.ones((2 * px + 1, 2 * px + 1), np.uint8))
    start = exit_arc[0]
    span = (exit_arc[1] - exit_arc[0]) % 360.0
    reach = float(w + h)
    wedge_pts = [center] + [
        (
            center[0] + reach * np.cos(np.radians(start + span * i / 16)),
            center[1] + reach * np.sin(np.radians(start + span * i / 16)),
        )
        for i in range(17)
    ]
    wedge = np.zeros_like(mask)
    cv2.fillPoly(wedge, [np.asarray(wedge_pts, dtype=np.int32)], 255)
    return cv2.bitwise_and(cv2.bitwise_and(grown, cv2.bitwise_not(mask)), wedge)
