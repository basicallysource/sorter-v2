from __future__ import annotations

from concurrent.futures import Future

from rt.contracts.events import Event
from rt.events.topics import C3_HANDOFF_TRIGGER
from rt.services.sector_carousel import (
    DISCARD_ROUTE,
    SectorCarouselHandler,
    SlotContaminationState,
    SlotPhase,
)


class _Distributor:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.commits: list[str] = []
        self.ready = False

    def handoff_request(self, **kwargs) -> bool:
        self.requests.append(kwargs)
        return True

    def pending_ready(self, piece_uuid: str | None = None) -> bool:
        return self.ready

    def handoff_commit(self, piece_uuid: str, now_mono: float | None = None) -> bool:
        self.commits.append(piece_uuid)
        return True


def _mark_ready_to_leave(handler: SectorCarouselHandler) -> None:
    for slot in handler.slots:
        if slot.phase is SlotPhase.CAPTURING:
            slot.capture_done = True
        elif slot.phase is SlotPhase.CLASSIFYING:
            slot.classification = f"class-{slot.piece_uuid}"
        elif slot.phase is SlotPhase.AWAITING_DIST:
            slot.distributor_ready = True
        elif slot.phase is SlotPhase.DROPPING:
            slot.ejected = True


def _rotate_ready(handler: SectorCarouselHandler, now_mono: float) -> bool:
    _mark_ready_to_leave(handler)
    return handler.rotate_one_sector(now_mono=now_mono)


def test_inject_at_slot1_starts_capture() -> None:
    captures: list[str] = []
    handler = SectorCarouselHandler(capture_start=lambda uuid, _slot: captures.append(uuid))
    handler.enable()

    assert handler.inject_at_slot1("piece-1", now_mono=1.0)

    snap = handler.snapshot(now_mono=1.0)
    slot1 = snap["slots"][0]
    assert slot1["slot_index"] == 1
    assert slot1["piece_uuid"] == "piece-1"
    assert slot1["phase"] == SlotPhase.CAPTURING.value
    assert captures == ["piece-1"]


def test_rotation_moves_payload_to_next_slot_phase() -> None:
    moves: list[float] = []
    handler = SectorCarouselHandler(
        c4_transport=lambda deg: moves.append(deg) or True,
        sector_step_deg=2.0,
        rotation_chunk_deg=2.0,
    )
    handler.enable()
    handler.inject_at_slot1("piece-1", now_mono=1.0)
    _mark_ready_to_leave(handler)

    assert handler.rotate_one_sector(now_mono=2.0)

    snap = handler.snapshot(now_mono=2.0)
    assert moves == [2.0]
    assert snap["slots"][1]["piece_uuid"] == "piece-1"
    assert snap["slots"][1]["phase"] == SlotPhase.SETTLING.value
    assert snap["slots"][1]["physical_sector_id"] == 0
    assert snap["slots"][1]["station_index"] == 2


def test_rotation_can_split_large_sector_step_into_chunks() -> None:
    moves: list[float] = []
    handler = SectorCarouselHandler(
        c4_transport=lambda deg: moves.append(deg) or True,
        sector_step_deg=6.0,
        rotation_chunk_deg=2.0,
        rotation_chunk_settle_s=0.0,
    )
    handler.enable()
    handler.inject_at_slot1("piece-1", now_mono=1.0)
    _mark_ready_to_leave(handler)

    assert handler.rotate_one_sector(now_mono=2.0)

    assert moves == [2.0, 2.0, 2.0]


def test_drop_slot_blocks_rotation_until_ejected() -> None:
    handler = SectorCarouselHandler(rotation_chunk_settle_s=0.0, settle_s=0.0)
    handler.enable()
    handler.inject_at_slot1("piece-1", now_mono=1.0)
    for ts in (2.0, 3.0, 4.0, 5.0):
        assert _rotate_ready(handler, ts)

    assert not handler.rotate_one_sector(now_mono=6.0)
    assert handler.snapshot(now_mono=6.0)["blocked"] == "eject_pending"


def test_classify_and_distributor_lifecycle() -> None:
    future: Future[str] = Future()
    dist = _Distributor()
    handler = SectorCarouselHandler(
        distributor_port=dist,
        classifier_submit=lambda _slot: future,
        rotation_chunk_settle_s=0.0,
        settle_s=0.0,
    )
    handler.enable()
    handler.inject_at_slot1("piece-1", now_mono=1.0)
    _rotate_ready(handler, now_mono=2.0)
    _rotate_ready(handler, now_mono=3.0)

    handler.tick(3.1)
    future.set_result("brick")
    handler.tick(3.2)
    assert handler.snapshot(now_mono=3.2)["slots"][2]["classification_present"]

    handler.rotate_one_sector(now_mono=4.0)
    handler.tick(4.1)
    assert dist.requests[0]["piece_uuid"] == "piece-1"
    assert dist.requests[0]["dossier"]["distributor_request_id"] is not None
    dist.ready = True
    handler.tick(4.2)
    assert handler.snapshot(now_mono=4.2)["slots"][3]["distributor_ready"]


def test_distributor_gate_blocks_until_ready() -> None:
    dist = _Distributor()
    handler = SectorCarouselHandler(
        distributor_port=dist,
        rotation_chunk_settle_s=0.0,
        settle_s=0.0,
    )
    handler.enable()
    handler.inject_at_slot1("piece-1", now_mono=1.0)
    _rotate_ready(handler, now_mono=2.0)
    _rotate_ready(handler, now_mono=3.0)
    handler.bind_classification("piece-1", "brick", now_mono=3.1)
    handler.rotate_one_sector(now_mono=4.0)
    handler.tick(4.1)

    assert dist.requests[0]["piece_uuid"] == "piece-1"
    assert not handler.rotate_one_sector(now_mono=4.2)
    gates = handler.gate_status(now_mono=4.2, include_cooldown=False)
    assert gates["slots"][3]["reason"] == "distributor_pending"

    dist.ready = True
    handler.tick(4.3)

    assert handler.rotate_one_sector(now_mono=4.4)


def test_bind_classification_rejects_stale_request_id() -> None:
    handler = SectorCarouselHandler()
    handler.enable()
    handler.inject_at_slot1("piece-1", now_mono=1.0)
    slot = handler.slots[0]
    slot.classifier_request_id = "current-request"

    assert not handler.bind_classification(
        "piece-1",
        "brick",
        request_id="old-request",
        now_mono=2.0,
    )
    assert handler.snapshot(now_mono=2.0)["slots"][0]["classification_present"] is False
    assert handler.snapshot(now_mono=2.0)["counters"]["stale_classifier_results"] == 1


def test_c3_handoff_event_injects_slot1() -> None:
    handler = SectorCarouselHandler()
    handler.enable()
    lease_id = handler.request_lease(
        predicted_arrival_in_s=0.6,
        min_spacing_deg=30.0,
        now_mono=9.5,
        track_global_id=7,
    )
    assert lease_id is not None
    handler.on_c3_handoff_trigger(
        Event(
            topic=C3_HANDOFF_TRIGGER,
            payload={
                "piece_uuid": "piece-1",
                "landing_lease_id": lease_id,
                "c3_eject_ts": 11.0,
                "expected_arrival_window_s": [0.4, 0.9],
            },
            source="test",
            ts_mono=10.0,
        )
    )

    slot1 = handler.snapshot(now_mono=10.0)["slots"][0]
    assert slot1["piece_uuid"] == "piece-1"
    assert slot1["phase"] == SlotPhase.CAPTURING.value
    assert slot1["extras"]["c3_eject_ts"] == 11.0
    assert slot1["extras"]["landing_lease_id"] == lease_id


def test_c3_handoff_event_without_lease_is_rejected() -> None:
    handler = SectorCarouselHandler()
    handler.enable()

    handler.on_c3_handoff_trigger(
        Event(
            topic=C3_HANDOFF_TRIGGER,
            payload={"piece_uuid": "piece-1"},
            source="test",
            ts_mono=10.0,
        )
    )

    snap = handler.snapshot(now_mono=10.0)
    assert snap["slots"][0]["piece_uuid"] is None
    assert snap["blocked"] == "handoff_missing_landing_lease"
    assert snap["counters"]["handoff_events_rejected"] == 1


def test_landing_lease_blocks_when_slot1_reserved() -> None:
    handler = SectorCarouselHandler()
    handler.enable()
    assert handler.request_lease(
        predicted_arrival_in_s=0.6,
        min_spacing_deg=30.0,
        now_mono=1.0,
    )
    assert handler.request_lease(
        predicted_arrival_in_s=0.6,
        min_spacing_deg=30.0,
        now_mono=1.1,
    ) is None
    snap = handler.snapshot(now_mono=1.1)
    assert snap["blocked"] == "landing_lease_pending"
    assert snap["pending_landing_leases"] == 1


def test_dropping_slot_ejects_and_commits() -> None:
    ejects: list[bool] = []
    dist = _Distributor()
    dist.ready = True
    handler = SectorCarouselHandler(
        c4_eject=lambda: ejects.append(True) or True,
        distributor_port=dist,
        rotation_chunk_settle_s=0.0,
        settle_s=0.0,
    )
    handler.enable()
    handler.inject_at_slot1("piece-1", now_mono=1.0)
    for ts in (2.0, 3.0, 4.0, 5.0):
        _rotate_ready(handler, ts)
    slot5 = handler.slots[4]
    slot5.classification = "brick"
    slot5.distributor_requested = True
    slot5.distributor_ready = True

    handler.tick(5.1)

    assert ejects == [True]
    assert dist.commits == ["piece-1"]
    slot5 = handler.snapshot(now_mono=5.1)["slots"][4]
    assert slot5["ejected"]
    assert slot5["phase"] == SlotPhase.DROPPED_PENDING_CLEAR.value
    assert slot5["clear_pending_next_rotate"]


def test_phase_verification_blocks_rotation_until_verified() -> None:
    moves: list[float] = []
    handler = SectorCarouselHandler(
        c4_transport=lambda deg: moves.append(deg) or True,
        require_phase_verification=True,
        sector_step_deg=2.0,
        rotation_chunk_deg=2.0,
        rotation_chunk_settle_s=0.0,
    )
    handler.enable()
    handler.inject_at_slot1("piece-1", now_mono=1.0)
    _mark_ready_to_leave(handler)

    assert handler.rotate_one_sector(now_mono=2.0) is False
    snap = handler.status_snapshot(now_mono=2.0)
    assert snap["phase_verified"] is False
    assert snap["auto_rotate_allowed"] is False
    assert snap["blocked"] == "phase_verification_required"
    assert moves == []

    handler.verify_phase(source="test", measured_offset_deg=12.0, now_mono=2.1)

    assert handler.rotate_one_sector(now_mono=2.2) is True
    assert moves == [2.0]


def test_gate_status_reports_blocking_slot_reason() -> None:
    handler = SectorCarouselHandler(settle_s=0.0, rotation_chunk_settle_s=0.0)
    handler.enable()
    handler.inject_at_slot1("piece-1", now_mono=1.0)
    _rotate_ready(handler, now_mono=2.0)
    _rotate_ready(handler, now_mono=3.0)

    gates = handler.gate_status(now_mono=3.1, include_cooldown=False)

    assert gates["can_rotate"] is False
    assert gates["slots"][2]["gate"] == "classification"
    assert gates["slots"][2]["reason"] == "classification_pending"
    assert any(reason["reason"] == "classification_pending" for reason in gates["reasons"])


def test_invariant_status_detects_duplicate_piece_uuid() -> None:
    handler = SectorCarouselHandler()
    handler.enable()
    handler.slots[0].piece_uuid = "same"
    handler.slots[0].phase = SlotPhase.CAPTURING
    handler.slots[1].piece_uuid = "same"
    handler.slots[1].phase = SlotPhase.SETTLING

    status = handler.invariant_status(now_mono=1.0)

    assert status["ok"] is False
    assert any(item["code"] == "duplicate_piece_uuid" for item in status["violations"])


def test_double_drop_routes_to_discard_and_bypasses_distributor() -> None:
    ejects: list[bool] = []
    dist = _Distributor()
    handler = SectorCarouselHandler(
        c4_eject=lambda: ejects.append(True) or True,
        distributor_port=dist,
        settle_s=0.0,
        rotation_chunk_settle_s=0.0,
    )
    handler.enable()
    handler.inject_at_slot1("piece-1", now_mono=1.0)

    assert handler.mark_double_drop(
        "piece-1",
        observed_count_estimate=2,
        now_mono=1.1,
    )
    slot1 = handler.snapshot(now_mono=1.1)["slots"][0]
    assert slot1["contamination_state"] == SlotContaminationState.CONFIRMED_MULTI.value
    assert slot1["final_route"] == DISCARD_ROUTE
    assert slot1["reject_reason"] == "c3_double_drop"

    handler.slots[0].capture_done = True
    assert handler.rotate_one_sector(now_mono=2.0)
    assert handler.rotate_one_sector(now_mono=3.0)
    assert handler.rotate_one_sector(now_mono=4.0)
    handler.tick(4.1)

    slot4 = handler.snapshot(now_mono=4.1)["slots"][3]
    assert slot4["distributor_ready"] is True
    assert slot4["extras"]["distributor_mode"] == "bypass_for_discard"
    assert dist.requests == []

    assert handler.rotate_one_sector(now_mono=5.0)
    handler.tick(5.1)

    snap = handler.snapshot(now_mono=5.1)
    assert ejects == [True]
    assert snap["slots"][4]["ejected"] is True
    assert snap["counters"]["discarded_slots"] == 1
    assert snap["counters"]["c3_double_drop_count"] == 1
    assert snap["counters"]["estimated_extra_parts"] == 1


def test_late_double_drop_overrides_normal_classification() -> None:
    handler = SectorCarouselHandler(settle_s=0.0, rotation_chunk_settle_s=0.0)
    handler.enable()
    handler.inject_at_slot1("piece-1", now_mono=1.0)
    _rotate_ready(handler, now_mono=2.0)
    _rotate_ready(handler, now_mono=3.0)

    assert handler.bind_classification("piece-1", "brick", now_mono=3.1)
    assert handler.mark_double_drop(
        "piece-1",
        observed_count_estimate=2,
        now_mono=3.2,
    )

    slot = handler.snapshot(now_mono=3.2)["slots"][2]
    assert slot["classification_present"] is True
    assert slot["normal_classification_present"] is True
    assert slot["final_route"] == DISCARD_ROUTE
    assert slot["reject_reason"] == "c3_double_drop"
    assert handler.rotate_one_sector(now_mono=4.0)


def test_classifier_multi_object_result_routes_to_discard() -> None:
    handler = SectorCarouselHandler(settle_s=0.0, rotation_chunk_settle_s=0.0)
    handler.enable()
    handler.inject_at_slot1("piece-1", now_mono=1.0)
    _rotate_ready(handler, now_mono=2.0)
    _rotate_ready(handler, now_mono=3.0)

    assert handler.bind_classification(
        "piece-1",
        {"label": "brick", "object_count_estimate": 2},
        now_mono=3.1,
    )

    slot = handler.snapshot(now_mono=3.1)["slots"][2]
    assert slot["contamination_state"] == SlotContaminationState.CONFIRMED_MULTI.value
    assert slot["final_route"] == DISCARD_ROUTE
    assert slot["reject_reason"] == "multi_object"
    assert slot["observed_count_estimate"] == 2


def test_spillover_suspected_blocks_rotation() -> None:
    handler = SectorCarouselHandler(settle_s=0.0, rotation_chunk_settle_s=0.0)
    handler.enable()
    handler.inject_at_slot1("piece-1", now_mono=1.0)
    handler.slots[0].capture_done = True

    assert handler.mark_slot_contaminated(
        "piece-1",
        state=SlotContaminationState.SPILL_SUSPECTED,
        reject_reason="spillover",
        observed_count_estimate=None,
        now_mono=1.1,
    )

    assert not handler.rotate_one_sector(now_mono=2.0)
    snap = handler.status_snapshot(now_mono=2.0)
    assert snap["blocked"] == "spillover_suspected"
    assert any(reason["reason"] == "spillover_suspected" for reason in snap["gates"]["reasons"])
    assert snap["invariants"]["ok"] is True


def test_distributor_ready_callback_rejects_stale_result() -> None:
    dist = _Distributor()
    handler = SectorCarouselHandler(
        distributor_port=dist,
        settle_s=0.0,
        rotation_chunk_settle_s=0.0,
    )
    handler.enable()
    handler.inject_at_slot1("piece-1", now_mono=1.0)
    _rotate_ready(handler, now_mono=2.0)
    _rotate_ready(handler, now_mono=3.0)
    handler.bind_classification("piece-1", "brick", now_mono=3.1)
    handler.rotate_one_sector(now_mono=4.0)
    handler.tick(4.1)
    request_id = handler.slots[3].distributor_request_id

    assert not handler.bind_distributor_ready(
        "piece-1",
        request_id="old-request",
        now_mono=4.2,
    )
    assert handler.snapshot(now_mono=4.2)["counters"]["stale_distributor_results"] == 1

    assert handler.bind_distributor_ready(
        "piece-1",
        request_id=request_id,
        now_mono=4.3,
    )
    assert handler.snapshot(now_mono=4.3)["slots"][3]["distributor_ready"] is True


def test_five_token_ring_preserves_piece_classifications() -> None:
    dropped: list[tuple[str, str]] = []
    classifications = {
        "A": "class_red",
        "B": "class_blue",
        "C": "class_green",
        "D": "class_yellow",
        "E": "class_reject",
    }
    handler = SectorCarouselHandler(
        c4_eject=lambda: True,
        settle_s=0.0,
        rotation_chunk_settle_s=0.0,
    )
    handler.enable()

    def mark_ready() -> None:
        for slot in handler.slots:
            if not slot.occupied:
                continue
            if slot.phase is SlotPhase.CAPTURING:
                slot.capture_done = True
            elif slot.phase is SlotPhase.CLASSIFYING:
                slot.classification = classifications[str(slot.piece_uuid)]
            elif slot.phase is SlotPhase.AWAITING_DIST:
                slot.distributor_ready = True
            elif slot.phase is SlotPhase.DROPPING:
                dropped.append((str(slot.piece_uuid), str(slot.classification)))
                handler.tick(float(len(dropped)) + 100.0)

    pieces = list(classifications)
    next_piece = 0
    now = 1.0
    while next_piece < len(pieces) or any(slot.occupied for slot in handler.slots):
        if next_piece < len(pieces) and not handler.slots[0].occupied:
            assert handler.inject_at_slot1(pieces[next_piece], now_mono=now)
            next_piece += 1
        mark_ready()
        assert handler.invariant_status(now_mono=now)["ok"] is True
        if any(slot.occupied for slot in handler.slots):
            assert handler.rotate_one_sector(now_mono=now + 0.1)
        now += 1.0

    assert dropped == [
        ("A", "class_red"),
        ("B", "class_blue"),
        ("C", "class_green"),
        ("D", "class_yellow"),
        ("E", "class_reject"),
    ]
    assert handler.invariant_status(now_mono=now)["ok"] is True
