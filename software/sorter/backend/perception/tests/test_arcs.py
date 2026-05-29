"""Bbox→(in_drop, in_exit) attribution tests.

If these pass, the per-frame inputs to the cascade are correct. If they
fail, no amount of state-machine tweaking can save the cascade.
"""

import math

import cv2
import numpy as np

from perception.arcs import (
    attributeBbox,
    attributeBboxes,
    bboxInsideChannelMask,
    bboxSections,
    comInPreciseZone,
    exitComForwardDeg,
    exitNearEdgeSection,
    forwardClearanceToExitDeg,
)
from perception.channel import ChannelDef, buildChannelDef


IMAGE_W = 400
IMAGE_H = 400
CENTER = (200, 200)
RADIUS = 140
BBOX_HALF = 6


def _annulus_polygon(
    inner: float = RADIUS - 30, outer: float = RADIUS + 30
) -> np.ndarray:
    """An annulus, approximated by 64 outer + 64 inner samples."""
    outer_pts = []
    inner_pts = []
    for i in range(64):
        theta = 2.0 * math.pi * i / 64.0
        outer_pts.append([CENTER[0] + outer * math.cos(theta), CENTER[1] + outer * math.sin(theta)])
        inner_pts.append([CENTER[0] + inner * math.cos(theta), CENTER[1] + inner * math.sin(theta)])
    return np.array(outer_pts + list(reversed(inner_pts)), dtype=np.int32)


def _bbox_at_angle(angle_deg: float, radius: float = RADIUS) -> tuple[int, int, int, int]:
    rad = math.radians(angle_deg)
    cx = CENTER[0] + radius * math.cos(rad)
    cy = CENTER[1] + radius * math.sin(rad)
    return (
        int(round(cx - BBOX_HALF)),
        int(round(cy - BBOX_HALF)),
        int(round(cx + BBOX_HALF)),
        int(round(cy + BBOX_HALF)),
    )


def _channel(
    channel_id: int = 3,
    drop_arc: tuple[float, float] = (75.0, 105.0),
    exit_arc: tuple[float, float] = (255.0, 285.0),
    precise_arc: tuple[float, float] | None = None,
    section_zero: float = 0.0,
) -> ChannelDef:
    polygon = _annulus_polygon()
    return buildChannelDef(
        channel_id=channel_id,
        polygon=polygon,
        frame_shape=(IMAGE_H, IMAGE_W),
        section_zero_angle=section_zero,
        drop_arc=drop_arc,
        exit_arc=exit_arc,
        precise_arc=precise_arc,
    )


# --- attribution primitives ------------------------------------------------


def test_drop_arc_lights_up_in_drop() -> None:
    ch = _channel()
    bbox = _bbox_at_angle(90.0)  # middle of drop arc 75-105
    in_drop, in_exit = attributeBbox(bbox, ch)
    assert in_drop, f"bbox at 90° should be in drop arc 75-105; sections={sorted(bboxSections(bbox, ch))}"
    assert not in_exit


def test_exit_arc_lights_up_in_exit() -> None:
    ch = _channel()
    bbox = _bbox_at_angle(270.0)  # middle of exit arc 255-285
    in_drop, in_exit = attributeBbox(bbox, ch)
    assert in_exit
    assert not in_drop


def test_neither_zone_when_between() -> None:
    ch = _channel()
    bbox = _bbox_at_angle(0.0)  # far from both arcs
    in_drop, in_exit = attributeBbox(bbox, ch)
    assert not in_drop
    assert not in_exit


def test_bbox_off_channel_attributes_nothing() -> None:
    """A bbox whose center is outside the channel polygon must not light up
    either flag — that's a noise leak from outside the channel."""
    ch = _channel()
    # Place a bbox well inside the inner radius (off the annulus).
    bbox = (
        CENTER[0] - BBOX_HALF,
        CENTER[1] - BBOX_HALF,
        CENTER[0] + BBOX_HALF,
        CENTER[1] + BBOX_HALF,
    )
    assert not bboxInsideChannelMask(bbox, ch)
    in_drop, in_exit = attributeBbox(bbox, ch)
    assert not in_drop
    assert not in_exit


def test_section_zero_rotation_is_applied() -> None:
    """Arc angles are image-space; section_zero rotates the section-id
    coordinate system. A bbox at image angle 270° must land in the exit
    arc at image-space (255°, 285°) regardless of section_zero — because
    the saved arcs are ALSO image-space."""
    for section_zero in (0.0, 30.0, 90.0, 200.0):
        ch = _channel(section_zero=section_zero)
        bbox = _bbox_at_angle(270.0)
        in_drop, in_exit = attributeBbox(bbox, ch)
        assert in_exit, f"bbox at image angle 270° must be in_exit; section_zero={section_zero}"
        assert not in_drop, f"bbox at image angle 270° must NOT be in_drop; section_zero={section_zero}"


def test_empty_arcs_attribute_nothing() -> None:
    """Regression guard: a misconfigured channel with no saved arcs must
    NOT silently report 'always clear, never at exit' — i.e. attribution
    is False but the cascade now sees no exit-blocking, no drop-blocking,
    no signal at all. The cascade test pins what happens with that input."""
    ch = buildChannelDef(
        channel_id=3,
        polygon=_annulus_polygon(),
        frame_shape=(IMAGE_H, IMAGE_W),
        section_zero_angle=0.0,
        drop_arc=None,
        exit_arc=None,
        precise_arc=None,
    )
    assert ch.drop_sections == frozenset()
    assert ch.exit_sections == frozenset()
    in_drop, in_exit = attributeBbox(_bbox_at_angle(90.0), ch)
    assert not in_drop
    assert not in_exit


def test_attribute_bboxes_aggregates_correctly() -> None:
    ch = _channel()
    bboxes = [
        _bbox_at_angle(90.0),   # drop
        _bbox_at_angle(0.0),    # neither (on channel, off arcs)
        _bbox_at_angle(270.0),  # exit
    ]
    any_drop, any_exit, _any_precise, _any_majority, n_on, _per_bbox = attributeBboxes(bboxes, ch)
    assert any_drop
    assert any_exit
    assert n_on == 3


def test_attribute_bboxes_skips_off_channel() -> None:
    ch = _channel()
    on = _bbox_at_angle(90.0)
    # Bbox far above the annulus — center not in mask.
    off = (10, 10, 22, 22)
    assert not bboxInsideChannelMask(off, ch)
    any_drop, any_exit, _any_precise, _any_majority, n_on, _per_bbox2 = attributeBboxes([on, off], ch)
    assert any_drop
    assert not any_exit
    assert n_on == 1


# --- exit/precise union -----------------------------------------------------


def test_exit_sections_union_precise() -> None:
    # Precise arc adjacent to the exit (255-285) on the CCW/approach side.
    ch = _channel(precise_arc=(225.0, 255.0))
    # A bbox in the precise band must read in_exit — the build merges the two
    # arcs into exit_sections so everything that "looks at the exit" sees both.
    in_drop, in_exit = attributeBbox(_bbox_at_angle(240.0), ch)
    assert in_exit
    assert not in_drop
    # And the original exit arc still reads in_exit.
    _, in_exit_orig = attributeBbox(_bbox_at_angle(270.0), ch)
    assert in_exit_orig


def test_exit_sections_no_precise_is_exit_only() -> None:
    ch = _channel()  # no precise arc
    _, in_exit_precise_band = attributeBbox(_bbox_at_angle(240.0), ch)
    assert not in_exit_precise_band


# --- forward clearance to exit (advance cap) -------------------------------


def test_exit_near_edge_is_entry_section() -> None:
    ch = _channel()  # exit arc 255-285, section_zero 0
    assert exitNearEdgeSection(ch) == 255


def test_clearance_measures_forward_distance_to_exit_edge() -> None:
    ch = _channel()
    # A piece at 200° sits between the drop (75-105) and exit (255-285) arcs.
    # Forward distance to the exit's near edge (255°) is ~55°.
    bbox = _bbox_at_angle(200.0)
    clearance = forwardClearanceToExitDeg([bbox], ch)
    assert clearance is not None
    assert 50.0 <= clearance <= 56.0


def test_clearance_uses_most_forward_piece() -> None:
    ch = _channel()
    # Rear piece in drop (90°, ~165° away) and a leading piece at 200° (~55°).
    # The cap must follow the leading piece, not the rear one.
    bboxes = [_bbox_at_angle(90.0), _bbox_at_angle(200.0)]
    clearance = forwardClearanceToExitDeg(bboxes, ch)
    assert clearance is not None
    assert 50.0 <= clearance <= 56.0


def test_clearance_none_without_pieces_or_exit() -> None:
    ch = _channel()
    assert forwardClearanceToExitDeg([], ch) is None
    no_exit = _channel(exit_arc=(0.0, 0.0))
    assert forwardClearanceToExitDeg([_bbox_at_angle(200.0)], no_exit) is None


# --- exit COM forward distance (fast eject) --------------------------------


def test_exit_com_forward_positive_when_behind_edge() -> None:
    ch = _channel()  # exit near edge at 255°, section_zero 0
    # A single small bbox centered at 200° — COM is ~55° behind the near edge.
    bbox = _bbox_at_angle(200.0)
    com = exitComForwardDeg([bbox], ch)
    assert com is not None
    assert 53.0 <= com <= 57.0


def test_exit_com_forward_negative_when_past_edge() -> None:
    ch = _channel()  # exit arc 255-285
    # COM in the middle of the exit arc (270°) is ~15° past the near edge → negative.
    bbox = _bbox_at_angle(270.0)
    com = exitComForwardDeg([bbox], ch)
    assert com is not None
    assert -17.0 <= com <= -13.0


def test_exit_com_uses_leading_piece() -> None:
    ch = _channel()
    # Rear piece in drop (90°) and a leading piece at 240° (~15° from edge).
    # The smallest forward distance wins.
    bboxes = [_bbox_at_angle(90.0), _bbox_at_angle(240.0)]
    com = exitComForwardDeg(bboxes, ch)
    assert com is not None
    assert 13.0 <= com <= 17.0


def test_exit_com_none_without_pieces_or_exit() -> None:
    ch = _channel()
    assert exitComForwardDeg([], ch) is None
    no_exit = _channel(exit_arc=(0.0, 0.0))
    assert exitComForwardDeg([_bbox_at_angle(200.0)], no_exit) is None


def test_exit_com_rear_arc_piece_is_not_treated_as_past_edge() -> None:
    """Regression: a piece far around the rear of the channel must read as a
    LARGE POSITIVE forward distance, never a large negative — otherwise the
    fast-eject controller mistakes it for 'already at the exit' and jitters
    forever instead of moving the real leading piece (observed live as
    com=-157.6°). Exit arc 255-285, near edge 255."""
    # A piece at image angle 50° is ~205° behind the near edge going forward.
    rear = _bbox_at_angle(50.0)
    com_rear = exitComForwardDeg([rear], _channel())
    assert com_rear is not None
    assert com_rear > 180.0, f"rear piece must read large positive, got {com_rear}"
    # With a real leading piece just behind the exit (250°, ~5° behind), the
    # leading piece — not the rear one — wins the min.
    leading = _bbox_at_angle(250.0)
    com = exitComForwardDeg([rear, leading], _channel())
    assert com is not None
    assert 3.0 <= com <= 8.0, f"leading piece should win at ~5°, got {com}"


def test_exit_com_measures_to_exit_only_not_precise() -> None:
    """Regression for the live false-trigger: with a precise arc (225-255)
    drawn BEFORE the exit arc (255-285), a piece sitting in the PRECISE zone
    (240°) must read a POSITIVE forward gap to the exit-only entry edge (255°),
    NOT <= 0. <= 0 would mean '>=50% in the exit' and start an eject while the
    piece never reached the real exit zone."""
    ch = _channel(precise_arc=(225.0, 255.0))  # exit_only = 255..284, entry 255
    # Piece centered in the precise band — short of the exit zone by ~15°.
    com_precise = exitComForwardDeg([_bbox_at_angle(240.0)], ch)
    assert com_precise is not None
    assert com_precise > 0.0, f"precise-zone piece must read positive gap, got {com_precise}"
    assert 13.0 <= com_precise <= 17.0
    # A piece actually in the exit-only region (270°) reads negative (>=50% in).
    com_exit = exitComForwardDeg([_bbox_at_angle(270.0)], ch)
    assert com_exit is not None
    assert com_exit < 0.0, f"exit-zone piece must read negative gap, got {com_exit}"


def test_com_in_precise_zone_is_the_eject_trigger() -> None:
    """The eject trigger: True only when the leading piece's COM is in the
    precise zone (225-255), not when it is before it or already in the exit."""
    ch = _channel(precise_arc=(225.0, 255.0))  # exit 255-285, precise 225-255
    assert comInPreciseZone([_bbox_at_angle(240.0)], ch) is True   # in precise
    assert comInPreciseZone([_bbox_at_angle(200.0)], ch) is False  # before precise
    assert comInPreciseZone([_bbox_at_angle(270.0)], ch) is False  # in exit, past precise
    assert comInPreciseZone([], ch) is False                        # no piece


# --- equivalence with legacy section math ----------------------------------


def test_perception_bbox_sections_match_legacy_getBboxSections() -> None:
    """The legacy ``subsystems.feeder.analysis.getBboxSections`` is the
    reference; perception's section math must produce the same set for
    the same inputs (otherwise saved arcs will attribute differently)."""
    from defs.channel import PolygonChannel
    from subsystems.feeder.analysis import getBboxSections as legacy_getBboxSections

    ch = _channel()
    legacy_channel = PolygonChannel(
        channel_id=ch.channel_id,
        polygon=np.zeros((0, 2), dtype=np.int32),
        center=ch.center,
        radius1_angle_image=ch.radius1_angle_image,
        mask=ch.mask,
        dropzone_sections=set(ch.drop_sections),
        exit_sections=set(ch.exit_sections),
    )
    for angle in (0.0, 30.0, 90.0, 150.0, 210.0, 270.0, 350.0):
        bbox = _bbox_at_angle(angle)
        ours = set(bboxSections(bbox, ch))
        theirs = set(legacy_getBboxSections(bbox, legacy_channel))
        assert ours == theirs, (
            f"section mismatch at angle={angle}°: perception={sorted(ours)}, "
            f"legacy={sorted(theirs)}"
        )


# Suppress unused-import warning; cv2 is used transitively via buildChannelDef.
_ = cv2
