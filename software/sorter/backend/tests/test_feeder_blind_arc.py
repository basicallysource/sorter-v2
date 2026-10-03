from perception.state import ChannelState, PieceObservation
from subsystems.feeder.pulse_perception.blind_arc import VANISH_S, BlindArc


def _state(*pieces: tuple[int, float]) -> ChannelState:
    obs = tuple(
        PieceObservation(com_forward_to_exit_deg=0.0, com_section=int(s), zone_code=0, sv_bt_track_id=t)
        for t, s in pieces
    )
    return ChannelState(ts=1.0, in_drop=False, in_exit=False, n_pieces=len(obs), pieces=obs)


def _arc() -> BlindArc:
    return BlindArc(start_deg=45.0, end_deg=135.0)


def test_a_piece_that_goes_out_of_view_is_expected_and_moves_with_the_channel() -> None:
    arc = _arc()
    arc.update(_state((7, 44)), 10.0, odometer=100.0)
    arc.update(_state(), 10.0 + VANISH_S + 0.1, odometer=100.0)
    assert arc.expected(100.0) == [44.0]
    assert arc.expected(130.0) == [74.0]


def test_a_piece_coming_back_into_view_accounts_for_it() -> None:
    arc = _arc()
    arc.update(_state((7, 44)), 10.0, odometer=0.0)
    arc.update(_state(), 11.0, odometer=0.0)
    arc.update(_state((9, 132)), 12.0, odometer=88.0)
    assert arc.expected(88.0) == []


def test_a_piece_that_never_comes_back_is_given_up() -> None:
    arc = _arc()
    arc.update(_state((7, 44)), 10.0, odometer=0.0)
    arc.update(_state(), 11.0, odometer=0.0)
    arc.update(_state(), 12.0, odometer=80.0)
    assert arc.expected(80.0) == [124.0]
    # 15 deg past the arc's end it would be in view: not seeing it, give it up.
    arc.update(_state(), 13.0, odometer=110.0)
    assert arc.expected(110.0) == []


def test_a_piece_leaving_elsewhere_is_not_expected() -> None:
    arc = _arc()
    arc.update(_state((7, 170)), 10.0, odometer=0.0)
    arc.update(_state(), 11.0, odometer=0.0)
    assert arc.expected(0.0) == []


def test_without_an_arc_nothing_is_tracked() -> None:
    arc = BlindArc()
    arc.update(_state((7, 44)), 10.0, odometer=0.0)
    arc.update(_state(), 11.0, odometer=0.0)
    assert arc.expected(0.0) == []
