"""A piece's trip through the classification channel is written as one row, and
the summary splits its seconds into C4's phases and the wait for the feeder."""

from types import SimpleNamespace

import db
import piece_cycles


def _c3(*gaps):
    return SimpleNamespace(pieces=[SimpleNamespace(com_forward_to_exit_deg=g) for g in gaps])


def test_cycle_is_written_and_summarized(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_STATE_DB_PATH", str(tmp_path / "state.sqlite"))
    rec = piece_cycles.CycleRecorder()
    t = 1000.0
    for head, wait in ((12.0, 1.0), (150.0, 5.0)):
        rec.asked(t, _c3(head, head + 60), _c3())
        rec.tick(t + wait / 2, c3_moving=True, c2_moving=False, chute_moving=False)
        rec.landed(t + wait)
        # A flicker in the drop zone that is never photographed does not end the wait.
        if head > 100:
            rec.asked(t + wait + 0.1, _c3(head), _c3())
            assert rec.waiting
            rec.landed(t + wait + 0.2)
            wait += 0.2
        rec.confirmed(t + wait + 0.1, 7, "u")
        rec.captured(t + wait + 0.5, 7)
        rec.rotated(t + wait + 1.0, ejecting=True)
        rec.ejected(t + wait + 2.5)
        rec.staged(t + wait + 3.0)
        t += wait + 3.0
    assert db.drain(5.0)
    out = piece_cycles.summary(0.0, 1e12)
    assert out["pieces"] == 2
    assert abs(out["c4"]["total"]["median"] - 3.0) < 1e-6
    cases = {c["key"]: c for c in out["wait_cases"]}
    assert cases["edge"]["n"] == 1 and abs(cases["edge"]["median"] - 1.0) < 1e-6
    assert cases["far"]["n"] == 1 and abs(cases["far"]["median"] - 5.2) < 1e-6


def test_a_cycle_the_machine_stopped_in_is_counted_apart(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_STATE_DB_PATH", str(tmp_path / "state.sqlite"))
    rec = piece_cycles.CycleRecorder()
    rec.step(0.0, held=False)
    rec.asked(0.0, _c3(10.0), _c3())
    rec.step(0.1, held=False)
    rec.step(5.0, held=False)  # the control loop did not step the channel for 4.9 s
    rec.landed(5.0)
    rec.confirmed(5.1, 1, "u")
    rec.captured(5.5, 1)
    rec.rotated(6.0, ejecting=False)
    rec.staged(8.0)
    assert db.drain(5.0)
    out = piece_cycles.summary(-1.0, 1e12)
    assert out["pieces"] == 0 and out["held"] == 1
