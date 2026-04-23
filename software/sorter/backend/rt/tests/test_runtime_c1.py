from __future__ import annotations

import threading
import time
from typing import Callable


from rt.contracts.runtime import RuntimeInbox
from rt.coupling.slots import CapacitySlot
from rt.runtimes.base import HwWorker
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
    )
    return rt, slot, log, worker


def test_c1_pulses_when_downstream_has_room() -> None:
    rt, slot, log, _ = _make_runtime()
    rt.tick(RuntimeInbox(tracks=None, capacity_downstream=1), now_mono=0.0)
    assert log == ["pulse"]
    # Slot claimed and held by the pulse (piece presumed in-flight downstream).
    assert slot.available() == 0
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


def test_c1_available_slots_is_zero_while_paused() -> None:
    rt, _slot, _log, _ = _make_runtime()
    rt.clear_pause()
    assert rt.available_slots() == 1
    rt._paused_reason = "test_pause"  # type: ignore[attr-defined]
    assert rt.available_slots() == 0


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
