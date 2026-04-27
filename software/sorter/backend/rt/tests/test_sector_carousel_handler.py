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

    assert handler.rotate_one_sector(now_mono=2.0)

    snap = handler.snapshot(now_mono=2.0)
    assert moves == [2.0]
    assert snap["slots"][1]["piece_uuid"] == "piece-1"
    assert snap["slots"][1]["phase"] == SlotPhase.SETTLING.value


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

    assert handler.rotate_one_sector(now_mono=2.0)

    assert moves == [2.0, 2.0, 2.0]


def test_drop_slot_blocks_rotation_until_ejected() -> None:
    handler = SectorCarouselHandler(rotation_chunk_settle_s=0.0)
    handler.enable()
    handler.inject_at_slot1("piece-1", now_mono=1.0)
    for ts in (2.0, 3.0, 4.0, 5.0):
        assert handler.rotate_one_sector(now_mono=ts)

    assert not handler.rotate_one_sector(now_mono=6.0)
    assert handler.snapshot(now_mono=6.0)["blocked"] == "drop_slot_occupied"


def test_classify_and_distributor_lifecycle() -> None:
    future: Future[str] = Future()
    dist = _Distributor()
    handler = SectorCarouselHandler(
        distributor_port=dist,
        classifier_submit=lambda _slot: future,
        rotation_chunk_settle_s=0.0,
    )
    handler.enable()
    handler.inject_at_slot1("piece-1", now_mono=1.0)
    handler.rotate_one_sector(now_mono=2.0)
    handler.rotate_one_sector(now_mono=3.0)

    handler.tick(3.1)
    future.set_result("brick")
    handler.tick(3.2)
    assert handler.snapshot(now_mono=3.2)["slots"][2]["classification_present"]

    handler.rotate_one_sector(now_mono=4.0)
    handler.tick(4.1)
    assert dist.requests[0]["piece_uuid"] == "piece-1"
    dist.ready = True
    handler.tick(4.2)
    assert handler.snapshot(now_mono=4.2)["slots"][3]["distributor_ready"]


def test_c3_handoff_event_injects_slot1() -> None:
    handler = SectorCarouselHandler()
    handler.enable()
    handler.on_c3_handoff_trigger(
        Event(
            topic=C3_HANDOFF_TRIGGER,
            payload={
                "piece_uuid": "piece-1",
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


def test_dropping_slot_ejects_and_commits() -> None:
    ejects: list[bool] = []
    dist = _Distributor()
    dist.ready = True
    handler = SectorCarouselHandler(
        c4_eject=lambda: ejects.append(True) or True,
        distributor_port=dist,
        rotation_chunk_settle_s=0.0,
    )
    handler.enable()
    handler.inject_at_slot1("piece-1", now_mono=1.0)
    for ts in (2.0, 3.0, 4.0, 5.0):
        handler.rotate_one_sector(now_mono=ts)
    slot5 = handler.slots[4]
    slot5.classification = "brick"
    slot5.distributor_requested = True
    slot5.distributor_ready = True

    handler.tick(5.1)

    assert ejects == [True]
    assert dist.commits == ["piece-1"]
    assert handler.snapshot(now_mono=5.1)["slots"][4]["ejected"]
