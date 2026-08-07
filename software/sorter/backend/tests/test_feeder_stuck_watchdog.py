import unittest

from subsystems.feeder.pulse_perception.config import PulsePerceptionConfig
from subsystems.feeder.pulse_perception.stuck_watchdog import FeederStuckWatchdog
from subsystems.feeder.incidents import FEEDER_JAM_INCIDENT_KIND


class _FakeRuntimeStats:
    def __init__(self) -> None:
        self._active = None
        self.auto_resolved: list[dict] = []

    def setActiveIncident(self, incident: dict) -> None:
        self._active = dict(incident)

    def activeIncident(self):
        return dict(self._active) if self._active else None

    def clearActiveIncident(self, *, kind=None, piece_uuid=None, resolved_by="system") -> None:
        if self._active is None:
            return
        if kind is not None and self._active.get("kind") != kind:
            return
        self._active = None

    def recordAutoResolvedIncident(self, incident: dict, *, resolved_by="auto") -> None:
        self.auto_resolved.append({**incident, "resolved_by": resolved_by})


class _FakeLogger:
    def info(self, *_a, **_k) -> None:
        pass

    def warning(self, *_a, **_k) -> None:
        pass


class _FakeGC:
    def __init__(self) -> None:
        self.runtime_stats = _FakeRuntimeStats()
        self.logger = _FakeLogger()


class _FakeStepper:
    def __init__(self) -> None:
        self.moves: list[float] = []
        self.enabled = False

    def set_speed_limits(self, _lo, _hi) -> None:
        pass

    def move_degrees(self, deg: float) -> bool:
        self.moves.append(float(deg))
        return True


def _cfg() -> PulsePerceptionConfig:
    cfg = PulsePerceptionConfig()
    cfg.stuck_watchdog_enabled = True
    cfg.stuck_no_progress_ms = 1000
    cfg.stuck_progress_epsilon_deg = 3.0
    cfg.stuck_nudge_output_deg = 4.0
    cfg.stuck_max_nudge_attempts = 3
    return cfg


class FeederStuckWatchdogTests(unittest.TestCase):
    def _observe(self, wd, gc, up, cfg, *, pos, wants, now):
        wd.observe(
            channel_id=2,
            channel_label="C2",
            upstream_label="C1",
            upstream_stepper=up,
            upstream_enabled=True,
            leading_pos_deg=pos,
            wants_advance=wants,
            cfg=cfg,
            now=now,
        )

    def test_nudges_upstream_then_escalates_to_jam(self) -> None:
        gc = _FakeGC()
        up = _FakeStepper()
        wd = FeederStuckWatchdog(gc)
        cfg = _cfg()

        # Piece parked at the same position while the channel keeps wanting to
        # advance it: three nudges, then a jam incident.
        self._observe(wd, gc, up, cfg, pos=40.0, wants=True, now=0.0)
        for i in range(3):
            # Cross the no-progress window each round; each should nudge once.
            self._observe(wd, gc, up, cfg, pos=40.0, wants=True, now=(i + 1) * 2.0)
            self.assertEqual(len(up.moves), i + 1, f"expected {i + 1} nudges")
            self.assertIsNone(gc.runtime_stats.activeIncident())

        # Fourth stall window: nudges exhausted -> operator jam incident.
        self._observe(wd, gc, up, cfg, pos=40.0, wants=True, now=8.0)
        self.assertEqual(len(up.moves), 3, "no fourth nudge")
        active = gc.runtime_stats.activeIncident()
        self.assertIsNotNone(active)
        self.assertEqual(active["kind"], FEEDER_JAM_INCIDENT_KIND)
        self.assertEqual(active["channel_label"], "C2")

    def test_forward_progress_resets_and_never_nudges(self) -> None:
        gc = _FakeGC()
        up = _FakeStepper()
        wd = FeederStuckWatchdog(gc)
        cfg = _cfg()

        pos = 60.0
        for i in range(10):
            pos -= 5.0  # advancing toward the exit each tick (> epsilon)
            self._observe(wd, gc, up, cfg, pos=pos, wants=True, now=float(i) * 2.0)
        self.assertEqual(up.moves, [], "moving piece must never be nudged")
        self.assertIsNone(gc.runtime_stats.activeIncident())

    def test_holding_for_downstream_does_not_count_as_stuck(self) -> None:
        gc = _FakeGC()
        up = _FakeStepper()
        wd = FeederStuckWatchdog(gc)
        cfg = _cfg()

        # Piece present but intentionally held (wants_advance False) for a long
        # time: the clock is paused, so no nudge and no incident.
        self._observe(wd, gc, up, cfg, pos=40.0, wants=False, now=0.0)
        self._observe(wd, gc, up, cfg, pos=40.0, wants=False, now=100.0)
        self.assertEqual(up.moves, [])
        self.assertIsNone(gc.runtime_stats.activeIncident())

    def test_piece_leaving_resets_attempts(self) -> None:
        gc = _FakeGC()
        up = _FakeStepper()
        wd = FeederStuckWatchdog(gc)
        cfg = _cfg()

        self._observe(wd, gc, up, cfg, pos=40.0, wants=True, now=0.0)
        self._observe(wd, gc, up, cfg, pos=40.0, wants=True, now=2.0)
        self.assertEqual(len(up.moves), 1)
        # Channel clears (no piece) -> tracker reset.
        self._observe(wd, gc, up, cfg, pos=None, wants=False, now=3.0)
        # A brand-new stall starts its own attempt budget.
        self._observe(wd, gc, up, cfg, pos=50.0, wants=True, now=4.0)
        self._observe(wd, gc, up, cfg, pos=50.0, wants=True, now=6.0)
        self.assertEqual(len(up.moves), 2)
        self.assertIsNone(gc.runtime_stats.activeIncident())

    def test_nudge_that_frees_piece_is_recorded_as_auto_resolved(self) -> None:
        gc = _FakeGC()
        up = _FakeStepper()
        wd = FeederStuckWatchdog(gc)
        cfg = _cfg()

        # Stall, nudge once, then the piece advances (the nudge freed it).
        self._observe(wd, gc, up, cfg, pos=40.0, wants=True, now=0.0)
        self._observe(wd, gc, up, cfg, pos=40.0, wants=True, now=2.0)
        self.assertEqual(len(up.moves), 1)
        self._observe(wd, gc, up, cfg, pos=30.0, wants=True, now=3.0)

        # Never escalated to an operator hold, but the freed jam is logged.
        self.assertIsNone(gc.runtime_stats.activeIncident())
        recorded = gc.runtime_stats.auto_resolved
        self.assertEqual(len(recorded), 1)
        row = recorded[0]
        self.assertEqual(row["kind"], FEEDER_JAM_INCIDENT_KIND)
        self.assertEqual(row["status"], "auto_resolved")
        self.assertEqual(row["channel_label"], "C2")
        self.assertEqual(row["nudge_attempts"], 1)
        self.assertEqual(row["resolved_by"], "auto")
        self.assertGreater(row["resolved_at"], row["triggered_at"])

    def test_escalated_jam_is_not_double_logged_as_auto_resolved(self) -> None:
        gc = _FakeGC()
        up = _FakeStepper()
        wd = FeederStuckWatchdog(gc)
        cfg = _cfg()

        # Drive to an operator jam, then the operator frees it (piece advances).
        self._observe(wd, gc, up, cfg, pos=40.0, wants=True, now=0.0)
        for t in (2.0, 4.0, 6.0, 8.0):
            self._observe(wd, gc, up, cfg, pos=40.0, wants=True, now=t)
        self.assertEqual(gc.runtime_stats.activeIncident()["kind"], FEEDER_JAM_INCIDENT_KIND)
        self._observe(wd, gc, up, cfg, pos=30.0, wants=True, now=10.0)

        # The active-slot clear path owns that resolution; no auto-resolved row.
        self.assertIsNone(gc.runtime_stats.activeIncident())
        self.assertEqual(gc.runtime_stats.auto_resolved, [])

    def test_disabled_watchdog_does_nothing(self) -> None:
        gc = _FakeGC()
        up = _FakeStepper()
        wd = FeederStuckWatchdog(gc)
        cfg = _cfg()
        cfg.stuck_watchdog_enabled = False

        self._observe(wd, gc, up, cfg, pos=40.0, wants=True, now=0.0)
        self._observe(wd, gc, up, cfg, pos=40.0, wants=True, now=100.0)
        self.assertEqual(up.moves, [])
        self.assertIsNone(gc.runtime_stats.activeIncident())

    def test_active_jam_clears_when_piece_advances(self) -> None:
        gc = _FakeGC()
        up = _FakeStepper()
        wd = FeederStuckWatchdog(gc)
        cfg = _cfg()

        # Drive to a jam.
        self._observe(wd, gc, up, cfg, pos=40.0, wants=True, now=0.0)
        for t in (2.0, 4.0, 6.0, 8.0):
            self._observe(wd, gc, up, cfg, pos=40.0, wants=True, now=t)
        self.assertEqual(gc.runtime_stats.activeIncident()["kind"], FEEDER_JAM_INCIDENT_KIND)

        # Operator frees it; the piece now advances -> incident auto-clears.
        self._observe(wd, gc, up, cfg, pos=30.0, wants=True, now=10.0)
        self.assertIsNone(gc.runtime_stats.activeIncident())


if __name__ == "__main__":
    unittest.main()
