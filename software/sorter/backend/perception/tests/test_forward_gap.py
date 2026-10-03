"""How far a channel can turn before a piece reaches the exit, and the exit
move the feeder sizes from it."""

from types import SimpleNamespace

from perception.arcs import forwardGapToExitDeg
from perception.state import ChannelState, PieceObservation
from perception.tests.test_arcs import _bbox_at_angle, _channel
from subsystems.feeder.pulse_perception.config import PulsePerceptionConfig
from subsystems.feeder.pulse_perception.flow import PulsePerceptionFeeding


def _ch():
    # precise 240-255, exit 255-285: the exit-only entry is at 255.
    return _channel(precise_arc=(240.0, 255.0))


def test_gap_is_measured_from_the_front_of_the_box() -> None:
    gap = forwardGapToExitDeg(_bbox_at_angle(200.0), _ch())
    # The box's front edge is a few degrees ahead of its center at 200.
    assert 45.0 < gap < 55.0


def test_a_piece_already_over_the_exit_has_no_room() -> None:
    assert forwardGapToExitDeg(_bbox_at_angle(260.0), _ch()) == 0.0


def _piece(angle: float, track_id: int) -> PieceObservation:
    return PieceObservation(
        com_forward_to_exit_deg=255.0 - angle,
        com_section=int(angle),
        zone_code=3,
        bbox=_bbox_at_angle(angle),
        sv_bt_track_id=track_id,
    )


def _feeder(channel_def) -> PulsePerceptionFeeding:
    f = PulsePerceptionFeeding.__new__(PulsePerceptionFeeding)
    f.gc = SimpleNamespace(perception_service=SimpleNamespace(channels=lambda: {3: channel_def}))
    return f


def _state(*pieces: PieceObservation) -> ChannelState:
    return ChannelState(ts=1.0, in_drop=False, in_exit=True, n_pieces=len(pieces), pieces=pieces)


def test_alone_at_the_exit_the_lead_goes_in_one_long_move() -> None:
    cfg = PulsePerceptionConfig()
    move = _feeder(_ch())._exitMoveDeg(3, _state(_piece(250.0, 1)), cfg)
    assert move == cfg.exit_move_max_deg


def test_a_piece_close_behind_keeps_it_to_the_small_pulse() -> None:
    cfg = PulsePerceptionConfig()
    move = _feeder(_ch())._exitMoveDeg(3, _state(_piece(253.0, 1), _piece(248.0, 2)), cfg)
    assert move == cfg.exit_pulse_output_deg


def test_a_piece_further_back_limits_the_move_to_its_room() -> None:
    cfg = PulsePerceptionConfig()
    ch = _ch()
    behind = _piece(238.0, 2)
    room = forwardGapToExitDeg(behind.bbox, ch)
    move = _feeder(ch)._exitMoveDeg(3, _state(_piece(250.0, 1), behind), cfg)
    assert move == min(cfg.exit_move_max_deg, room - cfg.exit_move_margin_deg)
    assert cfg.exit_pulse_output_deg < move <= cfg.exit_move_max_deg
