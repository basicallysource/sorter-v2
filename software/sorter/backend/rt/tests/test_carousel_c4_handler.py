from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from rt.services.carousel_c4_handler import (
    CarouselC4Handler,
    CarouselState,
    CarouselTickInput,
)


@dataclass
class _FakeDistributor:
    accept_request: bool = True
    pending_uuid: str | None = None
    pending_ready: bool = False
    request_calls: list[dict] = None
    commit_calls: list[str] = None

    def __post_init__(self) -> None:
        if self.request_calls is None:
            self.request_calls = []
        if self.commit_calls is None:
            self.commit_calls = []

    def handoff_request(self, **kwargs) -> bool:
        self.request_calls.append(kwargs)
        if self.accept_request:
            self.pending_uuid = kwargs["piece_uuid"]
            return True
        return False

    def handoff_commit(self, piece_uuid: str, now_mono: float | None = None) -> bool:
        self.commit_calls.append(piece_uuid)
        return True

    def pending_ready(self, piece_uuid: str | None = None) -> bool:
        return self.pending_ready


class _Recorder:
    def __init__(self, success: bool = True) -> None:
        self.calls: list[Any] = []
        self.success = success

    def __call__(self, *args, **kwargs) -> bool:
        self.calls.append(args or kwargs)
        return self.success


def _make(distributor=None, transport=None, eject=None) -> tuple[CarouselC4Handler, _Recorder, _Recorder, _FakeDistributor]:
    if distributor is None:
        distributor = _FakeDistributor()
    transport = transport or _Recorder()
    eject = eject or _Recorder()
    h = CarouselC4Handler(
        c4_transport=transport,
        c4_eject=eject,
        distributor_port=distributor,
        c4_hw_busy=lambda: False,
        classify_deg=18.0,
        drop_deg=30.0,
        classify_tolerance_deg=4.0,
        drop_tolerance_deg=2.0,
        settle_s=0.5,
        advance_step_deg=4.0,
        advance_cooldown_s=0.0,
        distributor_timeout_s=5.0,
    )
    return h, transport, eject, distributor


def _input(
    *,
    piece_uuid: str | None = "p1",
    angle_deg: float | None = -50.0,
    classification_present: bool = False,
    classification: Any = None,
    distributor_pending_uuid: str | None = None,
    distributor_pending_ready: bool = False,
    front_track_count: int = 1,
) -> CarouselTickInput:
    return CarouselTickInput(
        front_piece_uuid=piece_uuid,
        front_track_angle_deg=angle_deg,
        front_classification_present=classification_present,
        front_classification=classification,
        front_dossier={},
        front_track_count=front_track_count,
        distributor_pending_piece_uuid=distributor_pending_uuid,
        distributor_pending_ready=distributor_pending_ready,
    )


def test_disabled_handler_does_nothing() -> None:
    h, t, e, _ = _make()
    state = h.tick(_input(angle_deg=18.0, classification_present=True))
    # not enabled — must stay IDLE and not pulse anything.
    assert state == CarouselState.IDLE
    assert t.calls == []
    assert e.calls == []


def test_advances_to_classify_when_piece_present() -> None:
    h, t, e, _ = _make()
    h.enable()
    state = h.tick(_input(angle_deg=-50.0), now_mono=0.0)
    assert state == CarouselState.ADVANCING_TO_CLASSIFY
    assert len(t.calls) == 1   # one transport pulse fired


def test_settles_when_piece_within_classify_tolerance() -> None:
    h, t, e, _ = _make()
    h.enable()
    h.tick(_input(angle_deg=-50.0), now_mono=0.0)
    state = h.tick(_input(angle_deg=18.0), now_mono=0.1)
    assert state == CarouselState.SETTLING_AT_CLASSIFY


def test_requests_distributor_when_classification_present() -> None:
    h, t, e, dist = _make()
    h.enable()
    # Advance + settle
    h.tick(_input(angle_deg=18.0), now_mono=0.0)   # SETTLING
    state = h.tick(
        _input(angle_deg=18.0, classification_present=True, classification="brick-2x4"),
        now_mono=0.1,
    )
    # Settle saw classification → REQUESTING_DISTRIBUTOR (one state per tick)
    assert state == CarouselState.REQUESTING_DISTRIBUTOR
    # Next tick fires the handoff_request and advances.
    state = h.tick(
        _input(angle_deg=18.0, classification_present=True, classification="brick-2x4"),
        now_mono=0.2,
    )
    assert state == CarouselState.AWAIT_DISTRIBUTOR_READY
    assert len(dist.request_calls) == 1
    assert dist.request_calls[0]["piece_uuid"] == "p1"


def test_settle_timeout_progresses_to_await_classification() -> None:
    h, t, e, _ = _make()
    h.enable()
    h.tick(_input(angle_deg=18.0), now_mono=0.0)   # SETTLING
    state = h.tick(_input(angle_deg=18.0), now_mono=1.0)  # past settle_s=0.5
    assert state == CarouselState.AWAIT_CLASSIFICATION


def test_advances_to_drop_after_distributor_ready() -> None:
    h, t, e, dist = _make()
    h.enable()
    # Get to AWAIT_DISTRIBUTOR_READY: needs SETTLING → REQUESTING → AWAIT
    h.tick(_input(angle_deg=18.0), now_mono=0.0)        # SETTLING
    h.tick(
        _input(angle_deg=18.0, classification_present=True, classification="brick"),
        now_mono=0.1,
    )  # REQUESTING_DISTRIBUTOR
    h.tick(
        _input(angle_deg=18.0, classification_present=True, classification="brick"),
        now_mono=0.2,
    )  # AWAIT_DISTRIBUTOR_READY
    state = h.tick(
        _input(
            angle_deg=18.0,
            classification_present=True,
            classification="brick",
            distributor_pending_uuid="p1",
            distributor_pending_ready=True,
        ),
        now_mono=0.3,
    )
    assert state == CarouselState.ADVANCING_TO_DROP


def test_full_happy_path_to_dropped() -> None:
    h, t, e, dist = _make()
    h.enable()
    # ADVANCING_TO_CLASSIFY (piece at -50°) → SETTLING (at 18°)
    h.tick(_input(angle_deg=-50.0), now_mono=0.0)
    h.tick(_input(angle_deg=18.0), now_mono=0.1)
    # Classification arrives during settle → REQUESTING
    h.tick(
        _input(angle_deg=18.0, classification_present=True, classification="brick"),
        now_mono=0.2,
    )
    # REQUESTING fires handoff → AWAIT_DISTRIBUTOR_READY
    h.tick(
        _input(angle_deg=18.0, classification_present=True, classification="brick"),
        now_mono=0.3,
    )
    # Distributor ready → ADVANCING_TO_DROP
    h.tick(
        _input(
            angle_deg=18.0,
            classification_present=True,
            classification="brick",
            distributor_pending_uuid="p1",
            distributor_pending_ready=True,
        ),
        now_mono=0.4,
    )
    # Reaches drop_deg → DROPPING (one tick later)
    h.tick(
        _input(
            angle_deg=30.0,
            classification_present=True,
            classification="brick",
            distributor_pending_uuid="p1",
            distributor_pending_ready=True,
        ),
        now_mono=0.5,
    )
    # Next tick fires eject + commit + completes cycle
    h.tick(
        _input(
            angle_deg=30.0,
            classification_present=True,
            classification="brick",
            distributor_pending_uuid="p1",
            distributor_pending_ready=True,
        ),
        now_mono=0.6,
    )
    assert len(e.calls) == 1, "eject should fire once"
    assert dist.commit_calls == ["p1"]
    assert h.snapshot()["counters"]["cycles_completed"] == 1


def test_distributor_timeout_aborts_cycle() -> None:
    h, t, e, dist = _make()
    h.enable()
    h.tick(_input(angle_deg=18.0), now_mono=0.0)        # SETTLING
    h.tick(
        _input(angle_deg=18.0, classification_present=True, classification="x"),
        now_mono=0.1,
    )  # REQUESTING_DISTRIBUTOR
    h.tick(
        _input(angle_deg=18.0, classification_present=True, classification="x"),
        now_mono=0.2,
    )  # AWAIT_DISTRIBUTOR_READY (entered)
    # Distributor never gets ready — wait past timeout
    h.tick(
        _input(angle_deg=18.0, classification_present=True, classification="x"),
        now_mono=10.0,  # past distributor_timeout_s=5
    )
    assert h.snapshot()["counters"]["cycles_aborted"] == 1


def test_front_piece_change_aborts_cycle() -> None:
    h, t, e, _ = _make()
    h.enable()
    h.tick(_input(piece_uuid="p1", angle_deg=-50.0), now_mono=0.0)
    state = h.tick(_input(piece_uuid="p2", angle_deg=-50.0), now_mono=0.1)
    assert state == CarouselState.IDLE
    assert h.snapshot()["counters"]["cycles_aborted"] == 1


def test_distributor_request_reject_keeps_cycle_in_request_state() -> None:
    dist = _FakeDistributor(accept_request=False)
    h, t, e, _ = _make(distributor=dist)
    h.enable()
    h.tick(_input(angle_deg=18.0), now_mono=0.0)          # SETTLING
    h.tick(
        _input(angle_deg=18.0, classification_present=True, classification="x"),
        now_mono=0.1,
    )  # REQUESTING (entered)
    state = h.tick(
        _input(angle_deg=18.0, classification_present=True, classification="x"),
        now_mono=0.2,
    )  # REQUESTING handler runs, distributor rejects
    assert state == CarouselState.REQUESTING_DISTRIBUTOR
    snap = h.snapshot()
    assert snap["counters"]["distributor_request_rejects"] == 1


def test_update_geometry_and_timing_live() -> None:
    h, _, _, _ = _make()
    h.update_geometry(classify_deg=20.0, classify_tolerance_deg=8.0)
    h.update_timing(settle_s=1.5, advance_step_deg=6.0)
    snap = h.snapshot()
    assert snap["geometry"]["classify_deg"] == 20.0
    assert snap["geometry"]["classify_tolerance_deg"] == 8.0
    assert snap["timing"]["settle_s"] == 1.5
    assert snap["timing"]["advance_step_deg"] == 6.0


def test_disable_aborts_inflight_cycle() -> None:
    h, _, _, _ = _make()
    h.enable()
    h.tick(_input(angle_deg=-50.0), now_mono=0.0)
    h.disable()
    snap = h.snapshot()
    assert snap["enabled"] is False
    assert snap["counters"]["cycles_aborted"] == 1
