from subsystems.feeder.pulse_perception.flow import ExitDepartureDetector


def _feed(d, seq, dt=0.1, t0=0.0):
    out = []
    for i, c in enumerate(seq):
        out.append(d.observe(c, now=t0 + i * dt))
    return out


def test_flicker_between_3_and_4_never_reports_a_departure() -> None:
    d = ExitDepartureDetector(hold_s=0.8)
    seq = [4, 3, 4, 3, 3, 4, 3, 3, 3, 4, 4, 3, 4, 3, 3, 4] * 3
    assert not any(_feed(d, seq))


def test_a_sustained_drop_reports_once() -> None:
    d = ExitDepartureDetector(hold_s=0.8)
    seq = [4] * 10 + [3] * 20
    res = _feed(d, seq)
    assert sum(res) == 1
    # fires once the old maximum has aged out of the window (~0.8 s)
    assert res.index(True) >= 10 + 8


def test_two_departures_far_apart_both_report_and_increases_never_do() -> None:
    d = ExitDepartureDetector(hold_s=0.8, min_interval_s=1.0)
    seq = [3] * 10 + [2] * 20 + [5] * 10 + [4] * 20
    res = _feed(d, seq)
    assert sum(res) == 2
