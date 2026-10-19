from __future__ import annotations

import math

import cv2
import numpy as np
import pytest

from zones.finder import findZones
from zones.model import ChannelZones, Ring, Span

CENTER = (660.0, 350.0)
RIM = 300.0


def _picture(seed: int, turned: float = 0.0, hub_offset: tuple[int, int] = (0, 0)) -> np.ndarray:
    """A channel from above: a grey surround, a light stator ring, the darker
    turning rotor with radial ridges, a hub, a static guide bar across the rim,
    and a few pieces riding at the rim."""
    rng = np.random.default_rng(seed)
    img = np.full((720, 1280, 3), 70, np.uint8)
    c = (int(CENTER[0]), int(CENTER[1]))
    cv2.circle(img, c, 420, (205, 205, 200), -1)
    cv2.circle(img, c, int(RIM), (150, 150, 150), -1)
    for k in range(12):
        a = math.radians(turned + k * 30)
        cv2.line(img, c, (int(c[0] + RIM * math.cos(a)), int(c[1] + RIM * math.sin(a))), (165, 165, 165), 3)
    cv2.circle(img, (c[0] + hub_offset[0], c[1] + hub_offset[1]), 60, (30, 30, 30), -1)
    guide = math.radians(215)
    cv2.line(img, c, (int(c[0] + 330 * math.cos(guide)), int(c[1] + 330 * math.sin(guide))), (90, 90, 95), 18)
    for _ in range(5):
        a = rng.uniform(0, 2 * math.pi)
        r = RIM - rng.uniform(12, 30)
        p = (int(c[0] + r * math.cos(a)), int(c[1] + r * math.sin(a)))
        color = tuple(int(v) for v in rng.integers(0, 255, 3))
        cv2.rectangle(img, (p[0] - 14, p[1] - 9), (p[0] + 14, p[1] + 9), color, -1)
    noise = rng.normal(0, 3, img.shape)
    return np.clip(img + noise, 0, 255).astype(np.uint8)


def _current(center: tuple[float, float]) -> ChannelZones:
    return ChannelZones(
        channel=3,
        frame=(1280, 720),
        ring=Ring(center, 200.0, 420.0, 330.0),
        drop=Span(288.0, 9.0),
        exit=Span(169.0, 201.0),
        precise_width=6.0,
    )


def test_one_picture_finds_the_center_and_the_rim() -> None:
    found = findZones(3, [_picture(1)])
    ring = found.zones.ring
    assert math.dist(ring.center, CENTER) < 8.0
    assert ring.exit_radius == pytest.approx(RIM, rel=0.04)
    assert ring.inner_radius < RIM < ring.outer_radius
    assert found.zones.source["ring"] == "found"


def test_pictures_over_time_find_the_rim_too() -> None:
    found = findZones(3, [_picture(seed, turned=seed * 7.0) for seed in range(8)])
    assert math.dist(found.zones.ring.center, CENTER) < 6.0
    assert found.zones.ring.exit_radius == pytest.approx(RIM, rel=0.03)
    assert found.frames == 8


def test_zones_stay_where_they_were_on_the_band_when_the_center_moves() -> None:
    off_center = (CENTER[0] + 55.0, CENTER[1] + 4.0)
    current = _current(off_center)
    found = findZones(3, [_picture(2)], current)
    ring = found.zones.ring

    def on_band(center: tuple[float, float], radius: float, angle: float) -> tuple[float, float]:
        return (center[0] + radius * math.cos(math.radians(angle)), center[1] + radius * math.sin(math.radians(angle)))

    # The exit's start, where the old center's ray meets the found rim, is the
    # same spot as the new exit start on the rim.
    old_ray = math.radians(current.exit.start)
    dx, dy = math.cos(old_ray), math.sin(old_ray)
    fx, fy = off_center[0] - ring.center[0], off_center[1] - ring.center[1]
    b = fx * dx + fy * dy
    t = -b + math.sqrt(b * b - (fx * fx + fy * fy - ring.exit_radius**2))
    expected = (off_center[0] + t * dx, off_center[1] + t * dy)
    assert math.dist(on_band(ring.center, ring.exit_radius, found.zones.exit.start), expected) < 2.0
    assert found.zones.precise_width == current.precise_width


def test_a_locked_ring_is_kept() -> None:
    current = ChannelZones(
        channel=3,
        frame=(1280, 720),
        ring=Ring((500.0, 300.0), 200.0, 420.0, 330.0),
        drop=Span(288.0, 9.0),
        exit=Span(169.0, 201.0),
        locked=frozenset({"ring"}),
    )
    found = findZones(3, [_picture(3)], current)
    assert found.zones == current
    assert found.notes


def test_zones_come_back_at_the_cameras_size() -> None:
    small = cv2.resize(_picture(4), (640, 360), interpolation=cv2.INTER_AREA)
    found = findZones(3, [small], frame_size=(1280, 720))
    assert found.zones.frame == (1280, 720)
    assert math.dist(found.zones.ring.center, CENTER) < 10.0


def test_the_inner_circle_hugs_the_hub_even_where_it_looks_shifted() -> None:
    # The hub stands above the rotor, so from the camera it sits off the
    # rotor's center: the area starts just outside it, around its own center,
    # while the rim stays on the rotor's edge.
    found = findZones(3, [_picture(seed, turned=seed * 7.0, hub_offset=(28, -18)) for seed in range(6)])
    ring = found.zones.ring
    assert math.dist(ring.center, CENTER) < 4.0
    assert ring.exit_radius == pytest.approx(RIM, rel=0.02)
    assert ring.inner_center is not None
    assert math.dist(ring.inner_center, (CENTER[0] + 28, CENTER[1] - 18)) < 4.0
    assert ring.inner_radius == pytest.approx(60 * 1.04, abs=4.0)


def test_the_classification_channel_keeps_its_own_inner_edge() -> None:
    found = findZones(4, [_picture(seed, turned=seed * 7.0) for seed in range(6)])
    assert found.zones.ring.inner_center is None
