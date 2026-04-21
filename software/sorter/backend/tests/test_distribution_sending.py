"""Tests for the distribution Sending state — chute reopen gating.

Before the two-gate fix, Sending would reopen the distribution gate after a
fixed ``CHUTE_SETTLE_MS`` wall-clock timer without verifying that the
dropped piece had physically left the classification channel. This is the
root cause of the ~63% ``multi_drop_fail`` rate observed in production
runs — the next drop cycle commits while the previous piece is still
inside the exit guide.

The patched Sending state now holds the gate closed until EITHER:

  * the carousel live tracker no longer shows the dropped piece's
    ``global_id`` (vision-confirmed exit), OR
  * the ``post_distribute_cooldown_s`` cooldown has elapsed since drop
    commit (fallback when the tracker signal is unavailable).
"""

from __future__ import annotations

import queue
import time
import unittest

from defs.known_object import KnownObject
from piece_transport import ClassificationChannelTransport
from runtime_stats import RuntimeStatsCollector
from subsystems.bus import TickBus
from subsystems.distribution.sending import CHUTE_SETTLE_MS, Sending
from subsystems.distribution.states import DistributionState
from subsystems.shared_variables import SharedVariables


class _NullTimer:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _Profiler:
    def hit(self, *args, **kwargs) -> None:
        pass

    def mark(self, *args, **kwargs) -> None:
        pass

    def timer(self, *args, **kwargs):
        return _NullTimer()

    def enterState(self, *args, **kwargs) -> None:
        pass

    def exitState(self, *args, **kwargs) -> None:
        pass


class _Logger:
    def info(self, *args, **kwargs) -> None:
        pass

    def warning(self, *args, **kwargs) -> None:
        pass

    def warn(self, *args, **kwargs) -> None:
        pass


class _RunRecorder:
    def __init__(self) -> None:
        self.pieces: list[KnownObject] = []

    def recordPiece(self, piece: KnownObject) -> None:
        self.pieces.append(piece)


class _FakeVision:
    def __init__(self, live_ids_by_role: dict[str, set[int]] | None = None) -> None:
        self._live = live_ids_by_role or {}

    def getFeederTrackerLiveGlobalIds(self, role: str) -> set[int]:
        return set(self._live.get(role, set()))

    def setLive(self, role: str, ids: set[int]) -> None:
        self._live[role] = set(ids)


class _GlobalConfig:
    def __init__(self) -> None:
        self.logger = _Logger()
        self.profiler = _Profiler()
        self.runtime_stats = RuntimeStatsCollector()
        self.run_recorder = _RunRecorder()
        self.set_progress_tracker = None


def _mkSending(
    *,
    vision: _FakeVision | None,
    cooldown_s: float,
    shared: SharedVariables,
    event_queue: queue.Queue,
    gc: _GlobalConfig,
) -> Sending:
    # ``irl`` is only read for attribute access that Sending/BaseState don't
    # actually touch — a simple stub with a bool chute placeholder is
    # enough for unit-level behavior.
    class _IRL:
        pass

    return Sending(
        _IRL(),  # type: ignore[arg-type]
        gc,  # type: ignore[arg-type]
        shared,
        event_queue,
        vision=vision,
        post_distribute_cooldown_s=cooldown_s,
    )


class SendingChuteReopenGateTests(unittest.TestCase):
    def _mkTransportWithDrop(self, *, tracked_global_id: int) -> ClassificationChannelTransport:
        transport = ClassificationChannelTransport()
        # Manually stage a piece into the exit buffer so
        # ``getPieceForDistributionDrop`` returns it without exercising
        # the full zone manager pipeline.
        piece = KnownObject(tracked_global_id=tracked_global_id)
        transport._exit_piece = piece  # noqa: SLF001 — test-only shortcut
        return transport

    def _mkSharedWithTransport(self, transport: ClassificationChannelTransport) -> SharedVariables:
        bus = TickBus()
        gc_stub = _GlobalConfig()
        shared = SharedVariables(gc=gc_stub, bus=bus)
        shared.transport = transport
        # Close the distribution gate — Sending's job is to reopen it.
        shared.set_distribution_gate(False, reason="test_setup")
        return shared

    def test_reopens_when_tracker_no_longer_sees_piece(self) -> None:
        transport = self._mkTransportWithDrop(tracked_global_id=42)
        shared = self._mkSharedWithTransport(transport)
        gc = _GlobalConfig()
        event_queue: queue.Queue = queue.Queue()
        vision = _FakeVision(live_ids_by_role={"carousel": set()})  # piece has exited

        sending = _mkSending(
            vision=vision,
            cooldown_s=0.8,
            shared=shared,
            event_queue=event_queue,
            gc=gc,
        )

        # First step: pick up the piece, start the settle timer.
        self.assertIsNone(sending.step())
        self.assertIsNotNone(sending.piece)
        self.assertEqual(42, sending.piece.tracked_global_id)

        # Backdate start_time past the chute-settle threshold so we don't
        # have to actually sleep 1.5s; we also push it past the cooldown
        # fallback so only the tracker signal is what lets us reopen.
        sending.start_time = time.time() - (CHUTE_SETTLE_MS / 1000.0) - 5.0

        next_state = sending.step()
        self.assertEqual(DistributionState.IDLE, next_state)
        self.assertTrue(shared.get_distribution_ready())

    def test_holds_gate_while_tracker_still_sees_piece(self) -> None:
        transport = self._mkTransportWithDrop(tracked_global_id=17)
        shared = self._mkSharedWithTransport(transport)
        gc = _GlobalConfig()
        event_queue: queue.Queue = queue.Queue()
        # Tracker still reports the piece — Sending must NOT reopen even
        # after the settle+cooldown clock has elapsed.
        vision = _FakeVision(live_ids_by_role={"carousel": {17}})

        sending = _mkSending(
            vision=vision,
            cooldown_s=0.2,
            shared=shared,
            event_queue=event_queue,
            gc=gc,
        )
        self.assertIsNone(sending.step())

        # Backdate past both settle and cooldown — tracker still dominates.
        sending.start_time = time.time() - (CHUTE_SETTLE_MS / 1000.0) - 5.0

        next_state = sending.step()
        self.assertIsNone(next_state)
        self.assertFalse(shared.get_distribution_ready())

        # Now the tracker loses sight of the piece — gate opens on the
        # next step() call without a fresh cooldown.
        vision.setLive("carousel", set())
        next_state = sending.step()
        self.assertEqual(DistributionState.IDLE, next_state)
        self.assertTrue(shared.get_distribution_ready())

    def test_cooldown_fallback_when_tracker_unavailable(self) -> None:
        transport = self._mkTransportWithDrop(tracked_global_id=99)
        shared = self._mkSharedWithTransport(transport)
        gc = _GlobalConfig()
        event_queue: queue.Queue = queue.Queue()

        sending = _mkSending(
            vision=None,  # no tracker signal at all
            cooldown_s=0.25,
            shared=shared,
            event_queue=event_queue,
            gc=gc,
        )

        # Settle timer elapsed, but cooldown has NOT — gate must stay closed.
        self.assertIsNone(sending.step())
        sending.start_time = time.time() - (CHUTE_SETTLE_MS / 1000.0) - 0.05
        self.assertIsNone(sending.step())
        self.assertFalse(shared.get_distribution_ready())

        # Advance past the cooldown — gate opens.
        sending.start_time = time.time() - (CHUTE_SETTLE_MS / 1000.0) - 0.3
        next_state = sending.step()
        self.assertEqual(DistributionState.IDLE, next_state)
        self.assertTrue(shared.get_distribution_ready())

    def test_settle_timer_still_required_before_commit(self) -> None:
        transport = self._mkTransportWithDrop(tracked_global_id=3)
        shared = self._mkSharedWithTransport(transport)
        gc = _GlobalConfig()
        event_queue: queue.Queue = queue.Queue()
        # Tracker clear, cooldown zero — the ONLY gate left is the settle
        # timer itself. Sending must not reopen before it elapses even in
        # this "perfect world" scenario.
        vision = _FakeVision(live_ids_by_role={"carousel": set()})

        sending = _mkSending(
            vision=vision,
            cooldown_s=0.0,
            shared=shared,
            event_queue=event_queue,
            gc=gc,
        )
        self.assertIsNone(sending.step())

        # Still within settle window — piece must not commit yet.
        self.assertFalse(shared.get_distribution_ready())
        self.assertEqual([], gc.run_recorder.pieces)  # commit guard holds

        # Jump past the settle timer — now it commits AND reopens.
        sending.start_time = time.time() - (CHUTE_SETTLE_MS / 1000.0) - 0.01
        next_state = sending.step()
        self.assertEqual(DistributionState.IDLE, next_state)
        self.assertTrue(shared.get_distribution_ready())


if __name__ == "__main__":
    unittest.main()
