import logging
import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from irl.config import ClassificationChannelMode
from subsystems.classification_channel.incidents import (
    C4_EXIT_STUCK_INCIDENT_KIND,
    C4_STALL_WATCHDOG_SOURCE_KIND,
)
from subsystems.classification_channel.state_machine import (
    _STALL_INCIDENT_MS,
    ClassificationChannelStateMachine,
)


class FakeRuntimeStats:
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


class FakePerception:
    def __init__(self, n_pieces: int) -> None:
        self.n_pieces = n_pieces

    def read_state(self, channel: int):
        assert channel == 4
        return SimpleNamespace(n_pieces=self.n_pieces)


class FakeTwoPiece:
    def __init__(self) -> None:
        self.last_progress_at = time.monotonic()
        self.step_calls = 0
        self.auto_clear_calls = 0
        self.auto_clear_result = SimpleNamespace(
            cleared=False, occupied_at_start=True, output_deg_moved=720.0, reason="budget_exhausted"
        )

    def noteProgress(self) -> None:
        self.last_progress_at = time.monotonic()

    def phaseName(self) -> str:
        return "waiting"

    def step(self) -> None:
        self.step_calls += 1

    def attemptStallAutoClear(self, *, max_output_deg: float):
        self.auto_clear_calls += 1
        assert max_output_deg > 0
        return self.auto_clear_result


@pytest.fixture()
def machine_params_env():
    old = os.environ.get("MACHINE_SPECIFIC_PARAMS_PATH")
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = str(Path(tmpdir) / "machine_params.toml")
        yield
    if old is None:
        os.environ.pop("MACHINE_SPECIFIC_PARAMS_PATH", None)
    else:
        os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = old


def mkWatchdogSm(n_pieces: int = 1) -> ClassificationChannelStateMachine:
    sm = ClassificationChannelStateMachine.__new__(ClassificationChannelStateMachine)
    sm.gc = SimpleNamespace(
        runtime_stats=FakeRuntimeStats(),
        perception_service=FakePerception(n_pieces),
    )
    sm.logger = logging.getLogger("test_c4_stall_watchdog")
    sm._mode = ClassificationChannelMode.TWO_PIECE_STATE_MACHINE_REV01
    sm._two_piece = FakeTwoPiece()
    sm._last_progress_at = time.monotonic()
    sm._stall_incident_raised = False
    sm._stall_resolve_requested = False
    sm._stall_shake_request = None
    return sm


def setExitStuckMode(mode: str) -> None:
    from toml_config import setDashboardConfig

    setDashboardConfig({"incident_handling": {"exit_stuck": mode}})


def stallOut(sm: ClassificationChannelStateMachine) -> None:
    sm._two_piece.last_progress_at = time.monotonic() - (_STALL_INCIDENT_MS / 1000.0) - 1.0


def test_indexed_missing_reservation_still_trips_watchdog(machine_params_env):
    setExitStuckMode("manual")
    sm = mkWatchdogSm(n_pieces=0)
    sm._mode = ClassificationChannelMode.INDEXED_BUFFER_REV01
    sm._two_piece.hasReservations = lambda: True
    stallOut(sm)
    sm._checkStall(time.monotonic())
    assert sm.gc.runtime_stats.activeIncident() is not None


def test_indexed_mode_refuses_unbounded_manual_wiggle(machine_params_env):
    setExitStuckMode("manual")
    sm = mkWatchdogSm(n_pieces=1)
    sm._mode = ClassificationChannelMode.INDEXED_BUFFER_REV01
    sm._two_piece.hasReservations = lambda: True
    stallOut(sm)
    sm._checkStall(time.monotonic())
    assert not sm.requestStallShake(amplitude_output_deg=8, cycles=3,
                                   microsteps_per_second=4000,
                                   acceleration_microsteps_per_second_sq=80000)
    assert sm._stall_shake_request is None


def test_no_incident_while_progress_is_fresh(machine_params_env) -> None:
    setExitStuckMode("manual")
    sm = mkWatchdogSm(n_pieces=1)

    sm._checkStall(time.monotonic())

    assert sm.gc.runtime_stats.activeIncident() is None


def test_no_incident_when_channel_empty(machine_params_env) -> None:
    setExitStuckMode("manual")
    sm = mkWatchdogSm(n_pieces=0)
    stallOut(sm)

    sm._checkStall(time.monotonic())

    assert sm.gc.runtime_stats.activeIncident() is None
    # Re-armed: the stale progress timestamp was refreshed.
    assert time.monotonic() - sm._two_piece.last_progress_at < 1.0


def test_manual_mode_raises_exit_stuck_incident(machine_params_env) -> None:
    setExitStuckMode("manual")
    sm = mkWatchdogSm(n_pieces=1)
    stallOut(sm)

    sm._checkStall(time.monotonic())

    active = sm.gc.runtime_stats.activeIncident()
    assert active is not None
    assert active["kind"] == C4_EXIT_STUCK_INCIDENT_KIND
    assert active["source_kind"] == C4_STALL_WATCHDOG_SOURCE_KIND
    assert active["channel"] == "c4"
    assert active["auto_clear_failed"] is False
    assert sm._stall_incident_raised
    assert sm._two_piece.auto_clear_calls == 0


def test_incident_auto_clears_when_channel_empties(machine_params_env) -> None:
    setExitStuckMode("manual")
    sm = mkWatchdogSm(n_pieces=1)
    stallOut(sm)
    sm._checkStall(time.monotonic())
    assert sm.gc.runtime_stats.activeIncident() is not None

    sm.gc.perception_service.n_pieces = 0
    sm._checkStall(time.monotonic())

    assert sm.gc.runtime_stats.activeIncident() is None
    assert not sm._stall_incident_raised


def test_operator_resolve_rearms_without_instant_refire(machine_params_env) -> None:
    setExitStuckMode("manual")
    sm = mkWatchdogSm(n_pieces=1)
    stallOut(sm)
    sm._checkStall(time.monotonic())
    assert sm.gc.runtime_stats.activeIncident() is not None

    # Operator resolves via the UI (incident cleared out from under us) but the
    # piece is still on the channel: the next check must re-arm, not re-fire.
    sm.gc.runtime_stats.clearActiveIncident(kind=C4_EXIT_STUCK_INCIDENT_KIND)
    sm._checkStall(time.monotonic())

    assert sm.gc.runtime_stats.activeIncident() is None
    assert not sm._stall_incident_raised
    sm._checkStall(time.monotonic())
    assert sm.gc.runtime_stats.activeIncident() is None


def test_automatic_mode_clears_channel_without_incident(machine_params_env) -> None:
    setExitStuckMode("automatic")
    sm = mkWatchdogSm(n_pieces=1)
    sm._two_piece.auto_clear_result = SimpleNamespace(
        cleared=True, occupied_at_start=True, output_deg_moved=144.0, reason="cleared"
    )
    stallOut(sm)

    sm._checkStall(time.monotonic())

    assert sm._two_piece.auto_clear_calls == 1
    assert sm.gc.runtime_stats.activeIncident() is None
    assert not sm._stall_incident_raised


def test_automatic_clear_is_recorded_as_auto_resolved(machine_params_env) -> None:
    setExitStuckMode("automatic")
    sm = mkWatchdogSm(n_pieces=1)
    sm._two_piece.auto_clear_result = SimpleNamespace(
        cleared=True, occupied_at_start=True, output_deg_moved=144.0, reason="cleared"
    )
    stallOut(sm)

    sm._checkStall(time.monotonic())

    # Never became an operator-facing hold, but it must still be logged.
    assert sm.gc.runtime_stats.activeIncident() is None
    recorded = sm.gc.runtime_stats.auto_resolved
    assert len(recorded) == 1
    row = recorded[0]
    assert row["kind"] == C4_EXIT_STUCK_INCIDENT_KIND
    assert row["source_kind"] == C4_STALL_WATCHDOG_SOURCE_KIND
    assert row["status"] == "auto_resolved"
    assert row["auto_clear_failed"] is False
    assert row["auto_clear_moved_deg"] == 144.0
    assert row["resolved_by"] == "auto"
    # Real stall span recorded (triggered before now, resolved at now).
    assert row["resolved_at"] > row["triggered_at"]


def test_automatic_mode_falls_back_to_incident_when_clear_fails(machine_params_env) -> None:
    setExitStuckMode("automatic")
    sm = mkWatchdogSm(n_pieces=1)
    stallOut(sm)

    sm._checkStall(time.monotonic())

    assert sm._two_piece.auto_clear_calls == 1
    active = sm.gc.runtime_stats.activeIncident()
    assert active is not None
    assert active["kind"] == C4_EXIT_STUCK_INCIDENT_KIND
    assert active["auto_clear_failed"] is True
    assert active["auto_clear_moved_deg"] == 720.0


def test_off_mode_never_raises(machine_params_env) -> None:
    setExitStuckMode("off")
    sm = mkWatchdogSm(n_pieces=1)
    stallOut(sm)

    sm._checkStall(time.monotonic())

    assert sm.gc.runtime_stats.activeIncident() is None
    assert sm._two_piece.auto_clear_calls == 0


def test_step_freezes_flow_while_stall_incident_active(machine_params_env) -> None:
    setExitStuckMode("manual")
    sm = mkWatchdogSm(n_pieces=1)
    stallOut(sm)
    sm._checkStall(time.monotonic())
    assert sm.gc.runtime_stats.activeIncident() is not None

    sm.step()

    assert sm._two_piece.step_calls == 0

    # Once the channel empties the incident drops and the flow resumes.
    sm.gc.perception_service.n_pieces = 0
    sm.step()
    assert sm.gc.runtime_stats.activeIncident() is None
    sm.step()
    assert sm._two_piece.step_calls > 0


def test_requested_auto_resolve_runs_clear_and_drops_incident(machine_params_env) -> None:
    setExitStuckMode("manual")
    sm = mkWatchdogSm(n_pieces=1)
    stallOut(sm)
    sm._checkStall(time.monotonic())
    assert sm.gc.runtime_stats.activeIncident() is not None

    assert sm.requestStallAutoResolve() is True
    sm._two_piece.auto_clear_result = SimpleNamespace(
        cleared=True, occupied_at_start=True, output_deg_moved=216.0, reason="cleared"
    )
    sm.step()

    assert sm._two_piece.auto_clear_calls == 1
    assert sm.gc.runtime_stats.activeIncident() is None
    assert not sm._stall_incident_raised
    assert not sm._stall_resolve_requested


def test_requested_auto_resolve_failure_keeps_incident_with_details(machine_params_env) -> None:
    setExitStuckMode("manual")
    sm = mkWatchdogSm(n_pieces=1)
    stallOut(sm)
    sm._checkStall(time.monotonic())

    assert sm.requestStallAutoResolve() is True
    sm.step()

    assert sm._two_piece.auto_clear_calls == 1
    active = sm.gc.runtime_stats.activeIncident()
    assert active is not None
    assert active["kind"] == C4_EXIT_STUCK_INCIDENT_KIND
    assert active["status"] == "waiting_for_operator"
    assert active["awaiting_operator"] is True
    assert active["auto_clear_failed"] is True
    assert active["auto_clear_moved_deg"] == 720.0
    # Still resolvable: the flow stays frozen and the watchdog keeps monitoring.
    assert sm._two_piece.step_calls == 0


def test_request_auto_resolve_rejected_without_incident(machine_params_env) -> None:
    setExitStuckMode("manual")
    sm = mkWatchdogSm(n_pieces=1)

    assert sm.requestStallAutoResolve() is False
    assert not sm._stall_resolve_requested


def test_does_not_stomp_other_active_incident(machine_params_env) -> None:
    setExitStuckMode("manual")
    sm = mkWatchdogSm(n_pieces=1)
    sm.gc.runtime_stats.setActiveIncident({"kind": "distribution_chute_jam"})
    stallOut(sm)

    sm._checkStall(time.monotonic())

    active = sm.gc.runtime_stats.activeIncident()
    assert active is not None
    assert active["kind"] == "distribution_chute_jam"
    assert not sm._stall_incident_raised


def _armShakeTest(sm: ClassificationChannelStateMachine, monkeypatch, *, cleared: bool) -> list[dict]:
    from subsystems.classification_channel.simple_state_machine_rev01 import channel_clear

    calls: list[dict] = []

    def fakeStage(gc, irl, **kwargs):
        calls.append(kwargs)
        return channel_clear.ChannelClearResult(cleared, True, 0.0, "shaken_clear" if cleared else "still_occupied")

    monkeypatch.setattr(channel_clear, "shakeChannelStage", fakeStage)
    monkeypatch.setattr(channel_clear, "shimmyStepperPerOutputDeg", lambda cfg: 10.0)
    sm.irl = None
    sm.irl_config = None
    sm.vision = None
    return calls


def test_requested_test_wiggle_runs_one_stage_and_reports_failure(machine_params_env, monkeypatch) -> None:
    setExitStuckMode("manual")
    sm = mkWatchdogSm(n_pieces=1)
    stallOut(sm)
    sm._checkStall(time.monotonic())
    calls = _armShakeTest(sm, monkeypatch, cleared=False)

    assert sm.requestStallShake(
        amplitude_output_deg=2.5, cycles=3, microsteps_per_second=1800, acceleration_microsteps_per_second_sq=6000
    ) is True
    sm.step()

    assert len(calls) == 1
    assert calls[0]["amplitude_output_deg"] == 2.5
    assert calls[0]["cycles"] == 3
    assert calls[0]["stepper_per_output_deg"] == 10.0
    active = sm.gc.runtime_stats.activeIncident()
    assert active is not None and active["kind"] == C4_EXIT_STUCK_INCIDENT_KIND
    assert active["status"] == "waiting_for_operator"
    assert "Test wiggle 2.50° x3" in active["operator_message"]
    assert sm._stall_shake_request is None
    assert sm._two_piece.step_calls == 0


def test_requested_test_wiggle_that_frees_the_piece_drops_incident(machine_params_env, monkeypatch) -> None:
    setExitStuckMode("manual")
    sm = mkWatchdogSm(n_pieces=1)
    stallOut(sm)
    sm._checkStall(time.monotonic())
    _armShakeTest(sm, monkeypatch, cleared=True)

    assert sm.requestStallShake(
        amplitude_output_deg=1.0, cycles=2, microsteps_per_second=1200, acceleration_microsteps_per_second_sq=3600
    ) is True
    sm.step()

    assert sm.gc.runtime_stats.activeIncident() is None
    assert sm._stall_incident_raised is False


def test_request_test_wiggle_rejected_without_incident(machine_params_env) -> None:
    setExitStuckMode("manual")
    sm = mkWatchdogSm(n_pieces=1)
    assert sm.requestStallShake(
        amplitude_output_deg=1.0, cycles=1, microsteps_per_second=1000, acceleration_microsteps_per_second_sq=3000
    ) is False
    assert sm._stall_shake_request is None
