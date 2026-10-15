"""The C2/C3 crop collector keeps a track's last sightings: frames its cadence
skipped are held, and stored once the track is gone, because the picture right
before a piece leaves a channel is the one that ties it to the next channel."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

import channel_crop_store
from perception import channel_crop_capture
from perception.channel_crop_capture import ChannelCropCollector


class _Service:
    def __init__(self) -> None:
        self.result = None

    def read_pieces_and_frame(self, _channel: int):
        return self.result


def _collector(monkeypatch) -> tuple[ChannelCropCollector, _Service, list[dict], list[float]]:
    stored: list[dict] = []
    monkeypatch.setattr(channel_crop_store, "enqueue", lambda _jpeg, meta: stored.append(meta))
    clock = [100.0]
    # The collector's own reference to time, not the time module other threads use.
    monkeypatch.setattr(channel_crop_capture, "time", SimpleNamespace(time=lambda: clock[0]))
    service = _Service()
    return ChannelCropCollector(perception_service=service), service, stored, clock


def _frame(collector, service, clock, channel: int, ts: float, *pieces) -> None:
    clock[0] = ts
    frame = SimpleNamespace(timestamp=ts, bgr=np.full((120, 160, 3), 90, np.uint8))
    service.result = (list(pieces), frame)
    collector._collectChannel(channel, collector._cfg)


def _piece(track: int, deg: float, zone: int = 0):
    return SimpleNamespace(sv_bt_track_id=track, com_forward_to_exit_deg=deg, zone_code=zone,
                           com_section=10, bbox=(20, 20, 60, 50))


def test_a_track_stores_its_last_two_sightings_once_it_is_gone(monkeypatch) -> None:
    collector, service, stored, clock = _collector(monkeypatch)
    # Mid-channel on C3 the cadence wants 18 degrees between crops: only the first is taken.
    for i, deg in enumerate((30.0, 29.0, 28.0, 27.0)):
        _frame(collector, service, clock, 3, 1000.0 + i / 10, _piece(5, deg))
    assert [m["ts"] for m in stored] == [1000.0]

    collector._storeLastSightings(clock[0] + 0.1, collector._cfg)
    assert len(stored) == 1  # not gone long enough
    collector._storeLastSightings(clock[0] + 0.5, collector._cfg)
    assert [m["ts"] for m in stored] == [1000.0, 1000.2, 1000.3]
    assert stored[-1]["track_id"] == 5 and stored[-1]["sharpness"] is not None
    collector._storeLastSightings(clock[0] + 1.0, collector._cfg)
    assert len(stored) == 3  # stored once


def test_a_sighting_the_cadence_took_is_not_stored_again(monkeypatch) -> None:
    collector, service, stored, clock = _collector(monkeypatch)
    # Near the C3 exit the cadence takes a crop every 3 degrees.
    for i, deg in enumerate((12.0, 8.0, 4.0)):
        _frame(collector, service, clock, 3, 2000.0 + i / 10, _piece(9, deg, zone=2))
    collector._storeLastSightings(clock[0] + 1.0, collector._cfg)
    assert [m["ts"] for m in stored] == [2000.0, 2000.1, 2000.2]


def test_c2_takes_a_crop_every_ten_degrees(monkeypatch) -> None:
    collector, service, stored, clock = _collector(monkeypatch)
    for i in range(12):
        _frame(collector, service, clock, 2, 3000.0 + i / 10, _piece(4, 200.0 - 5.0 * i))
    assert [round(200.0 - m["com_forward_to_exit_deg"]) for m in stored] == [0, 10, 20, 30, 40, 50]
