from __future__ import annotations

import logging
import time
from collections import deque
from types import SimpleNamespace

from defs.known_object import ClassificationStatus, KnownObject, PieceStage
from piece_cycles import CycleRecorder
from piece_transport import ClassificationChannelTransport
from perception.state import ChannelState, PieceObservation
from runtime_stats import RuntimeStatsCollector
from subsystems.classification_channel.two_piece import flow as two_piece
from subsystems.classification_channel.two_piece.flow import (
    TwoPieceClassificationChannel,
    _Phase,
)
from subsystems.shared_variables import SharedVariables

DROP = two_piece._ZONE_DROP
NONE = two_piece._ZONE_NONE
_LOGGER = logging.getLogger("test_c4_edge_landing")


class _Worker:
    def __init__(self) -> None:
        self.ctx = SimpleNamespace(
            known_object=None,
            classify_started_at=0.0,
            capturing_started_at=0.0,
            captured_crops=[],
        )

    def emitKnownObject(self) -> None:
        pass

    def abandonInFlightObject(self, reason: str) -> None:
        pass

    def burstCaptureComplete(self, ctx, now: float) -> tuple[bool, str]:
        return False, "collecting"


def _channel(*, stopped: bool = True) -> TwoPieceClassificationChannel:
    transport = ClassificationChannelTransport()
    shared = SharedVariables()
    shared.transport = transport
    ch = TwoPieceClassificationChannel.__new__(TwoPieceClassificationChannel)
    ch.transport, ch.shared, ch.logger = transport, shared, _LOGGER
    ch.gc = SimpleNamespace(logger=_LOGGER, runtime_stats=RuntimeStatsCollector())
    ch.irl = SimpleNamespace(carousel_stepper=SimpleNamespace(stopped=stopped))
    ch.ctx = SimpleNamespace(
        config=SimpleNamespace(multi_feed_confirm_reads=3), reset=lambda: None, known_object=None
    )
    ch._pieces = {}
    ch._lost, ch._last_step_at, ch._turned_at = [], None, 0.0
    ch._rotation_started_at = 0.0
    ch._pair_until, ch._pair_group = 0.0, None
    ch._phase = _Phase.WAITING
    ch._eject_target = ch._stage_target = None
    ch._phase_started_at = time.monotonic()
    ch.last_progress_at = time.monotonic()
    ch._multi_drop_streak, ch._multi_drop_last_ts, ch._multi_drop_seq = 0, -1.0, 0
    ch._recent_ejects = deque(maxlen=16)
    ch._bucket_hold_cycles = 0
    ch._cycles = CycleRecorder()
    ch._was_ready, ch._ready_since = False, None
    ch._createPiece = lambda tid, now: ch._pieces.setdefault(
        tid, two_piece._TrackedPiece(tid, _Worker(), now)
    )
    return ch


def _piece(
    track_id: int,
    *,
    zone: int = NONE,
    box_in_drop: bool = True,
    gap: float = 210.0,
    x: int = 1000,
) -> PieceObservation:
    return PieceObservation(
        com_forward_to_exit_deg=gap,
        com_section=0,
        zone_code=zone,
        bbox=(x, 500, x + 100, 600),
        sv_bt_track_id=track_id,
        box_in_drop=box_in_drop,
    )


def _frame(now: float, *pieces: PieceObservation, in_drop: bool = True) -> ChannelState:
    return ChannelState(
        ts=now,
        in_drop=in_drop,
        in_exit=False,
        n_pieces=len(pieces),
        pieces=pieces,
    )


def test_edge_landed_piece_is_photographed_and_never_treated_as_stray(caplog) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER.name)
    ch = _channel()
    now = time.monotonic()
    state = _frame(now, _piece(42))

    ch._observe(state, now, stopped=True)

    tp = ch._pieces[42]
    assert tp.edge_landed
    assert ch._dropPiece() is tp
    assert tp.zone == DROP
    assert any(
        record.message
        == "[C4-2PIECE] track=42 landed on the drop zone edge; photographing it there"
        for record in caplog.records
    )

    perception = SimpleNamespace(read_bboxes_and_frame=lambda channel: ([], object()))
    ch._cropBurstFrame = lambda worker, bbox, frame: None
    ch._captureDropPieces(perception, now)

    assert tp.known_object is not None
    assert tp.worker.ctx.capturing_started_at == now
    ch._aimChuteForHead(now + two_piece._STRAY_MISC_S + 1.0)
    assert not tp.result_applied
    assert not tp.known_object.problems
    assert not any("stray head" in record.message for record in caplog.records)


def test_ready_head_is_not_ejected_while_an_edge_piece_is_uncaptured() -> None:
    ch = _channel()
    now = time.monotonic()
    obj = KnownObject(part_id="3001", color_id="5")
    obj.stage = PieceStage.distributing
    head = two_piece._TrackedPiece(47, _Worker(), now - 1.0)
    head.zone = two_piece._ZONE_PRECISE
    head.gap_to_exit = 40.0
    head.placed = True
    head.worker.ctx.known_object = obj
    ch._pieces[head.track_id] = head
    ch.shared.distribution_ready = True
    ch._ready_since = now - 3.1
    state = _frame(now, _piece(48))

    ch._observe(state, now, stopped=True)
    ch._maybeStartRotation(state)

    assert ch._phase == _Phase.WAITING
    assert ch._eject_target is None
    assert ch._dropPiece() is ch._pieces[48]


def test_captured_edge_piece_is_staged_with_the_ready_head() -> None:
    ch = _channel()
    now = time.monotonic()
    head = two_piece._TrackedPiece(50, _Worker(), now)
    head.zone = two_piece._ZONE_PRECISE
    head.gap_to_exit = 40.0
    ch._pieces[head.track_id] = head
    state = _frame(now, _piece(51))

    ch._observe(state, now, stopped=True)
    edge = ch._pieces[51]
    edge.worker.burstCaptureComplete = lambda ctx, current: (True, "done")
    ch._cropBurstFrame = lambda worker, bbox, frame: None
    perception = SimpleNamespace(read_bboxes_and_frame=lambda channel: ([], object()))
    ch._captureDropPieces(perception, now)

    assert edge.capture_done
    assert edge.edge_landed
    assert edge.zone == DROP
    ch._maybeStartRotation(state)
    assert ch._phase == _Phase.WAITING

    obj = KnownObject(part_id="3001", color_id="5")
    obj.stage = PieceStage.distributing
    obj.classification_status = ClassificationStatus.classified
    head.worker.ctx.known_object = obj
    head.placed = True
    head.result_applied = True
    ch.shared.distribution_ready = True
    ch._maybeStartRotation(state)

    assert ch._phase == _Phase.EJECTING
    assert ch._eject_target is head
    assert ch._stage_target is edge


def test_edge_landed_status_clears_after_waiting_and_does_not_return() -> None:
    ch = _channel()
    created_at = time.monotonic()
    ch._observe(_frame(created_at, _piece(52)), created_at, stopped=True)
    tp = ch._pieces[52]
    assert tp.edge_landed and tp.zone == DROP

    staging_at = created_at + 0.1
    ch._phase = _Phase.STAGING
    ch._observe(_frame(staging_at, _piece(52)), staging_at, stopped=True)
    assert not tp.edge_landed
    assert tp.zone == NONE

    waiting_at = created_at + 0.2
    ch._phase = _Phase.WAITING
    ch._phase_started_at = waiting_at
    ch._observe(_frame(waiting_at, _piece(52)), waiting_at, stopped=True)
    assert not tp.edge_landed
    assert tp.zone == NONE


def test_side_by_side_edge_landings_are_a_double_feed() -> None:
    ch = _channel()
    now = time.monotonic()
    state = _frame(
        now,
        _piece(53, gap=210.0, x=1000),
        _piece(54, gap=208.0, x=1130),
    )

    ch._observe(state, now, stopped=True)

    left, right = ch._pieces[53], ch._pieces[54]
    assert left.edge_landed and right.edge_landed
    assert left.double_feed and right.double_feed
    assert left.multi_drop_group == right.multi_drop_group


def test_a_bbox_outside_the_drop_zone_does_not_override_its_center_zone() -> None:
    ch = _channel()
    now = time.monotonic()

    ch._observe(_frame(now, _piece(43, box_in_drop=False), in_drop=False), now, stopped=True)

    tp = ch._pieces[43]
    assert not tp.edge_landed
    assert tp.zone == NONE
    assert ch._dropPiece() is None


def test_edge_landing_requires_waiting_and_a_stopped_stepper() -> None:
    for phase, stopped in ((_Phase.STAGING, True), (_Phase.WAITING, False)):
        ch = _channel(stopped=stopped)
        ch._phase = phase
        now = time.monotonic()

        ch._observe(_frame(now, _piece(44)), now, stopped=stopped)

        tp = ch._pieces[44]
        assert not tp.edge_landed
        assert tp.zone == NONE
        assert ch._dropPiece() is None


def test_an_already_captured_piece_is_not_overridden() -> None:
    ch = _channel()
    now = time.monotonic()
    tp = ch._createPiece(45, now)
    tp.capture_done = True

    ch._observe(_frame(now, _piece(45)), now, stopped=True)

    assert not tp.edge_landed
    assert tp.zone == NONE
    assert ch._dropPiece() is None


def test_ready_head_waits_2_5_seconds_then_ejects_alone_at_3_1_seconds(caplog) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER.name)
    ch = _channel()
    obj = KnownObject(part_id="3001", color_id="5")
    obj.stage = PieceStage.distributing
    obj.classification_status = ClassificationStatus.classified
    head = two_piece._TrackedPiece(46, _Worker(), time.monotonic())
    head.zone = two_piece._ZONE_PRECISE
    head.gap_to_exit = 40.0
    head.placed = True
    head.result_applied = True
    head.worker.ctx.known_object = obj
    ch._pieces[head.track_id] = head
    ch.shared.distribution_ready = True
    ch._ready_since = time.monotonic() - 2.5

    assert ch._dropPiece() is None
    ch._maybeStartRotation()
    assert ch._phase == _Phase.WAITING

    ch._ready_since = time.monotonic() - 3.1
    ch._maybeStartRotation()

    assert ch._phase == _Phase.EJECTING
    assert ch._eject_target is head
    assert any("alone" in record.message for record in caplog.records)


def test_blocked_drop_zone_uses_12_second_head_alone_fallback(caplog) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER.name)
    ch = _channel()
    obj = KnownObject(part_id="3001", color_id="5")
    obj.stage = PieceStage.distributing
    obj.classification_status = ClassificationStatus.classified
    head = two_piece._TrackedPiece(49, _Worker(), time.monotonic())
    head.zone = two_piece._ZONE_PRECISE
    head.gap_to_exit = 40.0
    head.placed = True
    head.result_applied = True
    head.worker.ctx.known_object = obj
    ch._pieces[head.track_id] = head
    ch.shared.distribution_ready = True
    state = SimpleNamespace(in_drop=True)

    assert ch._dropPiece() is None
    ch._ready_since = time.monotonic() - 3.1
    ch._maybeStartRotation(state)
    assert ch._phase == _Phase.WAITING

    ch._ready_since = time.monotonic() - 12.1
    ch._maybeStartRotation(state)

    assert ch._phase == _Phase.EJECTING
    assert ch._eject_target is head
    assert any(
        "(no next piece for 12 s)" in record.message for record in caplog.records
    )
