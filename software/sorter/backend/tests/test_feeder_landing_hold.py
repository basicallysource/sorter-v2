"""Each exit's hold after a piece falls follows how long pieces take to land."""

from __future__ import annotations

import pytest

from subsystems.feeder.pulse_perception import landing_hold
from subsystems.feeder.pulse_perception.landing_hold import LandingHold


@pytest.mark.parametrize(
    ("delays", "hold"),
    [
        ([0.3] * 10 + [0.5] * 10, 0.8),
        ([1.6] * 20, 1.9),
        ([0.4] * 20 + [3.5] * 10, 0.7),
        ([0.05] * 20, landing_hold.HOLD_MIN_S),
        ([2.9] * 20, landing_hold.HOLD_MAX_S),
    ],
)
def test_the_hold_follows_how_long_pieces_take_to_land(delays: list[float], hold: float) -> None:
    holds = LandingHold(landing_delays=lambda channel: delays)
    assert holds.holdS(3, 1.5, True, 0.0) == pytest.approx(hold)
    assert holds.report()["hold"]["3"]["measured"]


def test_the_configured_hold_stands_until_enough_pieces_have_landed_or_when_off() -> None:
    assert LandingHold(landing_delays=lambda channel: [0.4] * 5).holdS(2, 1.5, True, 0.0) == 1.5
    assert LandingHold(landing_delays=lambda channel: [0.4] * 30).holdS(2, 1.5, False, 0.0) == 1.5


def test_the_hold_is_worked_out_again_only_every_few_seconds() -> None:
    delays = [0.4] * 20
    holds = LandingHold(landing_delays=lambda channel: delays)
    assert holds.holdS(2, 1.5, True, 0.0) == pytest.approx(0.7)
    delays[:] = [1.0] * 20
    assert holds.holdS(2, 1.5, True, landing_hold.HOLD_EVERY_S / 2) == pytest.approx(0.7)
    assert holds.holdS(2, 1.5, True, landing_hold.HOLD_EVERY_S) == pytest.approx(1.3)
