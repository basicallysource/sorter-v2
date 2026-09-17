"""The two-piece C4 -> distribution handoff must never wedge or double-count.

Distribution holds exactly one piece (the transport's positioning slot). These
tests replay the failure seen on a production machine: a phantom track ahead of
the placed head overwrote the slot, distribution saw a drop that never
happened, the real eject then emptied the slot between Positioning finishing
and READY's first step, and READY latched "nothing" and waited forever. The C4
stall auto-resolve then dumped every following piece off the channel about
once a minute, never resetting distribution.
"""

from __future__ import annotations

import logging
import queue
import time
from types import SimpleNamespace
from unittest.mock import patch

from defs.known_object import ClassificationStatus, KnownObject, PieceStage
from piece_transport import ClassificationChannelTransport
from runtime_stats import RuntimeStatsCollector
from subsystems.classification_channel import two_piece
from subsystems.classification_channel.two_piece import (
    TwoPieceClassificationChannel,
    _Phase,
    _TrackedPiece,
)
from subsystems.distribution.idle import Idle
from subsystems.distribution.positioning import Positioning
from subsystems.distribution.ready import Ready
from subsystems.distribution.sending import CHUTE_SETTLE_MS, Sending
from subsystems.distribution.states import DistributionState
from subsystems.shared_variables import SharedVariables

_PRECISE_ZONE = 3
_LOGGER = logging.getLogger("test_c4_distribution_handoff")


class _RunRecorder:
    def __init__(self) -> None:
        self.pieces: list[KnownObject] = []

    def recordPiece(self, piece: KnownObject) -> None:
        self.pieces.append(piece)


def _mkGc() -> SimpleNamespace:
    return SimpleNamespace(
        logger=_LOGGER,
        runtime_stats=RuntimeStatsCollector(),
        run_recorder=_RunRecorder(),
        set_progress_tracker=None,
        disable_servos=False,
    )


def _mkShared(transport) -> SharedVariables:
    shared = SharedVariables()
    shared.transport = transport
    return shared


def _positioned(transport: ClassificationChannelTransport, shared: SharedVariables) -> KnownObject:
    """Place a classified piece and mark it positioned, as Positioning would."""
    obj = KnownObject(part_id="3001", color_id="1")
    obj.classification_status = ClassificationStatus.classified
    transport.placePieceForDistribution(obj)
    obj.stage = PieceStage.distributing
    shared.distribution_positioned_uuid = obj.uuid
    return obj


class _FakeWorker:
    def __init__(self, obj: KnownObject | None) -> None:
        self.ctx = SimpleNamespace(known_object=obj, classify_started_at=0.0)

    def emitKnownObject(self) -> None:
        pass

    def abandonInFlightObject(self, reason: str) -> None:
        pass


def _mkChannel(transport, shared) -> TwoPieceClassificationChannel:
    ch = TwoPieceClassificationChannel.__new__(TwoPieceClassificationChannel)
    ch.transport = transport
    ch.shared = shared
    ch.logger = _LOGGER
    ch.gc = SimpleNamespace()
    ch.irl = SimpleNamespace()
    ch.irl_config = SimpleNamespace()
    ch.cv = SimpleNamespace(_vision=None)
    ch.ctx = SimpleNamespace(reset=lambda: None, known_object=None)
    ch._pieces = {}
    ch._phase = _Phase.WAITING
    ch._eject_target = None
    ch._stage_target = None
    ch._phase_started_at = time.monotonic()
    ch.last_progress_at = time.monotonic()
    ch._multi_drop_streak = 0
    ch._multi_drop_last_ts = -1.0
    ch._multi_drop_seq = 0
    return ch


def _addPiece(
    ch: TwoPieceClassificationChannel,
    track_id: int,
    *,
    gap_to_exit: float,
    obj: KnownObject | None = None,
    placed: bool = False,
    age_s: float = 0.0,
    last_seen_ago_s: float = 0.0,
) -> _TrackedPiece:
    now = time.monotonic()
    tp = _TrackedPiece(track_id, _FakeWorker(obj), now - age_s)
    tp.zone = _PRECISE_ZONE
    tp.gap_to_exit = gap_to_exit
    tp.last_seen = now - last_seen_ago_s
    if obj is not None:
        tp.capture_done = True
        tp.result_applied = True
    tp.placed = placed
    ch._pieces[track_id] = tp
    return tp


# ------------------------------------------------------------------ distribution


def test_positioning_records_the_piece_it_aims_for() -> None:
    piece = KnownObject(part_id="3001", color_id="1")
    shared = SharedVariables()
    shared.sample_collection_mode = True
    shared.transport = SimpleNamespace(getPieceForDistributionPositioning=lambda: piece)
    layout = SimpleNamespace(layers=[])
    positioning = Positioning(
        SimpleNamespace(servos=[]),  # type: ignore[arg-type]
        _mkGc(),  # type: ignore[arg-type]
        shared,
        SimpleNamespace(),  # type: ignore[arg-type]
        layout,  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        queue.Queue(),
    )

    assert positioning.step() == DistributionState.READY
    assert shared.distribution_positioned_uuid == piece.uuid


def test_ready_sends_when_piece_was_flung_before_its_first_step() -> None:
    transport = ClassificationChannelTransport()
    shared = _mkShared(transport)
    ready = Ready(SimpleNamespace(), _mkGc(), shared)  # type: ignore[arg-type]
    obj = _positioned(transport, shared)

    # Classification steps after Positioning in the same tick and flings the
    # piece before READY ever runs. READY used to read the (now empty) slot here
    # and wait forever.
    transport.advanceTransport()

    assert ready.step() == DistributionState.SENDING
    assert transport.getPieceForDistributionDrop() is obj


def test_ready_waits_while_positioned_piece_is_still_queued() -> None:
    transport = ClassificationChannelTransport()
    shared = _mkShared(transport)
    ready = Ready(SimpleNamespace(), _mkGc(), shared)  # type: ignore[arg-type]
    _positioned(transport, shared)

    assert ready.step() is None
    assert ready.step() is None
    assert shared.distribution_ready


def test_ready_goes_idle_when_another_piece_replaces_the_positioned_one() -> None:
    transport = ClassificationChannelTransport()
    shared = _mkShared(transport)
    ready = Ready(SimpleNamespace(), _mkGc(), shared)  # type: ignore[arg-type]
    _positioned(transport, shared)
    assert ready.step() is None

    transport.placePieceForDistribution(KnownObject())

    # Nothing fell: re-evaluate instead of "sending" a drop that never happened.
    assert ready.step() == DistributionState.IDLE


def test_ready_goes_idle_when_positioned_piece_is_withdrawn() -> None:
    transport = ClassificationChannelTransport()
    shared = _mkShared(transport)
    ready = Ready(SimpleNamespace(), _mkGc(), shared)  # type: ignore[arg-type]
    obj = _positioned(transport, shared)
    assert ready.step() is None

    assert transport.clearPieceForDistribution(obj)

    assert ready.step() == DistributionState.IDLE


def test_ready_without_slot_handoff_still_treats_slot_change_as_drop() -> None:
    # Transports that do not promote the positioned piece into a drop slot (the
    # dynamic channel, the carousel) keep the old rule.
    slots = SimpleNamespace(wait=KnownObject(), drop=None)
    transport = SimpleNamespace(
        getPieceForDistributionPositioning=lambda: slots.wait,
        getPieceForDistributionDrop=lambda: slots.drop,
    )
    shared = _mkShared(transport)
    shared.distribution_positioned_uuid = slots.wait.uuid
    ready = Ready(SimpleNamespace(), _mkGc(), shared)  # type: ignore[arg-type]
    assert ready.step() is None

    slots.wait = KnownObject()

    assert ready.step() == DistributionState.SENDING


def test_sending_does_not_record_an_already_committed_piece_again() -> None:
    transport = ClassificationChannelTransport()
    previous = KnownObject()
    previous.stage = PieceStage.distributed
    previous.distributed_at = time.time() - 30.0
    transport._exit_piece = previous  # noqa: SLF001 - drop slot left from the last cycle
    shared = _mkShared(transport)
    gc = _mkGc()
    sending = Sending(SimpleNamespace(), gc, shared, queue.Queue())  # type: ignore[arg-type]

    assert sending.step() is None
    sending.start_time = time.time() - (CHUTE_SETTLE_MS / 1000.0) - 5.0

    assert sending.step() == DistributionState.IDLE
    assert gc.run_recorder.pieces == []


def test_idle_positions_again_a_piece_that_was_positioned_but_never_dropped() -> None:
    transport = ClassificationChannelTransport()
    shared = _mkShared(transport)
    _positioned(transport, shared)
    idle = Idle(SimpleNamespace(), _mkGc(), shared)  # type: ignore[arg-type]

    assert idle.step() == DistributionState.POSITIONING
    assert not shared.distribution_ready


def test_incident_hold_release_does_not_double_count_and_aims_again() -> None:
    transport = ClassificationChannelTransport()
    shared = _mkShared(transport)
    gc = _mkGc()
    previous = KnownObject()
    previous.stage = PieceStage.distributed
    previous.distributed_at = time.time() - 30.0
    transport._exit_piece = previous  # noqa: SLF001
    ready = Ready(SimpleNamespace(), gc, shared)  # type: ignore[arg-type]
    _positioned(transport, shared)
    assert ready.step() is None

    # An incident hold closes the gate; READY releases on the gate fallback.
    shared.set_distribution_gate(False, reason="incident:exit_stuck")
    assert ready.step() == DistributionState.SENDING

    sending = Sending(SimpleNamespace(), gc, shared, queue.Queue())  # type: ignore[arg-type]
    assert sending.step() is None
    sending.start_time = time.time() - (CHUTE_SETTLE_MS / 1000.0) - 5.0
    assert sending.step() == DistributionState.IDLE
    assert gc.run_recorder.pieces == []

    # The positioned piece never fell, so distribution aims for it again.
    idle = Idle(SimpleNamespace(), gc, shared)  # type: ignore[arg-type]
    assert idle.step() == DistributionState.POSITIONING


# ------------------------------------------------------------ two-piece channel


def test_track_ahead_of_placed_head_does_not_take_the_slot() -> None:
    transport = ClassificationChannelTransport()
    shared = _mkShared(transport)
    ch = _mkChannel(transport, shared)
    obj45 = _positioned(transport, shared)
    head = _addPiece(ch, 45, gap_to_exit=30.0, obj=obj45, placed=True)
    # A track that reads further forward and is old enough to be routed to misc
    # as a stray. It used to be placed over the slot.
    ghost = _addPiece(ch, 55, gap_to_exit=10.0, age_s=5.0)

    ch._aimChuteForHead(time.monotonic())

    assert transport.getPieceForDistributionPositioning() is obj45
    assert not ghost.placed
    assert ch._headPiece() is head


def test_placed_head_lost_before_eject_is_withdrawn() -> None:
    transport = ClassificationChannelTransport()
    shared = _mkShared(transport)
    ch = _mkChannel(transport, shared)
    obj = _positioned(transport, shared)
    _addPiece(ch, 7, gap_to_exit=30.0, obj=obj, placed=True, last_seen_ago_s=1.0)

    ch._retireGonePieces(time.monotonic())

    assert 7 not in ch._pieces
    assert transport.getPieceForDistributionPositioning() is None


def test_eject_target_retired_on_the_same_tick_is_still_committed() -> None:
    transport = ClassificationChannelTransport()
    shared = _mkShared(transport)
    ch = _mkChannel(transport, shared)
    obj = _positioned(transport, shared)
    tp = _addPiece(ch, 9, gap_to_exit=2.0, obj=obj, placed=True, last_seen_ago_s=1.0)
    ch._eject_target = tp
    ch._phase = _Phase.EJECTING
    now = time.monotonic()

    # A slow loop tick crosses both the retire and the eject-confirm windows:
    # _observe retires the track first, then _ejecting commits it.
    ch._retireGonePieces(now)
    assert transport.getPieceForDistributionPositioning() is obj
    ch._ejecting(SimpleNamespace(), True, now)

    assert transport.getPieceForDistributionDrop() is obj
    assert transport.getPieceForDistributionPositioning() is None
    assert tp.ejected


def test_stall_auto_clear_withdraws_a_placed_piece_that_was_never_aimed() -> None:
    transport = ClassificationChannelTransport()
    shared = _mkShared(transport)
    ch = _mkChannel(transport, shared)
    obj = KnownObject()
    transport.placePieceForDistribution(obj)  # placed, distribution never positioned it
    _addPiece(ch, 3, gap_to_exit=20.0, obj=obj, placed=True)
    cleared = SimpleNamespace(cleared=True, output_deg_moved=288.0, reason="cleared")

    with patch.object(two_piece, "clearChannelByAdvancing", return_value=cleared):
        ch.attemptStallAutoClear(max_output_deg=720.0)

    assert transport.getPieceForDistributionDrop() is None
    assert transport.getPieceForDistributionPositioning() is None
    assert ch._pieces == {}


def test_stall_auto_clear_commits_a_placed_head_whose_chute_is_aimed() -> None:
    transport = ClassificationChannelTransport()
    shared = _mkShared(transport)
    ch = _mkChannel(transport, shared)
    obj = _positioned(transport, shared)
    _addPiece(ch, 3, gap_to_exit=20.0, obj=obj, placed=True)
    cleared = SimpleNamespace(cleared=True, output_deg_moved=144.0, reason="cleared")

    with patch.object(two_piece, "clearChannelByAdvancing", return_value=cleared):
        ch.attemptStallAutoClear(max_output_deg=720.0)

    assert transport.getPieceForDistributionDrop() is obj
    assert transport.getPieceForDistributionPositioning() is None


def test_cleanup_withdraws_the_placed_piece() -> None:
    transport = ClassificationChannelTransport()
    shared = _mkShared(transport)
    ch = _mkChannel(transport, shared)
    obj = _positioned(transport, shared)
    _addPiece(ch, 3, gap_to_exit=20.0, obj=obj, placed=True)

    ch.cleanup()

    assert transport.getPieceForDistributionPositioning() is None


def test_phantom_ahead_then_real_eject_does_not_wedge_distribution() -> None:
    """Replay of the production wedge, end to end across both sides."""
    transport = ClassificationChannelTransport()
    shared = _mkShared(transport)
    gc = _mkGc()
    ch = _mkChannel(transport, shared)
    ready = Ready(SimpleNamespace(), gc, shared)  # type: ignore[arg-type]

    obj45 = _positioned(transport, shared)
    head = _addPiece(ch, 45, gap_to_exit=30.0, obj=obj45, placed=True)
    assert ready.step() is None  # READY, chute aimed for 45

    _addPiece(ch, 55, gap_to_exit=10.0, age_s=5.0)  # phantom ahead of the head
    ch._aimChuteForHead(time.monotonic())
    assert ready.step() is None  # no false "piece dropped"

    ch._pieces.pop(55)  # the phantom disappears
    ch._eject_target = head
    ch._phase = _Phase.EJECTING
    head.last_seen = time.monotonic() - 1.0  # 45 falls off the platter
    ch._ejecting(SimpleNamespace(), True, time.monotonic())

    assert ready.step() == DistributionState.SENDING
    sending = Sending(SimpleNamespace(), gc, shared, queue.Queue())  # type: ignore[arg-type]
    assert sending.step() is None
    sending.start_time = time.time() - (CHUTE_SETTLE_MS / 1000.0) - 5.0
    assert sending.step() == DistributionState.IDLE
    assert gc.run_recorder.pieces == [obj45]
