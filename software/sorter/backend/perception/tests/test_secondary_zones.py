"""Secondary (foreign) zone tests.

Secondary zones are display/tag-only polygons a camera observes that belong to
another channel. They must (a) build into rescaled masks, (b) tag detections by
center-in-mask membership, and CRUCIALLY (c) leave the primary attribution the
state machine reads completely unchanged.
"""

import math

import numpy as np

from perception.arcs import attributeBboxes, bboxInsideMask
from perception.channel import SecondaryZone, buildChannelDef


IMAGE_W = 400
IMAGE_H = 400
CENTER = (200, 200)
RADIUS = 140
BBOX_HALF = 6


def _annulus_polygon(inner=RADIUS - 30, outer=RADIUS + 30) -> np.ndarray:
    outer_pts, inner_pts = [], []
    for i in range(64):
        theta = 2.0 * math.pi * i / 64.0
        outer_pts.append([CENTER[0] + outer * math.cos(theta), CENTER[1] + outer * math.sin(theta)])
        inner_pts.append([CENTER[0] + inner * math.cos(theta), CENTER[1] + inner * math.sin(theta)])
    return np.array(outer_pts + list(reversed(inner_pts)), dtype=np.int32)


def _bbox_at_angle(angle_deg: float, radius: float = RADIUS):
    rad = math.radians(angle_deg)
    cx = CENTER[0] + radius * math.cos(rad)
    cy = CENTER[1] + radius * math.sin(rad)
    return (int(cx - BBOX_HALF), int(cy - BBOX_HALF), int(cx + BBOX_HALF), int(cy + BBOX_HALF))


def _square(cx, cy, half):
    return [[cx - half, cy - half], [cx + half, cy - half], [cx + half, cy + half], [cx - half, cy + half]]


def _channel(secondary=None):
    return buildChannelDef(
        channel_id=4,
        polygon=_annulus_polygon(),
        frame_shape=(IMAGE_H, IMAGE_W),
        section_zero_angle=0.0,
        drop_arc=(75.0, 105.0),
        exit_arc=(255.0, 285.0),
        precise_arc=(265.0, 285.0),
        arc_center=CENTER,
        secondary_zone_entries=secondary,
    )


def test_secondary_zone_builds_mask():
    ch = _channel([{"id": "sz1", "source_channel": 3, "zone_type": "exit", "points": _square(50, 50, 20)}])
    assert len(ch.secondary_zones) == 1
    z = ch.secondary_zones[0]
    assert z.id == "sz1" and z.source_channel == 3 and z.zone_type == "exit"
    assert z.mask.shape == (IMAGE_H, IMAGE_W)
    assert bool(z.mask[50, 50])          # center filled
    assert not bool(z.mask[200, 200])    # far away, empty


def test_membership_tagging():
    ch = _channel([{"id": "sz1", "source_channel": 3, "zone_type": "exit", "points": _square(50, 50, 20)}])
    z = ch.secondary_zones[0]
    assert bboxInsideMask((44, 44, 56, 56), z.mask)  # center (50,50) inside
    assert not bboxInsideMask((194, 194, 206, 206), z.mask)  # center (200,200) outside


def test_rescale_matches_primary():
    # Saved at 200x200, frame is 400x400 -> 2x. A zone square centered at (25,25)
    # in saved space must land centered at (50,50) in frame space.
    ch = buildChannelDef(
        channel_id=4,
        polygon=(_annulus_polygon().astype(np.float64) / 2.0).astype(np.int32),
        frame_shape=(IMAGE_H, IMAGE_W),
        section_zero_angle=0.0,
        drop_arc=(75.0, 105.0),
        exit_arc=(255.0, 285.0),
        precise_arc=None,
        arc_center=(CENTER[0] / 2.0, CENTER[1] / 2.0),
        saved_resolution=(IMAGE_W / 2.0, IMAGE_H / 2.0),
        secondary_zone_entries=[{"id": "sz1", "source_channel": 3, "zone_type": "drop", "points": _square(25, 25, 10)}],
    )
    z = ch.secondary_zones[0]
    assert bool(z.mask[50, 50])
    assert not bool(z.mask[25, 25])


def test_primary_attribution_unchanged_by_secondary_zones():
    plain = _channel(None)
    # Secondary zone deliberately overlaps the exit arc region to prove it does
    # not leak into the primary attribution.
    exit_bbox = _bbox_at_angle(270.0)
    sz_points = _square((exit_bbox[0] + exit_bbox[2]) // 2, (exit_bbox[1] + exit_bbox[3]) // 2, 40)
    withzones = _channel([{"id": "sz1", "source_channel": 3, "zone_type": "exit", "points": sz_points}])

    bboxes = [_bbox_at_angle(90.0), _bbox_at_angle(270.0)]
    assert attributeBboxes(bboxes, plain)[:5] == attributeBboxes(bboxes, withzones)[:5]
    # And the primary mask / section sets are byte-identical.
    assert np.array_equal(plain.mask, withzones.mask)
    assert plain.drop_sections == withzones.drop_sections
    assert plain.exit_sections == withzones.exit_sections
    assert plain.precise_sections == withzones.precise_sections


def test_malformed_entries_skipped():
    ch = _channel([
        {"id": "bad", "source_channel": 3, "zone_type": "exit", "points": [[1, 1], [2, 2]]},  # <3 pts
        "not-a-dict",
        {"id": "ok", "source_channel": 2, "zone_type": "drop", "points": _square(60, 60, 15)},
    ])
    assert [z.id for z in ch.secondary_zones] == ["ok"]
