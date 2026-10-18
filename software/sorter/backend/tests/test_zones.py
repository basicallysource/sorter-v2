from __future__ import annotations

import math
from dataclasses import replace

import cv2
import numpy as np
import pytest

from perception.channel import channelDefFor
from zones import store
from zones.model import (
    ChannelZones,
    Ring,
    Span,
    channelPolygon,
    fromDict,
    fromLegacyBlob,
    sectionsFor,
    toDict,
    toLegacyBlob,
)

OLD_EDITOR_BLOB = {
    "resolution": [1280, 720],
    "channel_angles": {"second": 0, "third": 0, "classification_channel": 0},
    "arc_params": {
        "third": {
            "center": [629, 335],
            "inner_radius": 294,
            "outer_radius": 669,
            "exit_outer_radius": 519,
            "resolution": [1280, 720],
            "drop_zone": {"start_outer_angle": 288.0436, "end_outer_angle": 9.0718, "end_inner_angle": 30.0},
            "exit_zone": {"start_outer_angle": 169.383, "end_outer_angle": 201.289, "end_inner_angle": 197.3},
            "precise_zone": {"start_outer_angle": 163.637, "end_outer_angle": 169.383},
        },
        "classification_channel": {
            "center": [1893, 998],
            "inner_radius": 748,
            "outer_radius": 1552,
            "exit_outer_radius": 1019,
            "resolution": [3840, 2160],
            "drop_zone": {"start_angle": 281.86, "end_angle": 118.62},
            "exit_zone": {"start_angle": 232.64, "end_angle": 274.09},
            "precise_zone": {"start_angle": 147.16, "end_angle": 232.64},
        },
    },
}


def _zones(**changes) -> ChannelZones:
    zones = ChannelZones(
        channel=3,
        frame=(400, 400),
        ring=Ring((200.0, 200.0), 100.0, 180.0, 150.0),
        drop=Span(300.0, 20.0),
        exit=Span(170.0, 210.0),
        precise_width=6.0,
    )
    return replace(zones, **changes)


# --- spans ------------------------------------------------------------------


def test_a_span_runs_forward_and_wraps() -> None:
    span = Span(350.0, 10.0)
    assert span.width == pytest.approx(20.0)
    assert span.middle == pytest.approx(0.0)
    assert span.contains(355.0) and span.contains(5.0)
    assert not span.contains(20.0) and not span.contains(340.0)


def test_widening_a_span_keeps_its_middle() -> None:
    wider = Span(170.0, 210.0).widened(10.0)
    assert (wider.start, wider.end) == pytest.approx((165.0, 215.0))
    assert Span(170.0, 210.0).moved(-180.0).start == pytest.approx(350.0)


def test_the_precise_sliver_ends_where_the_exit_starts() -> None:
    precise = _zones().precise
    assert precise is not None
    assert (precise.start, precise.end) == pytest.approx((164.0, 170.0))
    assert _zones(precise_width=0.0).precise is None


def test_sections_start_inclusive_and_end_exclusive() -> None:
    assert sectionsFor(Span(10.5, 20.3), 0.0) == frozenset(range(10, 20))
    assert sectionsFor(Span(355.0, 5.0), 0.0) == frozenset(range(355, 360)) | frozenset(range(0, 5))
    assert sectionsFor(Span(100.0, 110.0), 90.0) == frozenset(range(10, 20))


# --- the channel's area -----------------------------------------------------


def _mask(zones: ChannelZones) -> np.ndarray:
    mask = np.zeros((zones.frame[1], zones.frame[0]), np.uint8)
    cv2.fillPoly(mask, [np.round(np.asarray(channelPolygon(zones))).astype(np.int32)], 255)
    return mask


def _at(zones: ChannelZones, angle: float, radius: float) -> tuple[int, int]:
    cx, cy = zones.ring.center
    return (
        int(round(cx + radius * math.cos(math.radians(angle)))),
        int(round(cy + radius * math.sin(math.radians(angle)))),
    )


def test_the_channel_is_the_ring_from_the_drop_to_the_exit_cut_at_the_exit() -> None:
    zones = _zones()
    mask = _mask(zones)

    def inside(angle: float, radius: float) -> bool:
        x, y = _at(zones, angle, radius)
        return bool(mask[y, x])

    assert inside(310.0, 165.0)  # the drop, out near the outer edge
    assert inside(90.0, 120.0)  # on the way round
    assert inside(190.0, 140.0)  # the exit, inside its radius
    assert not inside(190.0, 165.0)  # past the rim at the exit: the next channel
    assert inside(160.0, 165.0)  # just before the exit, full width
    assert not inside(250.0, 140.0)  # between the exit and the drop: nothing rides
    assert not inside(90.0, 60.0)  # the hub


# --- saving -----------------------------------------------------------------


def test_zones_read_from_the_old_editors_blob() -> None:
    zones = fromLegacyBlob(OLD_EDITOR_BLOB)
    assert sorted(zones) == [3, 4]
    c3 = zones[3]
    assert c3.frame == (1280, 720)
    assert c3.ring.center == (629.0, 335.0)
    assert c3.ring.exit_radius == pytest.approx(519.0)
    assert (c3.drop.start, c3.drop.end) == pytest.approx((288.0436, 9.0718))
    assert c3.precise_width == pytest.approx(169.383 - 163.637)
    c4 = zones[4]
    assert c4.frame == (3840, 2160)
    assert (c4.exit.start, c4.exit.end) == pytest.approx((232.64, 274.09))
    assert c4.precise_width == pytest.approx(232.64 - 147.16)


def test_zones_survive_the_old_blob_and_the_new_document() -> None:
    zones = fromLegacyBlob(OLD_EDITOR_BLOB)
    again = fromLegacyBlob(toLegacyBlob(zones))
    for channel, original in zones.items():
        assert toDict(replace(again[channel], source={})) == toDict(replace(original, source={}))
        assert toDict(fromDict(toDict(original))) == toDict(original)


def test_saving_writes_the_document_and_the_old_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_STATE_DB_PATH", str(tmp_path / "local_state.sqlite"))
    import local_state

    local_state.set_channel_zones_blob(OLD_EDITOR_BLOB)
    assert sorted(store.loadZones()) == [3, 4]

    heard: list[int] = []
    unsubscribe = store.subscribe(lambda: heard.append(1))
    try:
        saved = store.saveChannel(_zones(channel=2, locked=frozenset({"ring"})))
    finally:
        unsubscribe()
    assert sorted(saved) == [2, 3, 4] and heard == [1]
    blob = local_state.get_channel_zones_blob()
    assert blob["zones"]["version"] == store.DOCUMENT_VERSION
    assert set(blob["arc_params"]) == {"second", "third", "classification_channel"}
    loaded = store.loadChannel(2)
    assert loaded is not None and loaded.locked == frozenset({"ring"}) and loaded.updated_at is not None

    assert store.updateChannel(2, lambda z: None) == loaded
    moved = store.updateChannel(2, lambda z: replace(z, exit=z.exit.moved(5.0)))
    assert moved is not None and moved.exit.start == pytest.approx(175.0)


# --- perception ---------------------------------------------------------------


def test_perception_takes_the_zones_at_the_live_frames_size() -> None:
    zones = _zones()
    channel = channelDefFor(zones, (800, 800))
    assert channel.center == pytest.approx((400.0, 400.0))
    assert channel.mask.shape == (800, 800)
    assert channel.drop_sections == sectionsFor(zones.drop, 0.0)
    assert channel.precise_sections == frozenset(range(164, 170))
    assert channel.exit_sections == frozenset(range(164, 210))
    assert channelDefFor(_zones(precise_width=0.0), (400, 400)).precise_sections == frozenset()
