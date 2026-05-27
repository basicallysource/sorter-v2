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
    any_drop, any_exit, n_on = attributeBboxes(bboxes, ch)
    assert any_drop
    assert any_exit
    assert n_on == 3


def test_attribute_bboxes_skips_off_channel() -> None:
    ch = _channel()
    on = _bbox_at_angle(90.0)
    # Bbox far above the annulus — center not in mask.
    off = (10, 10, 22, 22)
    assert not bboxInsideChannelMask(off, ch)
    any_drop, any_exit, n_on = attributeBboxes([on, off], ch)
    assert any_drop
    assert not any_exit
    assert n_on == 1


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
