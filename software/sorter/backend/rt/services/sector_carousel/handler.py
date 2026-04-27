from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import Future
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Protocol

from rt.contracts.events import Event, EventBus, Subscription
from rt.events.topics import C3_HANDOFF_TRIGGER

from .slot import SectorSlot, SlotPhase


class _DistributorPort(Protocol):
    def handoff_request(
        self,
        *,
        piece_uuid: str,
        classification: Any,
        dossier: dict[str, Any] | None = None,
        now_mono: float | None = None,
    ) -> bool: ...

    def pending_ready(self, piece_uuid: str | None = None) -> bool: ...

    def handoff_commit(
        self, piece_uuid: str, now_mono: float | None = None
    ) -> bool: ...


@dataclass(slots=True)
class SectorCarouselCounters:
    injected: int = 0
    duplicate_injections: int = 0
    rejected_injections: int = 0
    rotations: int = 0
    blocked_rotations: int = 0
    capture_starts: int = 0
    capture_completions: int = 0
    classifier_submits: int = 0
    classifier_completions: int = 0
    distributor_requests: int = 0
    distributor_rejects: int = 0
    ejects: int = 0
    drops_completed: int = 0
    events_received: int = 0
    errors: dict[str, int] = field(default_factory=dict)


class SectorCarouselHandler:
    """Clocked five-slot C4 scheduler.

    Slots are physical sectors on the C4 platter. A sector rotation advances
    each slot to the next phase while the slot payload remains attached to
    the same physical sector.
    """

    SLOT_COUNT = 5
    SECTOR_STEP_DEG = 72.0
    PHASE_BY_SLOT = (
        SlotPhase.CAPTURING,
        SlotPhase.SETTLING,
        SlotPhase.CLASSIFYING,
        SlotPhase.AWAITING_DIST,
        SlotPhase.DROPPING,
    )

    def __init__(
        self,
        *,
        c4_transport: Callable[[float], bool] | None = None,
        c4_eject: Callable[[], bool] | None = None,
        distributor_port: _DistributorPort | None = None,
        classifier_submit: Callable[[SectorSlot], Future[Any] | Any] | None = None,
        capture_start: Callable[[str, SectorSlot], Any] | None = None,
        c4_hw_busy: Callable[[], bool] | None = None,
        event_bus: EventBus | None = None,
        sector_step_deg: float = SECTOR_STEP_DEG,
        settle_s: float = 0.35,
        auto_rotate: bool = False,
        rotate_cooldown_s: float = 5.0,
        rotation_chunk_deg: float = 2.0,
        rotation_chunk_settle_s: float = 0.12,
        logger: logging.Logger | None = None,
    ) -> None:
        self._slots = [
            SectorSlot(slot_index=i + 1, entered_phase_at=0.0)
            for i in range(self.SLOT_COUNT)
        ]
        self._c4_transport = c4_transport or (lambda _deg: True)
        self._c4_eject = c4_eject or (lambda: True)
        self._distributor = distributor_port
        self._classifier_submit = classifier_submit
        self._capture_start = capture_start
        self._c4_hw_busy = c4_hw_busy or (lambda: False)
        self._event_bus = event_bus
        self._sector_step_deg = max(0.5, min(72.0, float(sector_step_deg)))
        self._rotation_chunk_deg = max(0.5, min(3.0, float(rotation_chunk_deg)))
        self._rotation_chunk_settle_s = max(0.0, float(rotation_chunk_settle_s))
        self._settle_s = max(0.0, float(settle_s))
        self._auto_rotate = bool(auto_rotate)
        self._rotate_cooldown_s = max(5.0, float(rotate_cooldown_s))
        self._logger = logger or logging.getLogger("rt.sector_carousel")
        self._enabled = False
        self._last_rotate_at = -float("inf")
        self._last_tick_at = 0.0
        self._subscription: Subscription | None = None
        self._pending_landing_leases: dict[str, float] = {}
        self._counters = SectorCarouselCounters()

    @property
    def slots(self) -> tuple[SectorSlot, ...]:
        return tuple(self._slots)

    def enable(self) -> None:
        self._enabled = True
        if self._event_bus is not None and self._subscription is None:
            self._subscription = self._event_bus.subscribe(
                C3_HANDOFF_TRIGGER, self.on_c3_handoff_trigger
            )

    def disable(self) -> None:
        self._enabled = False
        sub = self._subscription
        self._subscription = None
        if sub is not None:
            sub.unsubscribe()

    def is_enabled(self) -> bool:
        return bool(self._enabled)

    def update_timing(
        self,
        *,
        settle_s: float | None = None,
        rotate_cooldown_s: float | None = None,
        sector_step_deg: float | None = None,
        rotation_chunk_deg: float | None = None,
        rotation_chunk_settle_s: float | None = None,
        auto_rotate: bool | None = None,
    ) -> None:
        if settle_s is not None:
            self._settle_s = max(0.0, float(settle_s))
        if rotate_cooldown_s is not None:
            self._rotate_cooldown_s = max(5.0, float(rotate_cooldown_s))
        if sector_step_deg is not None:
            self._sector_step_deg = max(0.5, min(72.0, float(sector_step_deg)))
        if rotation_chunk_deg is not None:
            self._rotation_chunk_deg = max(0.5, min(3.0, float(rotation_chunk_deg)))
        if rotation_chunk_settle_s is not None:
            self._rotation_chunk_settle_s = max(0.0, float(rotation_chunk_settle_s))
        if auto_rotate is not None:
            self._auto_rotate = bool(auto_rotate)

    def on_c3_handoff_trigger(self, event: Event) -> None:
        payload = dict(event.payload or {})
        piece_uuid = payload.get("piece_uuid")
        if not isinstance(piece_uuid, str) or not piece_uuid.strip():
            piece_uuid = f"c3-{int(float(event.ts_mono) * 1000)}"
        self._counters.events_received += 1
        self._pending_landing_leases.clear()
        self.inject_at_slot1(
            piece_uuid.strip(),
            now_mono=float(event.ts_mono),
            extras={
                "c3_eject_ts": payload.get("c3_eject_ts"),
                "expected_arrival_window_s": payload.get(
                    "expected_arrival_window_s"
                ),
                "event_source": event.source,
            },
        )

    def inject_at_slot1(
        self,
        piece_uuid: str,
        *,
        now_mono: float | None = None,
        extras: dict[str, Any] | None = None,
    ) -> bool:
        ts = time.monotonic() if now_mono is None else float(now_mono)
        piece_uuid = str(piece_uuid).strip()
        if not piece_uuid:
            self._counters.rejected_injections += 1
            return False
        if any(slot.piece_uuid == piece_uuid for slot in self._slots):
            self._counters.duplicate_injections += 1
            return True
        slot = self._slots[0]
        if slot.occupied:
            slot.blocked_reason = "slot1_occupied"
            self._counters.rejected_injections += 1
            return False
        slot.clear(now_mono=ts)
        slot.piece_uuid = piece_uuid
        slot.set_phase(SlotPhase.CAPTURING, now_mono=ts)
        if extras:
            slot.extras.update(extras)
        self._counters.injected += 1
        self._start_capture(slot)
        return True

    def landing_lease_port(self) -> "SectorCarouselHandler":
        return self

    def request_lease(
        self,
        *,
        predicted_arrival_in_s: float,
        min_spacing_deg: float,
        now_mono: float,
        track_global_id: int | None = None,
    ) -> str | None:
        self._expire_landing_leases(now_mono)
        slot1 = self._slots[0]
        if slot1.occupied or self._pending_landing_leases:
            if slot1.occupied:
                slot1.blocked_reason = "landing_slot_reserved"
            return None
        lease_id = uuid.uuid4().hex[:12]
        ttl_s = max(0.5, float(predicted_arrival_in_s) + 1.0)
        self._pending_landing_leases[lease_id] = float(now_mono) + ttl_s
        return lease_id

    def consume_lease(self, lease_id: str) -> None:
        self._pending_landing_leases.pop(lease_id, None)

    def rotate_one_sector(self, *, now_mono: float | None = None) -> bool:
        ts = time.monotonic() if now_mono is None else float(now_mono)
        if self._c4_hw_busy():
            self._slots[-1].blocked_reason = "hw_busy"
            self._counters.blocked_rotations += 1
            return False
        if self._slots[-1].occupied and not self._slots[-1].ejected:
            self._slots[-1].blocked_reason = "drop_slot_occupied"
            self._counters.blocked_rotations += 1
            return False
        if not self._transport_in_chunks(float(self._sector_step_deg)):
            self._counters.blocked_rotations += 1
            return False
        moved_at = time.monotonic()
        self._slots[-1].clear(now_mono=moved_at)
        self._slots.insert(0, self._slots.pop())
        for index, slot in enumerate(self._slots, start=1):
            slot.slot_index = index
            if slot.occupied:
                slot.set_phase(self.PHASE_BY_SLOT[index - 1], now_mono=moved_at)
        self._last_rotate_at = moved_at
        self._counters.rotations += 1
        return True

    def tick(self, now_mono: float | None = None) -> dict[str, Any]:
        ts = time.monotonic() if now_mono is None else float(now_mono)
        self._last_tick_at = ts
        if not self._enabled:
            return self.snapshot(now_mono=ts)
        for slot in self._slots:
            if not slot.occupied:
                continue
            if slot.phase is SlotPhase.CAPTURING:
                self._start_capture(slot)
            elif slot.phase is SlotPhase.SETTLING:
                if ts - slot.entered_phase_at >= self._settle_s:
                    slot.capture_done = True
            elif slot.phase is SlotPhase.CLASSIFYING:
                self._submit_or_poll_classifier(slot, ts)
            elif slot.phase is SlotPhase.AWAITING_DIST:
                self._request_or_poll_distributor(slot, ts)
            elif slot.phase is SlotPhase.DROPPING:
                self._drop(slot, ts)
        if (
            self._auto_rotate
            and ts - self._last_rotate_at >= self._rotate_cooldown_s
            and any(slot.occupied for slot in self._slots)
            and self._ready_for_rotation(ts)
        ):
            self.rotate_one_sector(now_mono=ts)
        return self.snapshot(now_mono=ts)

    def attach_frame_pool(
        self,
        piece_uuid: str,
        frame_pool: list[Any],
        *,
        now_mono: float | None = None,
    ) -> bool:
        slot = self._slot_for_piece(piece_uuid)
        if slot is None:
            return False
        slot.frame_pool = list(frame_pool)
        slot.capture_done = True
        self._counters.capture_completions += 1
        return True

    def bind_classification(
        self,
        piece_uuid: str,
        classification: Any,
        *,
        dossier: dict[str, Any] | None = None,
        now_mono: float | None = None,
    ) -> bool:
        slot = self._slot_for_piece(piece_uuid)
        if slot is None:
            return False
        slot.classification = classification
        if dossier:
            slot.extras["dossier"] = dict(dossier)
        if now_mono is not None:
            slot.extras["classified_at"] = float(now_mono)
        return True

    def bind_front_classification(
        self,
        *,
        c4_piece_uuid: str,
        classification: Any,
        dossier: dict[str, Any] | None = None,
        now_mono: float | None = None,
    ) -> bool:
        if self.bind_classification(
            c4_piece_uuid,
            classification,
            dossier=dossier,
            now_mono=now_mono,
        ):
            return True
        for slot in self._slots:
            if (
                slot.occupied
                and slot.classification is None
                and slot.phase in {SlotPhase.CLASSIFYING, SlotPhase.AWAITING_DIST}
            ):
                slot.classification = classification
                slot.extras["c4_piece_uuid"] = c4_piece_uuid
                if dossier:
                    slot.extras["dossier"] = dict(dossier)
                if now_mono is not None:
                    slot.extras["classified_at"] = float(now_mono)
                return True
        return False

    def snapshot(self, *, now_mono: float | None = None) -> dict[str, Any]:
        ts = self._last_tick_at if now_mono is None else float(now_mono)
        return {
            "name": "sector_carousel",
            "enabled": bool(self._enabled),
            "slot_count": self.SLOT_COUNT,
            "sector_step_deg": float(self._sector_step_deg),
            "auto_rotate": bool(self._auto_rotate),
            "timing": {
                "settle_s": float(self._settle_s),
                "rotate_cooldown_s": float(self._rotate_cooldown_s),
                "rotation_chunk_deg": float(self._rotation_chunk_deg),
                "rotation_chunk_settle_s": float(self._rotation_chunk_settle_s),
                "last_rotate_at_mono": (
                    None
                    if self._last_rotate_at == -float("inf")
                    else float(self._last_rotate_at)
                ),
                "next_rotate_in_s": (
                    0.0
                    if self._last_rotate_at == -float("inf")
                    else max(
                        0.0,
                        float(self._rotate_cooldown_s)
                        - (float(ts) - float(self._last_rotate_at)),
                    )
                ),
            },
            "slots": [slot.snapshot(now_mono=ts) for slot in self._slots],
            "counters": {
                **asdict(self._counters),
                "errors": dict(self._counters.errors),
            },
            "blocked": self._blocked_reason(),
            "pending_landing_leases": len(self._pending_landing_leases),
        }

    def _transport_in_chunks(self, degrees: float) -> bool:
        total = float(degrees)
        if total == 0.0:
            return True
        chunk = max(0.5, min(abs(total), float(self._rotation_chunk_deg)))
        sign = 1.0 if total > 0.0 else -1.0
        remaining = abs(total)
        first = True
        while remaining > 1e-6:
            step = min(chunk, remaining)
            if not first and self._rotation_chunk_settle_s > 0.0:
                time.sleep(self._rotation_chunk_settle_s)
            first = False
            if not self._c4_transport(sign * step):
                return False
            remaining -= step
        return True

    def _expire_landing_leases(self, now_mono: float) -> None:
        expired = [
            lease_id
            for lease_id, expires_at in self._pending_landing_leases.items()
            if expires_at <= now_mono
        ]
        for lease_id in expired:
            self._pending_landing_leases.pop(lease_id, None)

    def _ready_for_rotation(self, now_mono: float) -> bool:
        for slot in self._slots:
            if not slot.occupied:
                continue
            if slot.phase is SlotPhase.CAPTURING and not slot.capture_done:
                return False
            if slot.phase is SlotPhase.SETTLING:
                if now_mono - slot.entered_phase_at < self._settle_s:
                    return False
            if slot.phase is SlotPhase.CLASSIFYING and slot.classification is None:
                return False
            if slot.phase is SlotPhase.AWAITING_DIST and not slot.distributor_ready:
                return False
            if slot.phase is SlotPhase.DROPPING and not slot.ejected:
                return False
        return True

    def _start_capture(self, slot: SectorSlot) -> None:
        if slot.capture_started or slot.piece_uuid is None:
            return
        slot.capture_started = True
        self._counters.capture_starts += 1
        if self._capture_start is None:
            return
        try:
            self._capture_start(slot.piece_uuid, slot)
        except Exception:
            slot.blocked_reason = "capture_start_raised"
            self._count_error("capture_start_raised")
            self._logger.exception("SectorCarouselHandler: capture_start raised")

    def _submit_or_poll_classifier(self, slot: SectorSlot, now_mono: float) -> None:
        if slot.classification is not None:
            return
        future = slot.classifier_future
        if future is None and self._classifier_submit is not None:
            try:
                future = self._classifier_submit(slot)
            except Exception:
                slot.blocked_reason = "classifier_submit_raised"
                self._count_error("classifier_submit_raised")
                self._logger.exception("SectorCarouselHandler: classifier_submit raised")
                return
            self._counters.classifier_submits += 1
            if isinstance(future, Future):
                slot.classifier_future = future
            else:
                slot.classification = future
                self._counters.classifier_completions += 1
                return
        if isinstance(future, Future) and future.done():
            try:
                slot.classification = future.result(timeout=0.0)
            except Exception as exc:
                slot.classification = {"error": str(exc)}
                self._count_error("classifier_future_raised")
            slot.classifier_future = None
            slot.extras["classified_at"] = now_mono
            self._counters.classifier_completions += 1

    def _request_or_poll_distributor(self, slot: SectorSlot, now_mono: float) -> None:
        if slot.classification is None:
            slot.blocked_reason = "missing_classification"
            return
        port = self._distributor
        if port is None:
            slot.distributor_ready = True
            return
        if not slot.distributor_requested:
            try:
                accepted = bool(
                    port.handoff_request(
                        piece_uuid=str(slot.piece_uuid),
                        classification=slot.classification,
                        dossier=slot.snapshot(now_mono=now_mono),
                        now_mono=now_mono,
                    )
                )
            except Exception:
                accepted = False
                self._count_error("distributor_request_raised")
                self._logger.exception("SectorCarouselHandler: handoff_request raised")
            if not accepted:
                slot.blocked_reason = "distributor_busy"
                self._counters.distributor_rejects += 1
                return
            slot.distributor_requested = True
            slot.distributor_request_id = str(slot.piece_uuid)
            self._counters.distributor_requests += 1
        try:
            slot.distributor_ready = bool(port.pending_ready(slot.piece_uuid))
        except Exception:
            slot.blocked_reason = "distributor_ready_raised"
            self._count_error("distributor_ready_raised")

    def _drop(self, slot: SectorSlot, now_mono: float) -> None:
        if slot.ejected or slot.piece_uuid is None:
            return
        if slot.distributor_requested and not slot.distributor_ready:
            slot.blocked_reason = "waiting_distributor"
            return
        try:
            ok = bool(self._c4_eject())
        except Exception:
            ok = False
            self._count_error("eject_raised")
            self._logger.exception("SectorCarouselHandler: c4_eject raised")
        slot.eject_attempted = True
        if not ok:
            slot.blocked_reason = "eject_rejected"
            return
        self._counters.ejects += 1
        port = self._distributor
        if port is not None and slot.distributor_requested:
            try:
                port.handoff_commit(str(slot.piece_uuid), now_mono=now_mono)
            except Exception:
                self._count_error("handoff_commit_raised")
                self._logger.exception("SectorCarouselHandler: handoff_commit raised")
        slot.ejected = True
        self._counters.drops_completed += 1

    def _slot_for_piece(self, piece_uuid: str) -> SectorSlot | None:
        for slot in self._slots:
            if slot.piece_uuid == piece_uuid:
                return slot
        return None

    def _blocked_reason(self) -> str | None:
        for slot in self._slots:
            if slot.blocked_reason:
                return slot.blocked_reason
        return None

    def _count_error(self, reason: str) -> None:
        self._counters.errors[reason] = self._counters.errors.get(reason, 0) + 1
