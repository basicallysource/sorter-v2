from subsystems.feeder.pulse_perception.flow import ExitDepartureDetector


def test_confirmed_decrease_reports_a_departure_once() -> None:
    d = ExitDepartureDetector()
    assert d.observe(3) is False
    assert d.observe(3) is False
    assert d.observe(2) is False   # first sighting: wait for confirmation
    assert d.observe(2) is True    # confirmed: one piece left
    assert d.observe(2) is False
    assert d.observe(1) is False
    assert d.observe(1) is True


def test_one_frame_dropout_is_ignored_and_increases_never_fire() -> None:
    d = ExitDepartureDetector()
    d.observe(2); d.observe(2)
    assert d.observe(1) is False
    assert d.observe(2) is False   # back to the stable value: dropout
    assert d.observe(3) is False
    assert d.observe(3) is False   # increase confirmed, not a departure
    assert d.observe(0) is False
    assert d.observe(0) is True
