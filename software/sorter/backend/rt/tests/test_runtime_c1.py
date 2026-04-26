from __future__ import annotations

import threading
import time
from typing import Callable

import pytest


from rt.contracts.runtime import RuntimeInbox
from rt.coupling.slots import CapacitySlot
from rt.runtimes.base import HwWorker, _Command
from rt.runtimes.c1 import RuntimeC1


class _InlineHwWorker:
    """HwWorker stub that runs enqueued commands inline on the calling thread.

    Trims out thread timing from the unit tests so we can assert on slot
    state immediately after a tick.
    """

    def __init__(self) -> None:
        self._busy = False
        self.commands: list[str] = []

    def start(self) -> None:  # pragma: no cover - no-op
        return None

    def stop(self, timeout_s: float = 2.0) -> None:  # pragma: no cover
        return None

    def enqueue(self, command: Callable[[], None], *, priority: int = 0, label: str = "hw_cmd") -> bool:
        self.commands.append(label)
        self._busy = True
        try:
            command()
        finally:
            self._busy = False
        return True

    def busy(self) -> bool:
        return self._busy

    def pending(self) -> int:
        return 0


def _make_runtime(
    *,
    pulse_success: bool = True,
    recovery_success: bool = True,
    downstream_cap: int = 1,
    hw_worker=None,
    pulse_observer: Callable[[str], None] | None = None,
    recovery_admission_check: (
        Callable[[int], "tuple[bool, dict]"] | None
    ) = None,
    **kwargs,
) -> tuple[RuntimeC1, CapacitySlot, list[str], _InlineHwWorker]:
    slot = CapacitySlot("c1_to_c2", capacity=downstream_cap)
    log: list[str] = []

    def pulse() -> bool:
        log.append("pulse")
        return pulse_success

    def recovery(level: int) -> bool:
        log.append(f"recover_l{level}")
        return recovery_success

    worker = hw_worker if hw_worker is not None else _InlineHwWorker()
    rt = RuntimeC1(
        downstream_slot=slot,
        pulse_command=pulse,
        recovery_command=recovery,
        hw_worker=worker,  # type: ignore[arg-type]
        jam_timeout_s=kwargs.get("jam_timeout_s", 1.0),
        jam_min_pulses=kwargs.get("jam_min_pulses", 2),
        jam_cooldown_s=kwargs.get("jam_cooldown_s", 0.0),
        max_recovery_cycles=kwargs.get("max_recovery_cycles", 3),
        pulse_cooldown_s=kwargs.get("pulse_cooldown_s", 0.0),
        startup_hold_s=kwargs.get("startup_hold_s", 0.0),
        unconfirmed_pulse_limit=kwargs.get("unconfirmed_pulse_limit", 2),
        observation_hold_s=kwargs.get("observation_hold_s", 0.0),
        pulse_observer=pulse_observer,
        recovery_admission_check=recovery_admission_check,
    )
    return rt, slot, log, worker


def test_c1_startup_hold_blocks_initial_feed_until_elapsed() -> None:
    rt, slot, log, _ = _make_runtime(startup_hold_s=2.0)

    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=1), now_mono=10.0)
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=1), now_mono=11.0)

    assert log == []
    assert slot.taken(now_mono=11.0) == 0
    assert rt.health().blocked_reason == "startup_hold"
    snap = rt.debug_snapshot()
    assert snap["startup_hold_armed"] is True
    assert snap["startup_hold_remaining_s"] == pytest.approx(1.0)

    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=1), now_mono=12.1)

    assert log == ["pulse"]
    assert rt.health().state == "pulsing"
    assert rt.debug_snapshot()["startup_hold_armed"] is False


def test_c1_pulses_when_downstream_has_room() -> None:
    rt, slot, log, _ = _make_runtime()
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=1), now_mono=0.0)
    assert log == ["pulse"]
    # Slot claimed and held by the pulse (piece presumed in-flight downstream).
    assert slot.available() == 0
    assert rt.health().state == "pulsing"


def test_c1_pulse_observer_fires_on_dispatch_and_recovery() -> None:
    events: list[str] = []
    rt, _slot, log, _ = _make_runtime(
        jam_timeout_s=0.5,
        jam_min_pulses=2,
        pulse_cooldown_s=0.0,
        downstream_cap=10,
        pulse_observer=lambda action_id: events.append(action_id),
    )
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=0.0)
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=9), now_mono=0.0)
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=8), now_mono=5.0)

    assert events[:2] == ["pulse", "pulse"]
    # The third tick triggers recovery, level 0.
    assert "recover_level_0" in events
    # Sanity: pulse_command and recovery_command both ran.
    assert log[:2] == ["pulse", "pulse"]
    assert "recover_l0" in log


def test_c1_recovery_blocked_when_admission_denies() -> None:
    """Headroom-gated recovery skips the dispatch and bumps cooldown."""
    decisions: list[int] = []

    def _admission(level: int) -> tuple[bool, dict[str, object]]:
        decisions.append(level)
        return False, {
            "level": level,
            "headroom_eq": 0,
            "level_estimate_eq": 12,
            "reason": "insufficient_c2_headroom",
        }

    rt, _slot, log, _ = _make_runtime(
        jam_timeout_s=0.5,
        jam_min_pulses=2,
        pulse_cooldown_s=0.0,
        jam_cooldown_s=2.0,
        downstream_cap=10,
        recovery_admission_check=_admission,
    )
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=0.0)
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=9), now_mono=0.0)
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=8), now_mono=5.0)

    # Recovery was attempted but admission denied — pulse log has the
    # earlier two pulses but no recovery dispatch.
    assert log[:2] == ["pulse", "pulse"]
    assert "recover_l0" not in log
    assert decisions == [0]
    assert rt.health().blocked_reason == "recovery_headroom_insufficient"

    info = rt.debug_snapshot()["last_recovery_admission"]
    assert info["reason"] == "insufficient_c2_headroom"
    assert info["headroom_eq"] == 0
    # No attempt was burned — the cycle counter stays at 0 so we can
    # try again once C2 has drained.
    assert rt.debug_snapshot()["jam"]["attempts"] == 0


def test_c1_recovery_proceeds_when_admission_allows() -> None:
    def _admission(level: int) -> tuple[bool, dict[str, object]]:
        return True, {"level": level, "headroom_eq": 14, "level_estimate_eq": 3}

    rt, _slot, log, _ = _make_runtime(
        jam_timeout_s=0.5,
        jam_min_pulses=2,
        pulse_cooldown_s=0.0,
        downstream_cap=10,
        recovery_admission_check=_admission,
    )
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=0.0)
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=9), now_mono=0.0)
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=8), now_mono=5.0)

    assert "recover_l0" in log


def test_c1_recovery_admission_failures_fail_open() -> None:
    def _admission(level: int) -> tuple[bool, dict[str, object]]:
        raise RuntimeError("admission probe down")

    rt, _slot, log, _ = _make_runtime(
        jam_timeout_s=0.5,
        jam_min_pulses=2,
        pulse_cooldown_s=0.0,
        downstream_cap=10,
        recovery_admission_check=_admission,
    )
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=0.0)
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=9), now_mono=0.0)
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=8), now_mono=5.0)

    # Fail-open: if the admission probe crashes we still recover.
    assert "recover_l0" in log
    info = rt.debug_snapshot()["last_recovery_admission"]
    assert info["error"] == "admission_check_failed"


def test_c1_pulse_observer_failures_do_not_crash_runtime() -> None:
    def _broken(action_id: str) -> None:
        raise RuntimeError("observer down")

    rt, _slot, log, _ = _make_runtime(pulse_observer=_broken)
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=1), now_mono=0.0)
    # The pulse must still fire even when the observer raises.
    assert log == ["pulse"]
    assert rt.health().state == "pulsing"


def test_c1_does_not_pulse_when_downstream_full() -> None:
    rt, slot, log, _ = _make_runtime(downstream_cap=1)
    # Pre-fill the slot so capacity_downstream == 0.
    assert slot.try_claim() is True
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=0), now_mono=0.0)
    assert log == []
    assert rt.health().blocked_reason == "downstream_full"


def test_c1_releases_slot_if_hardware_rejects_pulse() -> None:
    rt, slot, log, _ = _make_runtime(pulse_success=False)
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=1), now_mono=0.0)
    assert log == ["pulse"]
    # Hardware said nope — capacity restored.
    assert slot.available() == 1


def test_c1_triggers_jam_recovery_after_stall() -> None:
    rt, _slot, log, _ = _make_runtime(
        jam_timeout_s=0.5,
        jam_min_pulses=2,
        pulse_cooldown_s=0.0,
        downstream_cap=10,  # so successive pulses all fire
    )
    # Two successful pulses while "stalled" — no downstream progress feedback.
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=0.0)
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=9), now_mono=0.0)
    # Jump forward past the jam timeout; next tick should trigger recovery.
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=8), now_mono=5.0)
    assert "recover_l0" in log


def test_c1_pause_after_recovery_exhausted() -> None:
    rt, _slot, log, _ = _make_runtime(
        jam_timeout_s=0.5,
        jam_min_pulses=1,
        pulse_cooldown_s=0.0,
        max_recovery_cycles=2,
        recovery_success=False,
    )
    # Prime with one pulse so the jam counter ticks.
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=1), now_mono=0.0)
    # Two recovery attempts + third tick should transition to paused.
    for t in (5.0, 6.0, 7.0, 8.0):
        rt.tick(RuntimeInbox(tracks=None, capacity_downstream=1), now_mono=t)
    assert rt.is_paused()
    assert rt.available_slots() == 0


def test_c1_clear_pause_resets_jam_exhaustion() -> None:
    rt, _slot, _log, _ = _make_runtime(
        jam_timeout_s=0.5,
        jam_min_pulses=1,
        pulse_cooldown_s=0.0,
        max_recovery_cycles=1,
        recovery_success=False,
    )
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=1), now_mono=0.0)
    for t in (5.0, 6.0, 7.0):
        rt.tick(RuntimeInbox(tracks=None, capacity_downstream=1), now_mono=t)
    assert rt.is_paused()
    assert rt.health().blocked_reason == "jam_recovery_exhausted"

    rt.clear_pause()

    assert not rt.is_paused()
    assert rt.available_slots() == 1
    assert rt.health().state == "idle"
    assert rt.health().blocked_reason is None


def test_c1_downstream_progress_resets_jam_counter() -> None:
    rt, _slot, log, _ = _make_runtime(
        jam_timeout_s=0.5,
        jam_min_pulses=1,
        pulse_cooldown_s=0.0,
        downstream_cap=10,
    )
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=0.0)
    assert log[-1] == "pulse"
    rt.notify_downstream_progress(now_mono=1.0)
    # Even past the jam timeout, a fresh tick should pulse not recover.
    log.clear()
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=9), now_mono=5.0)
    assert log == ["pulse"]


def test_c1_observes_after_unconfirmed_pulse_limit() -> None:
    rt, slot, log, _ = _make_runtime(
        downstream_cap=10,
        pulse_cooldown_s=0.0,
        jam_timeout_s=100.0,
        unconfirmed_pulse_limit=2,
        observation_hold_s=10.0,
    )

    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=0.0)
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=1.0)
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=2.0)

    assert log == ["pulse", "pulse"]
    assert slot.taken(now_mono=2.0) == 2
    assert rt.health().blocked_reason == "observing_downstream"
    snap = rt.debug_snapshot()
    assert snap["observation_hold_remaining_s"] == pytest.approx(9.0)

    rt.notify_downstream_progress(now_mono=3.0)
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=3.1)

    assert log == ["pulse", "pulse"]
    assert rt.health().blocked_reason == "observing_downstream"
    assert rt.debug_snapshot()["observation_hold_remaining_s"] == pytest.approx(9.9)

    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=13.1)

    assert log == ["pulse", "pulse", "pulse"]
    assert rt.health().state == "pulsing"


def test_c1_observes_after_downstream_progress_before_next_blind_pulse() -> None:
    rt, slot, log, _ = _make_runtime(
        downstream_cap=10,
        pulse_cooldown_s=0.0,
        jam_timeout_s=100.0,
        unconfirmed_pulse_limit=4,
        observation_hold_s=8.0,
    )

    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=0.0)
    rt.notify_downstream_progress(now_mono=0.5)
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=1.0)

    assert log == ["pulse"]
    assert slot.taken(now_mono=1.0) == 1
    assert rt.health().blocked_reason == "observing_downstream"

    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=8.6)

    assert log == ["pulse", "pulse"]
    assert rt.health().state == "pulsing"


def test_c1_hw_worker_queue_rollback_releases_slot() -> None:
    """If the hardware worker queue is saturated the slot reservation must
    not leak — otherwise downstream would block forever."""

    class FullHw(_InlineHwWorker):
        def enqueue(self, command, *, priority=0, label="hw_cmd"):
            return False

    rt, slot, log, _ = _make_runtime(hw_worker=FullHw())
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=1), now_mono=0.0)
    assert log == []  # pulse never reached the worker
    assert slot.available() == 1


def test_c1_does_not_stack_pulses_while_hw_command_is_queued() -> None:
    class QueuedHw(_InlineHwWorker):
        def __init__(self) -> None:
            super().__init__()
            self.queued_command = None
            self.queued_label = None

        def enqueue(self, command, *, priority=0, label="hw_cmd"):
            self.commands.append(label)
            self.queued_command = command
            self.queued_label = label
            return True

        def pending(self) -> int:
            return 1 if self.queued_command is not None else 0

    worker = QueuedHw()
    rt, slot, log, _ = _make_runtime(
        hw_worker=worker,
        pulse_cooldown_s=0.0,
        downstream_cap=10,
    )

    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=0.0)
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=0.1)

    assert worker.commands == ["c1_pulse"]
    assert log == []
    assert slot.taken(now_mono=0.1) == 1
    assert rt.health().blocked_reason == "hw_busy"


def test_c1_available_slots_is_zero_while_paused() -> None:
    rt, _slot, _log, _ = _make_runtime()
    rt.clear_pause()
    assert rt.available_slots() == 1
    rt._paused_reason = "test_pause"  # type: ignore[attr-defined]
    assert rt.available_slots() == 0


def test_c1_maintenance_pause_blocks_source_pulses() -> None:
    rt, slot, log, _ = _make_runtime()
    rt.pause_for_maintenance("c234_purge")

    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=1), now_mono=0.0)

    assert log == []
    assert slot.available() == 1
    assert rt.available_slots() == 0
    assert rt.health().blocked_reason == "c234_purge"

    rt.resume_from_maintenance()
    assert rt.available_slots() == 1


def test_c1_resume_from_maintenance_rearms_startup_hold() -> None:
    rt, _slot, log, _ = _make_runtime(startup_hold_s=1.0, downstream_cap=10)

    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=0.0)
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=1.1)
    assert log == ["pulse"]

    rt.pause_for_maintenance("c234_purge")
    rt.resume_from_maintenance()
    log.clear()

    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=10), now_mono=2.0)

    assert log == []
    assert rt.health().blocked_reason == "startup_hold"


def test_real_hw_worker_runs_command_on_thread() -> None:
    """Covers the HwWorker start/stop lifecycle and async execution."""
    worker = HwWorker("c1_test")
    worker.start()
    done = threading.Event()

    def cmd() -> None:
        time.sleep(0.005)
        done.set()

    assert worker.enqueue(cmd, label="smoke") is True
    assert done.wait(timeout=1.0)
    assert worker.status_snapshot()["thread_alive"] is True
    worker.stop(timeout_s=1.0)


def test_real_hw_worker_enqueue_restarts_missing_thread() -> None:
    worker = HwWorker("c1_restart")
    done = threading.Event()

    assert worker.status_snapshot()["thread_alive"] is False
    assert worker.enqueue(done.set, label="restart_smoke") is True
    assert done.wait(timeout=1.0)
    status = worker.status_snapshot()
    assert status["running"] is True
    assert status["thread_alive"] is True
    worker.stop(timeout_s=1.0)


def test_real_hw_worker_ignores_stale_stop_sentinel_on_restart() -> None:
    worker = HwWorker("c1_stale_sentinel")
    done = threading.Event()
    worker._queue.put_nowait(None)  # noqa: SLF001 - simulate stale stop sentinel
    worker._queue.put_nowait(  # noqa: SLF001
        _Command(priority=0, seq=1, fn=done.set, label="after_stale_sentinel")
    )

    worker.start()

    assert done.wait(timeout=1.0)
    assert worker.status_snapshot()["thread_alive"] is True
    worker.stop(timeout_s=1.0)


def test_real_hw_worker_pending_restarts_dead_thread_with_backlog() -> None:
    worker = HwWorker("c1_pending_restart")
    done = threading.Event()
    worker._running = True  # noqa: SLF001 - simulate a crashed worker with backlog
    worker._thread = None  # noqa: SLF001
    worker._queue.put_nowait(  # noqa: SLF001
        _Command(priority=0, seq=1, fn=done.set, label="backlog")
    )

    assert worker.pending() >= 1

    assert done.wait(timeout=1.0)
    assert worker.status_snapshot()["thread_alive"] is True
    worker.stop(timeout_s=1.0)


def test_real_hw_worker_rejects_when_queue_full() -> None:
    worker = HwWorker("c1_full")
    released = threading.Event()
    block_one = threading.Event()

    def blocker() -> None:
        block_one.set()
        released.wait(timeout=1.0)

    worker.start()
    assert worker.enqueue(blocker, label="block") is True
    assert block_one.wait(timeout=1.0)
    # Fill the bounded queue; any subsequent enqueue returns False.
    filled_until_full = False
    for i in range(10):
        if not worker.enqueue(lambda: None, label=f"noop_{i}"):
            filled_until_full = True
            break
    assert filled_until_full, "HwWorker should eventually reject enqueue when queue is saturated"
    released.set()
    worker.stop(timeout_s=1.0)
