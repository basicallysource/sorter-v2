import unittest

from perception.state import ChannelState, PieceObservation
from subsystems.feeder.pulse_perception.dispense_gate import DispenseGate


def _piece(track_id: int | None, gap: float = 0.0) -> PieceObservation:
    return PieceObservation(
        com_forward_to_exit_deg=gap, com_section=0, zone_code=3, sv_bt_track_id=track_id
    )


def _state(*pieces: PieceObservation, in_exit: bool | None = None) -> ChannelState:
    return ChannelState(
        ts=1.0,
        in_drop=False,
        in_exit=bool(pieces) if in_exit is None else in_exit,
        n_pieces=len(pieces),
        pieces=tuple(pieces),
    )


class DispenseGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = DispenseGate(vanish_confirm_s=0.15, arrival_timeout_s=1.5)

    def test_a_blink_is_not_a_fall(self) -> None:
        self.gate.notePush(_piece(7))
        self.assertFalse(self.gate.observe(_state(), 10.0, downstream_arrived=False))
        # While the pushed piece is unseen, nothing more is pushed off.
        self.assertFalse(self.gate.exitAllowed())
        self.assertFalse(self.gate.observe(_state(_piece(7)), 10.1, downstream_arrived=False))
        self.assertTrue(self.gate.exitAllowed())

    def test_the_exit_holds_after_a_fall_until_the_next_channel_sees_it(self) -> None:
        self.gate.notePush(_piece(7))
        self.gate.observe(_state(_piece(8, gap=12.0)), 10.0, downstream_arrived=False)
        fell = self.gate.observe(_state(_piece(8, gap=12.0)), 10.2, downstream_arrived=False)
        self.assertTrue(fell)
        self.assertFalse(self.gate.exitAllowed())
        # Reported once.
        self.assertFalse(self.gate.observe(_state(_piece(8)), 10.3, downstream_arrived=False))
        self.assertFalse(self.gate.exitAllowed())
        self.gate.observe(_state(_piece(8)), 10.5, downstream_arrived=True)
        self.assertTrue(self.gate.exitAllowed())

    def test_the_exit_reopens_after_the_timeout_if_the_piece_is_never_seen(self) -> None:
        self.gate.notePush(_piece(7))
        self.gate.observe(_state(), 10.0, downstream_arrived=False)
        self.assertTrue(self.gate.observe(_state(), 10.2, downstream_arrived=False))
        self.gate.observe(_state(), 11.0, downstream_arrived=False)
        self.assertFalse(self.gate.exitAllowed())
        self.gate.observe(_state(), 11.7, downstream_arrived=False)
        self.assertTrue(self.gate.exitAllowed())

    def test_an_untracked_lead_falls_when_the_exit_empties(self) -> None:
        self.gate.notePush(_piece(None))
        self.assertFalse(self.gate.observe(_state(_piece(None)), 10.0, downstream_arrived=False))
        self.assertTrue(self.gate.observe(_state(in_exit=False), 10.1, downstream_arrived=False))
        self.assertFalse(self.gate.exitAllowed())

    def test_nothing_pushed_means_nothing_held(self) -> None:
        self.assertFalse(self.gate.observe(_state(), 10.0, downstream_arrived=False))
        self.assertTrue(self.gate.exitAllowed())


if __name__ == "__main__":
    unittest.main()
