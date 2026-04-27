from __future__ import annotations

from concurrent.futures import Future

from rt.contracts.events import Event
from rt.events.topics import C3_HANDOFF_TRIGGER
from rt.services.sector_carousel import SectorCarouselHandler, SlotPhase


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
