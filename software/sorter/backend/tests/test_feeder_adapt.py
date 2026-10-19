"""The feeder fitting itself to the pieces: C2 leaves room behind the last piece
on C3, the room follows the double feeds, and each exit's hold follows how long
pieces take to land."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from perception.arcs import backGapToExitDeg, forwardGapToExitDeg
from perception.channel import buildChannelDef
from perception.state import ChannelState
from subsystems.feeder.pulse_perception import adapt as adapt_mod
from subsystems.feeder.pulse_perception.adapt import Adapt
from subsystems.feeder.pulse_perception.blind_arc import BlindArc
from subsystems.feeder.pulse_perception.config import PulsePerceptionConfig
from subsystems.feeder.pulse_perception.dispense_gate import DispenseGate
from subsystems.feeder.pulse_perception.flow import PulsePerceptionFeeding

CENTER = (200.0, 200.0)
RADIUS = 150.0
# Pieces travel toward increasing angles: they land at 200-260 and reach the
# precise sliver at 100 and the exit at 110.
EXIT_AT = 110.0
DROP_FRONT = (EXIT_AT - 259.0) % 360.0


def _channel():
    poly = np.array([[0, 0], [400, 0], [400, 400], [0, 400]], dtype=np.float64)
    return buildChannelDef(
        channel_id=3,
        polygon=poly,
        frame_shape=(400, 400),
        section_zero_angle=0.0,
        drop_arc=(200.0, 260.0),
        exit_arc=(110.0, 150.0),
        precise_arc=(100.0, 110.0),
        arc_center=CENTER,
    )


def _box(theta: float, length_deg: float) -> tuple[int, int, int, int]:
    xs, ys = [], []
    for a in np.linspace(theta - length_deg / 2, theta + length_deg / 2, 9):
        xs.append(CENTER[0] + RADIUS * math.cos(math.radians(a)))
        ys.append(CENTER[1] + RADIUS * math.sin(math.radians(a)))
    return (int(min(xs)) - 1, int(min(ys)) - 1, int(max(xs)) + 1, int(max(ys)) + 1)


def _piece(theta: float, length_deg: float = 4.0, track_id: int = 1, zone: int = 0):
    return SimpleNamespace(
        sv_bt_track_id=track_id,
        zone_code=zone,
        bbox=_box(theta, length_deg),
        com_forward_to_exit_deg=(EXIT_AT - theta) % 360.0,
    )


def _state(*pieces):
    return SimpleNamespace(pieces=tuple(pieces))


def _adapt(**kwargs) -> tuple[Adapt, list[dict]]:
    saved: list[dict] = []
    kwargs.setdefault("load", lambda: None)
    kwargs.setdefault("cycles", lambda since: [])
    kwargs.setdefault("landing_delays", lambda channel: [])
    return Adapt(save=saved.append, **kwargs), saved


def _cycles(close: int, close_doubled: int, far: int, far_doubled: int) -> list[dict]:
    rows = []
    for i in range(close):
        rows.append({"landed_at": 1.0, "c3_head_deg": 5.0, "c3_next_deg": 15.0, "multi_drop": int(i < close_doubled)})
    for i in range(far):
        rows.append({"landed_at": 1.0, "c3_head_deg": 5.0, "c3_next_deg": 90.0, "multi_drop": int(i < far_doubled)})
    return rows


def test_a_piece_back_is_its_front_plus_its_length() -> None:
    ch = _channel()
    box = _box(290.0, 20.0)
    assert forwardGapToExitDeg(box, ch) == pytest.approx((EXIT_AT - 300.0) % 360.0, abs=2.0)
    assert backGapToExitDeg(box, ch) == pytest.approx((EXIT_AT - 280.0) % 360.0, abs=2.0)


def test_c2_waits_until_the_last_piece_is_clear_of_where_pieces_land() -> None:
    ch = _channel()
    adapt, _ = _adapt()
    adapt.observe(_state(), ch, 0.0)
    # Just past the landing zone, its back still within the room of its front.
    assert not adapt.roomClear(_state(_piece(265.0)), ch, 12.0)
    # Far enough on.
    assert adapt.roomClear(_state(_piece(290.0)), ch, 12.0)


def test_a_long_piece_takes_more_room() -> None:
    ch = _channel()
    adapt, _ = _adapt()
    adapt.observe(_state(), ch, 0.0)
    assert adapt.roomClear(_state(_piece(285.0, length_deg=4.0)), ch, 12.0)
    assert not adapt.roomClear(_state(_piece(285.0, length_deg=40.0)), ch, 12.0)


def test_pieces_in_the_landing_zone_and_a_room_of_nothing_never_hold_c2() -> None:
    ch = _channel()
    adapt, _ = _adapt()
    adapt.observe(_state(), ch, 0.0)
    # The landing zone's own gate holds C2 for a piece still in it.
    assert adapt.roomClear(_state(_piece(250.0, zone=1)), ch, 12.0)
    assert adapt.roomClear(_state(_piece(265.0)), ch, 0.0)


def test_where_pieces_land_is_measured() -> None:
    ch = _channel()
    adapt, _ = _adapt()
    adapt.observe(_state(), ch, 0.0)
    room = adapt.report()["room"]
    assert room["landing_front_deg"] == pytest.approx(DROP_FRONT, abs=1.0)
    assert not room["landing_front_measured"]
    for i in range(adapt_mod.LANDINGS_NEEDED):
        adapt.observe(_state(_piece(230.0, track_id=100 + i, zone=1)), ch, float(i))
    room = adapt.report()["room"]
    assert room["landing_front_measured"]
    assert room["landing_front_deg"] == pytest.approx((EXIT_AT - 232.0) % 360.0, abs=2.0)
    # The same piece seen again is not another landing.
    adapt.observe(_state(_piece(230.0, track_id=100, zone=1)), ch, 20.0)
    assert adapt.report()["room"]["landings"] == adapt_mod.LANDINGS_NEEDED


def test_the_room_grows_while_close_pieces_double() -> None:
    adapt, saved = _adapt(cycles=lambda since: _cycles(close=10, close_doubled=4, far=30, far_doubled=1))
    assert adapt.margin(12.0) == 12.0
    adapt.tune(now=1000.0, mono=100.0)
    assert adapt.margin(12.0) == 12.0 + adapt_mod.MARGIN_UP_DEG
    assert saved and saved[-1]["margin_deg"] == 14.0
    assert "close behind another doubled" in adapt.report()["room"]["why"]


def test_the_room_waits_for_enough_hand_offs_and_moves_at_most_once_a_minute() -> None:
    adapt, _ = _adapt(cycles=lambda since: _cycles(close=5, close_doubled=4, far=10, far_doubled=0))
    adapt.margin(12.0)
    adapt.tune(now=1000.0, mono=100.0)
    assert adapt.margin(12.0) == 12.0
    adapt._cycles = lambda since: _cycles(close=10, close_doubled=4, far=30, far_doubled=1)
    adapt.tune(now=1010.0, mono=110.0)
    assert adapt.margin(12.0) == 12.0
    adapt.tune(now=1070.0, mono=170.0)
    assert adapt.margin(12.0) == 14.0


def test_the_room_eases_back_when_it_only_keeps_c2_waiting() -> None:
    adapt, _ = _adapt(load=lambda: {"margin_deg": 20.0}, cycles=lambda since: _cycles(0, 0, far=40, far_doubled=1))
    adapt.margin(12.0)
    for i in range(10):
        adapt.noteWait(ready=True, held=i % 2 == 0, now=float(i))
    adapt.tune(now=1000.0, mono=100.0)
    assert adapt.margin(12.0) == 20.0 - adapt_mod.MARGIN_DOWN_DEG


def test_the_room_stays_put_when_c2_is_not_kept_waiting() -> None:
    adapt, _ = _adapt(load=lambda: {"margin_deg": 20.0}, cycles=lambda since: _cycles(0, 0, far=40, far_doubled=1))
    adapt.margin(12.0)
    for i in range(10):
        adapt.noteWait(ready=True, held=False, now=float(i))
    adapt.tune(now=1000.0, mono=100.0)
    assert adapt.margin(12.0) == 20.0


def test_the_room_keeps_within_its_floor_and_its_most() -> None:
    adapt, _ = _adapt(load=lambda: {"margin_deg": 5.0})
    assert adapt.margin(12.0) == 12.0
    adapt, _ = _adapt(
        load=lambda: {"margin_deg": adapt_mod.MARGIN_MAX_DEG},
        cycles=lambda since: _cycles(close=10, close_doubled=5, far=30, far_doubled=0),
    )
    adapt.margin(12.0)
    adapt.tune(now=1000.0, mono=100.0)
    assert adapt.margin(12.0) == adapt_mod.MARGIN_MAX_DEG


@pytest.mark.parametrize(
    ("delays", "hold"),
    [
        ([0.3] * 10 + [0.5] * 10, 0.8),
        ([1.6] * 20, 1.9),
        ([0.4] * 20 + [3.5] * 10, 0.7),
        ([0.05] * 20, adapt_mod.HOLD_MIN_S),
        ([2.9] * 20, adapt_mod.HOLD_MAX_S),
    ],
)
def test_the_hold_follows_how_long_pieces_take_to_land(delays: list[float], hold: float) -> None:
    adapt, _ = _adapt(landing_delays=lambda channel: delays)
    assert adapt.holdS(3, 1.5, True, 0.0) == pytest.approx(hold)
    assert adapt.report()["hold"]["3"]["measured"]


def test_the_configured_hold_stands_until_enough_pieces_have_landed_or_when_off() -> None:
    adapt, _ = _adapt(landing_delays=lambda channel: [0.4] * 5)
    assert adapt.holdS(2, 1.5, True, 0.0) == 1.5
    adapt, _ = _adapt(landing_delays=lambda channel: [0.4] * 30)
    assert adapt.holdS(2, 1.5, False, 0.0) == 1.5


def _feeder(c2, c3) -> tuple[PulsePerceptionFeeding, list[int]]:
    feeder = PulsePerceptionFeeding.__new__(PulsePerceptionFeeding)
    moved: list[int] = []
    channel = _channel()
    perception = SimpleNamespace(read_states=lambda: {2: c2, 3: c3}, channels=lambda: {3: channel})
    feeder.gc = SimpleNamespace(perception_service=perception, logger=SimpleNamespace(debug=lambda *a: None))
    feeder.shared = SimpleNamespace(feeder_hidden_pieces={}, classification_ready=True)
    feeder.irl = SimpleNamespace(c_channel_2_rotor_stepper=SimpleNamespace(_name="c2"))
    feeder._config = PulsePerceptionConfig(enable_ch1=False, enable_ch3=False, c3_room_adapts=False)
    feeder._config_loaded_at = float("inf")
    feeder._gates = {2: DispenseGate(), 3: DispenseGate()}
    feeder._odometer = {1: 0.0, 2: 0.0, 3: 0.0}
    feeder._blind = {2: BlindArc(), 3: BlindArc()}
    feeder._held = SimpleNamespace(check=lambda *a: None)
    feeder._drop_seen_at = {}
    feeder._busy = lambda stepper: False
    feeder._move = lambda label, channel, stepper, deg, pause, cfg, enforce_min=True: moved.append(channel) or True
    return feeder, moved


@pytest.fixture
def fresh_adapt(monkeypatch):
    fresh, _ = _adapt()
    monkeypatch.setattr(adapt_mod, "_adapt", fresh)
    return fresh


def test_c2_holds_its_exit_piece_until_c3_has_room(fresh_adapt) -> None:
    lead = SimpleNamespace(sv_bt_track_id=7, zone_code=2, bbox=(0, 0, 1, 1), com_forward_to_exit_deg=-1.0)
    c2 = ChannelState(ts=1.0, in_drop=False, in_exit=True, n_pieces=1, pieces=(lead,))
    close = ChannelState(ts=1.0, in_drop=False, in_exit=False, n_pieces=1, pieces=(_piece(265.0),))
    feeder, moved = _feeder(c2, close)
    feeder.step()
    assert moved == []
    clear = ChannelState(ts=1.0, in_drop=False, in_exit=False, n_pieces=1, pieces=(_piece(290.0),))
    feeder, moved = _feeder(c2, clear)
    feeder.step()
    assert moved == [2]
