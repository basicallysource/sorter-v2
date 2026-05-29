"""Region-attribution tests for the GO_TO_ANGLE_REV01 + SIMPLE_STATE_MACHINE
decision path.

The only thing the decision logic needs to do per loop:
  - per detection, know which channel it's on (one camera per channel)
  - per detection, know whether its bbox is in the drop zone or exit zone
    (or neither) of that channel.

Everything cascading downstream of those two facts is a few-line state rule
in go_to_angle/flow.py. If these tests pass, the inputs the decision logic
sees are correct. If they fail, the entire feeder cascade is fed garbage and
no amount of state-machine tweaking can save it.
"""

import math
from typing import Iterable

import numpy as np

from defs.channel import ChannelDetection, PolygonChannel
from subsystems.feeder.analysis import (
    analyzeFeederChannels,
    getBboxSections,
)
from subsystems.feeder.go_to_angle.geometry import (
    pieceRelativeAngle,
    sectionForRelativeAngle,
)


IMAGE_W = 400
IMAGE_H = 400
CENTER = (200.0, 200.0)
RADIUS = 140.0
BBOX_HALF = 6  # 12 px box — small enough that all 9 sample points land in
               # one or two sections.


def _bbox_at_angle(angle_deg: float, radius: float = RADIUS) -> tuple[int, int, int, int]:
    """Build a small bbox whose center is at (radius, angle) around CENTER.

    Uses image coordinates (y grows downward), so angle is measured the same
    way the production code measures it: ``np.arctan2(dy, dx)`` against the
    polygon center.
    """
    rad = math.radians(angle_deg)
    cx = CENTER[0] + radius * math.cos(rad)
    cy = CENTER[1] + radius * math.sin(rad)
    return (
        int(round(cx - BBOX_HALF)),
        int(round(cy - BBOX_HALF)),
        int(round(cx + BBOX_HALF)),
        int(round(cy + BBOX_HALF)),
    )


def _annulus_mask(
    inner: float = RADIUS - 30,
    outer: float = RADIUS + 30,
) -> np.ndarray:
    mask = np.zeros((IMAGE_H, IMAGE_W), dtype=np.uint8)
    yy, xx = np.ogrid[:IMAGE_H, :IMAGE_W]
    dx = xx - CENTER[0]
    dy = yy - CENTER[1]
    r2 = dx * dx + dy * dy
    in_band = (r2 >= inner * inner) & (r2 <= outer * outer)
    mask[in_band] = 255
    return mask


def _polygon_from_mask(mask: np.ndarray) -> np.ndarray:
    """A coarse polygon hugging the annulus bounding box — only used as a
    placeholder for ``PolygonChannel.polygon``. Region attribution uses
    ``mask`` + sections, not the polygon, so a bounding box suffices."""
    ys, xs = np.where(mask > 0)
    if ys.size == 0:
        return np.zeros((0, 2), dtype=np.int32)
    return np.array(
        [
            [int(xs.min()), int(ys.min())],
            [int(xs.max()), int(ys.min())],
            [int(xs.max()), int(ys.max())],
            [int(xs.min()), int(ys.max())],
        ],
        dtype=np.int32,
    )


def _section_set(start_deg: int, end_deg: int) -> set[int]:
    """Section ids covering ``[start_deg, end_deg)`` on a 360-section ring."""
    if start_deg <= end_deg:
        return set(range(start_deg, end_deg))
    return set(range(start_deg, 360)) | set(range(0, end_deg))


def _make_channel(
    channel_id: int,
    *,
    drop_range: tuple[int, int],
    exit_range: tuple[int, int],
    radius1_angle_image: float = 0.0,
) -> PolygonChannel:
    mask = _annulus_mask()
    return PolygonChannel(
        channel_id=channel_id,
        polygon=_polygon_from_mask(mask),
        center=CENTER,
        radius1_angle_image=radius1_angle_image,
        mask=mask,
        dropzone_sections=_section_set(*drop_range),
        exit_sections=_section_set(*exit_range),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _channel_2() -> PolygonChannel:
    # C2 drop zone south (around 90°), exit zone north (around 270°).
    return _make_channel(2, drop_range=(75, 105), exit_range=(255, 285))


def _channel_3() -> PolygonChannel:
    # Same arc geometry for simplicity; different channel_id distinguishes
    # the detections.
    return _make_channel(3, drop_range=(75, 105), exit_range=(255, 285))


# --- getBboxSections is the primitive every other check sits on top of ---


def test_bbox_inside_dropzone_arc_intersects_dropzone_sections() -> None:
    ch = _channel_3()
    bbox = _bbox_at_angle(90.0)  # middle of the drop arc
    sections = getBboxSections(bbox, ch)
    assert sections & ch.dropzone_sections, (
        f"bbox at 90° (middle of drop zone) failed to overlap dropzone_sections; "
        f"bbox sections={sorted(sections)}, drop={sorted(ch.dropzone_sections)}"
    )
    assert not (sections & ch.exit_sections), (
        "bbox at 90° should not touch the exit zone (centered at 270°)"
    )


def test_bbox_inside_exit_arc_intersects_exit_sections() -> None:
    ch = _channel_3()
    bbox = _bbox_at_angle(270.0)  # middle of the exit arc
    sections = getBboxSections(bbox, ch)
    assert sections & ch.exit_sections, (
        f"bbox at 270° (middle of exit zone) failed to overlap exit_sections; "
        f"bbox sections={sorted(sections)}, exit={sorted(ch.exit_sections)}"
    )
    assert not (sections & ch.dropzone_sections)


def test_bbox_between_zones_misses_both() -> None:
    ch = _channel_3()
    bbox = _bbox_at_angle(0.0)  # neutral angle, far from both arcs
    sections = getBboxSections(bbox, ch)
    assert not (sections & ch.dropzone_sections)
    assert not (sections & ch.exit_sections)


# --- sectionForRelativeAngle(pieceRelativeAngle(...)) is what go_to_angle uses ---


def test_piece_relative_angle_matches_section_membership() -> None:
    ch = _channel_3()
    # Bbox in the exit zone → relative angle round-trips into an exit section.
    bbox_exit = _bbox_at_angle(270.0)
    rel = pieceRelativeAngle(bbox_exit, ch)
    sec = sectionForRelativeAngle(rel)
    assert sec in ch.exit_sections, (
        f"piece at angle 270° produced section {sec}, not in exit_sections "
        f"{sorted(ch.exit_sections)} (relative_angle={rel:.2f})"
    )
    # And a drop-zone bbox lands in a drop section.
    bbox_drop = _bbox_at_angle(90.0)
    rel = pieceRelativeAngle(bbox_drop, ch)
    sec = sectionForRelativeAngle(rel)
    assert sec in ch.dropzone_sections


def test_radius1_offset_rotates_the_arcs_consistently() -> None:
    """If radius1_angle_image rotates 30°, a bbox at image angle 300° should
    still land in the exit zone (which was at relative 270° on a 0°-aligned
    channel)."""
    ch = _make_channel(
        3,
        drop_range=(75, 105),
        exit_range=(255, 285),
        radius1_angle_image=30.0,
    )
    bbox = _bbox_at_angle(300.0)  # 300° image = 270° relative
    rel = pieceRelativeAngle(bbox, ch)
    sec = sectionForRelativeAngle(rel)
    assert sec in ch.exit_sections, (
        f"with radius1_angle_image=30°, bbox at image 300° gave relative "
        f"{rel:.2f}° section {sec}; expected to land in exit_sections"
    )


# --- analyzeFeederChannels is what feeds go_to_angle's downstream_ready ---


def test_analyze_marks_only_the_channel_a_detection_belongs_to() -> None:
    ch3 = _channel_3()
    # One piece in C3's drop zone; nothing in C2.
    det = ChannelDetection(
        bbox=_bbox_at_angle(90.0),
        channel_id=3,
        channel=ch3,
    )
    analysis = analyzeFeederChannels([det])
    assert analysis.ch3_dropzone_occupied is True
    assert analysis.ch2_dropzone_occupied is False, (
        "a C3 detection must not light up the C2 dropzone flag — channels "
        "are filtered by channel_id, one camera per channel"
    )


def test_analyze_ignores_detections_with_wrong_channel_id() -> None:
    """Defensive: even if a producer accidentally tagged a C2 bbox with C3's
    channel object (e.g. via a bad call site), analyzeFeederChannels still
    only fires the channel matching ``det.channel_id``.
    """
    ch3 = _channel_3()
    det = ChannelDetection(
        bbox=_bbox_at_angle(90.0),  # geometry says drop zone
        channel_id=2,                # but it claims to be on C2
        channel=ch3,                 # with C3's polygon
    )
    analysis = analyzeFeederChannels([det])
    assert analysis.ch3_dropzone_occupied is False
    # C2 path is also checked via det.channel, so the C2 flag CAN go up here;
    # that's fine — the point of this test is that the channel_id is the
    # routing key, not the polygon.


def test_piece_at_exit_logic_matches_arc_membership() -> None:
    """Mirror the inline ``_piece_at_exit`` check from go_to_angle/flow.py."""
    ch3 = _channel_3()
    det_drop = ChannelDetection(bbox=_bbox_at_angle(90.0), channel_id=3, channel=ch3)
    det_exit = ChannelDetection(bbox=_bbox_at_angle(270.0), channel_id=3, channel=ch3)

    def at_exit(dets: Iterable[ChannelDetection]) -> bool:
        for d in dets:
            if d.channel_id != 3:
                continue
            rel = pieceRelativeAngle(d.bbox, d.channel)
            if sectionForRelativeAngle(rel) in d.channel.exit_sections:
                return True
        return False

    assert at_exit([det_exit]) is True
    assert at_exit([det_drop]) is False
    assert at_exit([det_drop, det_exit]) is True


def test_empty_zone_sets_never_attribute_anything() -> None:
    """Regression guard: if saved arcs are missing, exit_sections and
    dropzone_sections are empty sets — no detection should ever be reported
    as 'at exit' or 'in drop zone'. The bug we're guarding against is the
    channel silently running with empty zones and the cascade lock-up
    appearing to work because nothing is ever 'occupied'."""
    bare = PolygonChannel(
        channel_id=3,
        polygon=_polygon_from_mask(_annulus_mask()),
        center=CENTER,
        radius1_angle_image=0.0,
        mask=_annulus_mask(),
        dropzone_sections=set(),
        exit_sections=set(),
    )
    det = ChannelDetection(bbox=_bbox_at_angle(90.0), channel_id=3, channel=bare)
    analysis = analyzeFeederChannels([det])
    assert analysis.ch3_dropzone_occupied is False
    rel = pieceRelativeAngle(det.bbox, det.channel)
    assert sectionForRelativeAngle(rel) not in bare.exit_sections
