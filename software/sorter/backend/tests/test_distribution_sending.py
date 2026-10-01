from __future__ import annotations

import queue
import time
import unittest

from defs.known_object import KnownObject
from piece_transport import ClassificationChannelTransport
from runtime_stats import RuntimeStatsCollector
from subsystems.bus import TickBus
from subsystems.distribution.sending import (
    CHUTE_SETTLE_MS,
    MISSING_DROP_PIECE_GRACE_MS,
    Sending,
)
from subsystems.distribution.states import DistributionState
from subsystems.shared_variables import SharedVariables


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


class _GlobalConfig:
    def __init__(self) -> None:
        self.logger = _Logger()
        self.runtime_stats = RuntimeStatsCollector()
        self.run_recorder = _RunRecorder()
        self.set_progress_tracker = None
        self.disable_servos = False


def _mkSending(
    *,
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
        post_distribute_cooldown_s=cooldown_s,
    )


class SendingChuteReopenGateTests(unittest.TestCase):
    def _mkTransportWithDrop(self, *, tracked_global_id: int) -> ClassificationChannelTransport:
        transport = ClassificationChannelTransport()
        # Manually stage a piece into the exit buffer so
        # ``getPieceForDistributionDrop`` returns it without exercising
        # the state machine pipeline.
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


    def test_gate_waits_for_settle_and_cooldown(self) -> None:
        transport = self._mkTransportWithDrop(tracked_global_id=99)
        shared = self._mkSharedWithTransport(transport)
        gc = _GlobalConfig()
        event_queue: queue.Queue = queue.Queue()

        sending = _mkSending(
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

        sending = _mkSending(
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

    def test_missing_drop_piece_reopens_after_grace(self) -> None:
        transport = ClassificationChannelTransport()
        shared = self._mkSharedWithTransport(transport)
        gc = _GlobalConfig()
        event_queue: queue.Queue = queue.Queue()
        sending = _mkSending(
            cooldown_s=0.0,
            shared=shared,
            event_queue=event_queue,
            gc=gc,
        )

        self.assertIsNone(sending.step())
        sending.start_time = (
            time.time() - (MISSING_DROP_PIECE_GRACE_MS / 1000.0) - 0.01
        )

        next_state = sending.step()
        self.assertEqual(DistributionState.IDLE, next_state)
        self.assertTrue(shared.get_distribution_ready())


if __name__ == "__main__":
    unittest.main()
