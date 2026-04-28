from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import Future
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Protocol

from rt.contracts.events import Event, EventBus, Subscription
from rt.events.topics import C3_HANDOFF_TRIGGER

from .slot import DISCARD_ROUTE, SectorSlot, SlotContaminationState, SlotPhase


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
    landing_lease_requests: int = 0
    landing_lease_grants: int = 0
    landing_lease_rejects: int = 0
    landing_lease_timeouts: int = 0
    handoff_events_rejected: int = 0
    rotations: int = 0
    blocked_rotations: int = 0
    capture_starts: int = 0
    capture_completions: int = 0
    classifier_submits: int = 0
    classifier_completions: int = 0
    stale_classifier_results: int = 0
    distributor_requests: int = 0
    distributor_rejects: int = 0
    stale_distributor_results: int = 0
    ejects: int = 0
    drops_completed: int = 0
    c3_double_drop_count: int = 0
    c3_suspect_multi_count: int = 0
    multi_object_detected_count: int = 0
    discard_due_to_double_drop_count: int = 0
    discard_due_to_ambiguous_capture_count: int = 0
    spillover_suspected_count: int = 0
    discarded_slots: int = 0
    estimated_extra_parts: int = 0
    events_received: int = 0
    errors: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class _LandingLease:
    lease_id: str
    expires_at: float
    granted_at: float
    track_global_id: int | None = None
    handoff_quality: str | None = None
    handoff_multi_risk: bool | None = None
    handoff_context: dict[str, Any] = field(default_factory=dict)


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
        require_phase_verification: bool = False,
        discard_route_mode: str = "bypass",
        event_log_limit: int = 200,
        logger: logging.Logger | None = None,
    ) -> None:
        self._slots = [
            SectorSlot(
                slot_index=i + 1,
                physical_sector_id=i,
                entered_phase_at=0.0,
            )
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
        self._pending_landing_leases: dict[str, _LandingLease] = {}
        self._rotation_in_progress = False
        self._require_phase_verification = bool(require_phase_verification)
        self._phase_verified = not bool(require_phase_verification)
        self._phase_verified_at: float | None = None
        self._phase_verification_source: str | None = None
        self._phase_verification: dict[str, Any] | None = None
        normalized_discard_mode = str(discard_route_mode or "bypass").strip().lower()
        self._discard_route_mode = (
            normalized_discard_mode
            if normalized_discard_mode in {"bypass", "distributor"}
            else "bypass"
        )
        self._last_step_started_at: float | None = None
        self._last_step_done_at: float | None = None
        self._last_step_duration_ms: float | None = None
        self._last_effective_step_period_ms: float | None = None
        self._event_log_limit = max(20, int(event_log_limit))
        self._event_log: list[dict[str, Any]] = []
        self._counters = SectorCarouselCounters()

    @property
    def slots(self) -> tuple[SectorSlot, ...]:
        return tuple(self._slots)

    def enable(self) -> None:
        self._enabled = True
        self._record_event("handler_enabled")
        if self._event_bus is not None and self._subscription is None:
            self._subscription = self._event_bus.subscribe(
                C3_HANDOFF_TRIGGER, self.on_c3_handoff_trigger
            )

    def disable(self) -> None:
        self._enabled = False
        self._record_event("handler_disabled")
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
        self._record_event(
            "timing_updated",
            settle_s=self._settle_s,
            rotate_cooldown_s=self._rotate_cooldown_s,
            sector_step_deg=self._sector_step_deg,
            rotation_chunk_deg=self._rotation_chunk_deg,
            rotation_chunk_settle_s=self._rotation_chunk_settle_s,
            auto_rotate=self._auto_rotate,
        )

    def verify_phase(
        self,
        *,
        source: str,
        now_mono: float | None = None,
        measured_offset_deg: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        ts = time.monotonic() if now_mono is None else float(now_mono)
        self._phase_verified = True
        self._phase_verified_at = ts
        self._phase_verification_source = str(source or "unknown")
        self._phase_verification = {
            "source": self._phase_verification_source,
            "verified_at_mono": ts,
            "measured_offset_deg": measured_offset_deg,
            "details": dict(details or {}),
        }
        self._record_event(
            "phase_verified",
            now_mono=ts,
            source=self._phase_verification_source,
            measured_offset_deg=measured_offset_deg,
        )

    def invalidate_phase(
        self,
        *,
        reason: str,
        now_mono: float | None = None,
    ) -> None:
        ts = time.monotonic() if now_mono is None else float(now_mono)
        if self._require_phase_verification:
            self._phase_verified = False
        self._record_event("phase_invalidated", now_mono=ts, reason=str(reason))

    def on_c3_handoff_trigger(self, event: Event) -> None:
        payload = dict(event.payload or {})
        piece_uuid = payload.get("piece_uuid")
        if not isinstance(piece_uuid, str) or not piece_uuid.strip():
            piece_uuid = f"c3-{int(float(event.ts_mono) * 1000)}"
        lease_id = payload.get("landing_lease_id")
        self._counters.events_received += 1
        if not isinstance(lease_id, str) or not lease_id.strip():
            self._counters.handoff_events_rejected += 1
            self._count_error("handoff_missing_landing_lease")
            self._slots[0].blocked_reason = "handoff_missing_landing_lease"
            self._record_event(
                "handoff_rejected",
                now_mono=float(event.ts_mono),
                reason="handoff_missing_landing_lease",
                piece_uuid=piece_uuid,
            )
            return
        if not self._consume_lease_for_handoff(lease_id.strip(), float(event.ts_mono)):
            self._counters.handoff_events_rejected += 1
            self._count_error("handoff_without_valid_lease")
            self._slots[0].blocked_reason = "handoff_without_valid_lease"
            self._record_event(
                "handoff_rejected",
                now_mono=float(event.ts_mono),
                reason="handoff_without_valid_lease",
                piece_uuid=piece_uuid,
                landing_lease_id=lease_id,
            )
            return
        self._record_event(
            "handoff_accepted",
            now_mono=float(event.ts_mono),
            piece_uuid=piece_uuid,
            landing_lease_id=lease_id.strip(),
        )
        self.inject_at_slot1(
            piece_uuid.strip(),
            now_mono=float(event.ts_mono),
            extras={
                "landing_lease_id": lease_id.strip(),
                "c3_eject_ts": payload.get("c3_eject_ts"),
                "c3_eject_started_ts": payload.get("c3_eject_started_ts"),
                "expected_arrival_window_s": payload.get(
                    "expected_arrival_window_s"
                ),
                "handoff_quality": payload.get("handoff_quality"),
                "handoff_multi_risk": payload.get("handoff_multi_risk"),
                "multi_risk_score": payload.get("multi_risk_score"),
                "candidate_track_ids": payload.get("candidate_track_ids"),
                "candidate_global_ids": payload.get("candidate_global_ids"),
                "c3_handoff_quality_details": payload.get(
                    "c3_handoff_quality_details"
                ),
                "event_source": event.source,
            },
        )
        if _payload_indicates_c3_suspect_multi(payload):
            self.mark_slot_contaminated(
                piece_uuid.strip(),
                state=SlotContaminationState.SUSPECT_MULTI,
                reject_reason="c3_suspect_multi",
                observed_count_estimate=_optional_int(
                    payload.get("observed_count_estimate")
                ),
                now_mono=float(event.ts_mono),
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
            self._record_event("injection_rejected", now_mono=ts, reason="empty_piece_uuid")
            return False
        if any(slot.piece_uuid == piece_uuid for slot in self._slots):
            self._counters.duplicate_injections += 1
            self._record_event(
                "injection_duplicate",
                now_mono=ts,
                piece_uuid=piece_uuid,
            )
            return True
        slot = self._slots[0]
        if slot.occupied:
            slot.blocked_reason = "slot1_occupied"
            self._counters.rejected_injections += 1
            self._record_event(
                "injection_rejected",
                now_mono=ts,
                reason="slot1_occupied",
                piece_uuid=piece_uuid,
            )
            return False
        slot.clear(now_mono=ts)
        slot.piece_uuid = piece_uuid
        slot.set_phase(SlotPhase.CAPTURING, now_mono=ts)
        if extras:
            slot.extras.update(extras)
        self._counters.injected += 1
        self._record_event("piece_injected", now_mono=ts, piece_uuid=piece_uuid)
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
        handoff_quality: str | None = None,
        handoff_multi_risk: bool | None = None,
        handoff_context: dict | None = None,
    ) -> str | None:
        self._counters.landing_lease_requests += 1
        self._expire_landing_leases(now_mono)
        slot1 = self._slots[0]
        if not self._enabled:
            slot1.blocked_reason = "sector_carousel_disabled"
            self._counters.landing_lease_rejects += 1
            self._record_event(
                "landing_lease_rejected",
                now_mono=now_mono,
                reason="sector_carousel_disabled",
                track_global_id=track_global_id,
            )
            return None
        if self._require_phase_verification and not self._phase_verified:
            slot1.blocked_reason = "phase_verification_required"
            self._counters.landing_lease_rejects += 1
            self._record_event(
                "landing_lease_rejected",
                now_mono=now_mono,
                reason="phase_verification_required",
                track_global_id=track_global_id,
                handoff_quality=handoff_quality,
                handoff_multi_risk=handoff_multi_risk,
            )
            return None
        if self._rotation_in_progress or self._c4_hw_busy():
            slot1.blocked_reason = "landing_hw_busy"
            self._counters.landing_lease_rejects += 1
            self._record_event(
                "landing_lease_rejected",
                now_mono=now_mono,
                reason="landing_hw_busy",
                track_global_id=track_global_id,
            )
            return None
        if slot1.occupied or self._pending_landing_leases:
            if slot1.occupied:
                slot1.blocked_reason = "landing_slot_reserved"
            else:
                slot1.blocked_reason = "landing_lease_pending"
            self._counters.landing_lease_rejects += 1
            self._record_event(
                "landing_lease_rejected",
                now_mono=now_mono,
                reason=slot1.blocked_reason,
                track_global_id=track_global_id,
            )
            return None
        lease_id = uuid.uuid4().hex[:12]
        ttl_s = max(0.5, float(predicted_arrival_in_s) + 1.0)
        self._pending_landing_leases[lease_id] = _LandingLease(
            lease_id=lease_id,
            expires_at=float(now_mono) + ttl_s,
            granted_at=float(now_mono),
            track_global_id=track_global_id,
            handoff_quality=(
                str(handoff_quality) if handoff_quality is not None else None
            ),
            handoff_multi_risk=(
                bool(handoff_multi_risk)
                if handoff_multi_risk is not None
                else None
            ),
            handoff_context=dict(handoff_context or {}),
        )
        slot1.blocked_reason = None
        self._counters.landing_lease_grants += 1
        self._record_event(
            "landing_lease_granted",
            now_mono=now_mono,
            landing_lease_id=lease_id,
            track_global_id=track_global_id,
            expires_at=float(now_mono) + ttl_s,
            handoff_quality=handoff_quality,
            handoff_multi_risk=handoff_multi_risk,
        )
        return lease_id

    def consume_lease(self, lease_id: str) -> None:
        if self._pending_landing_leases.pop(lease_id, None) is not None:
            self._record_event("landing_lease_consumed", landing_lease_id=lease_id)

    def rotate_one_sector(self, *, now_mono: float | None = None) -> bool:
        ts = time.monotonic() if now_mono is None else float(now_mono)
        gates = self.gate_status(now_mono=ts, include_cooldown=False)
        hard_reasons = [
            reason
            for reason in gates["reasons"]
            if reason.get("blocking") and reason.get("reason") != "empty_pipeline"
        ]
        if hard_reasons:
            reason = str(hard_reasons[0].get("reason") or "gate_blocked")
            target_slot = self._slots[-1]
            slot_idx = hard_reasons[0].get("slot_index")
            if isinstance(slot_idx, int) and 1 <= slot_idx <= len(self._slots):
                target_slot = self._slots[slot_idx - 1]
            target_slot.blocked_reason = reason
            self._counters.blocked_rotations += 1
            self._record_event(
                "sector_step_rejected",
                now_mono=ts,
                reason=reason,
                gate=hard_reasons[0].get("gate"),
                slot_index=hard_reasons[0].get("slot_index"),
            )
            return False
        if self._rotation_in_progress:
            self._slots[-1].blocked_reason = "rotation_in_progress"
            self._counters.blocked_rotations += 1
            self._record_event(
                "sector_step_rejected",
                now_mono=ts,
                reason="rotation_in_progress",
            )
            return False
        if self._c4_hw_busy():
            self._slots[-1].blocked_reason = "hw_busy"
            self._counters.blocked_rotations += 1
            self._record_event("sector_step_rejected", now_mono=ts, reason="hw_busy")
            return False
        if (
            self._slots[-1].occupied
            and self._slots[-1].phase is not SlotPhase.DROPPED_PENDING_CLEAR
            and not self._slots[-1].ejected
        ):
            self._slots[-1].blocked_reason = "drop_slot_occupied"
            self._counters.blocked_rotations += 1
            self._record_event(
                "sector_step_rejected",
                now_mono=ts,
                reason="drop_slot_occupied",
            )
            return False
        self._last_step_started_at = ts
        previous_start = self._last_step_started_at
        if self._last_step_done_at is not None:
            self._last_effective_step_period_ms = max(
                0.0,
                (ts - float(self._last_step_done_at)) * 1000.0,
            )
        self._record_event("sector_step_started", now_mono=ts, degrees=self._sector_step_deg)
        self._rotation_in_progress = True
        try:
            if not self._transport_in_chunks(float(self._sector_step_deg)):
                self._counters.blocked_rotations += 1
                self._record_event(
                    "sector_step_rejected",
                    now_mono=ts,
                    reason="transport_failed",
                )
                return False
            moved_at = time.monotonic() if now_mono is None else ts
        finally:
            self._rotation_in_progress = False
        self._slots[-1].clear(now_mono=moved_at)
        self._slots.insert(0, self._slots.pop())
        for index, slot in enumerate(self._slots, start=1):
            slot.slot_index = index
            if slot.occupied:
                slot.set_phase(self.PHASE_BY_SLOT[index - 1], now_mono=moved_at)
        self._last_rotate_at = moved_at
        self._last_step_done_at = moved_at
        self._last_step_duration_ms = max(0.0, (moved_at - previous_start) * 1000.0)
        self._counters.rotations += 1
        self._record_event(
            "sector_step_done",
            now_mono=moved_at,
            degrees=self._sector_step_deg,
            duration_ms=self._last_step_duration_ms,
            effective_step_period_ms=self._last_effective_step_period_ms,
        )
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
            and self.auto_rotate_allowed()
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
        self._record_event(
            "capture_done",
            now_mono=now_mono,
            piece_uuid=piece_uuid,
            frame_count=len(frame_pool),
        )
        return True

    def bind_classification(
        self,
        piece_uuid: str,
        classification: Any,
        *,
        request_id: str | None = None,
        dossier: dict[str, Any] | None = None,
        now_mono: float | None = None,
    ) -> bool:
        slot = self._slot_for_piece(piece_uuid)
        if slot is None:
            return False
        if request_id is not None and slot.classifier_request_id != request_id:
            self._counters.stale_classifier_results += 1
            self._record_event(
                "classifier_result_stale",
                now_mono=now_mono,
                piece_uuid=piece_uuid,
                request_id=request_id,
                active_request_id=slot.classifier_request_id,
            )
            return False
        if slot.final_route == DISCARD_ROUTE and not _classification_is_discard(classification):
            slot.normal_classification = classification
            if dossier:
                slot.extras["normal_dossier"] = dict(dossier)
            self._record_event(
                "classifier_result_preserved_under_discard",
                now_mono=now_mono,
                piece_uuid=piece_uuid,
                request_id=request_id,
                final_route=slot.final_route,
            )
            return True
        self._apply_classification_to_slot(
            slot,
            classification,
            request_id=request_id,
            dossier=dossier,
            now_mono=now_mono,
        )
        return True

    def _apply_classification_to_slot(
        self,
        slot: SectorSlot,
        classification: Any,
        *,
        request_id: str | None = None,
        dossier: dict[str, Any] | None = None,
        now_mono: float | None = None,
    ) -> None:
        slot.classification = classification
        if _classification_is_discard(classification):
            slot.final_route = DISCARD_ROUTE
            if slot.reject_reason is None:
                slot.reject_reason = _discard_reason_from_classification(classification)
            observed_count = _observed_count_from_classification(classification)
            if observed_count is not None:
                slot.observed_count_estimate = observed_count
            if slot.contamination_state is SlotContaminationState.CLEAN:
                reason = slot.reject_reason or "classification_discard"
                if observed_count is not None and observed_count > slot.expected_count:
                    previous_state = slot.contamination_state
                    slot.contamination_state = SlotContaminationState.CONFIRMED_MULTI
                    self._count_contamination(
                        slot=slot,
                        previous_state=previous_state,
                        state=slot.contamination_state,
                        reject_reason=reason,
                    )
                elif reason in {"multi_object", "c3_double_drop"}:
                    previous_state = slot.contamination_state
                    slot.contamination_state = SlotContaminationState.CONFIRMED_MULTI
                    if slot.observed_count_estimate is None:
                        slot.observed_count_estimate = 2
                    self._count_contamination(
                        slot=slot,
                        previous_state=previous_state,
                        state=slot.contamination_state,
                        reject_reason=reason,
                    )
                elif reason in {"capture_ambiguous", "ambiguous_capture"}:
                    previous_state = slot.contamination_state
                    slot.contamination_state = SlotContaminationState.SUSPECT_MULTI
                    self._count_contamination(
                        slot=slot,
                        previous_state=previous_state,
                        state=slot.contamination_state,
                        reject_reason=reason,
                    )
        elif slot.final_route is None:
            slot.final_route = _route_from_classification(classification)
        if dossier:
            slot.extras["dossier"] = dict(dossier)
        if now_mono is not None:
            slot.extras["classified_at"] = float(now_mono)
        self._record_event(
            "classifier_result_applied",
            now_mono=now_mono,
            piece_uuid=slot.piece_uuid,
            request_id=request_id,
        )

    def mark_slot_contaminated(
        self,
        piece_uuid: str,
        *,
        state: SlotContaminationState,
        reject_reason: str,
        observed_count_estimate: int | None = None,
        now_mono: float | None = None,
    ) -> bool:
        ts = time.monotonic() if now_mono is None else float(now_mono)
        slot = self._slot_for_piece(piece_uuid)
        if slot is None:
            return False
        previous_state = slot.contamination_state
        slot.mark_contaminated(
            state=state,
            reject_reason=reject_reason,
            observed_count_estimate=observed_count_estimate,
            now_mono=ts,
        )
        self._count_contamination(
            slot=slot,
            previous_state=previous_state,
            state=state,
            reject_reason=reject_reason,
        )
        self._record_event(
            "slot_contaminated",
            now_mono=ts,
            piece_uuid=piece_uuid,
            contamination_state=state.value,
            reject_reason=reject_reason,
            observed_count_estimate=slot.observed_count_estimate,
            final_route=slot.final_route,
        )
        return True

    def mark_double_drop(
        self,
        piece_uuid: str,
        *,
        observed_count_estimate: int = 2,
        now_mono: float | None = None,
    ) -> bool:
        return self.mark_slot_contaminated(
            piece_uuid,
            state=SlotContaminationState.CONFIRMED_MULTI,
            reject_reason="c3_double_drop",
            observed_count_estimate=observed_count_estimate,
            now_mono=now_mono,
        )

    def bind_distributor_ready(
        self,
        piece_uuid: str,
        *,
        request_id: str | None = None,
        now_mono: float | None = None,
    ) -> bool:
        slot = self._slot_for_piece(piece_uuid)
        if slot is None:
            self._counters.stale_distributor_results += 1
            self._record_event(
                "distributor_result_stale",
                now_mono=now_mono,
                piece_uuid=piece_uuid,
                request_id=request_id,
                reason="piece_not_active",
            )
            return False
        if request_id is not None and slot.distributor_request_id != request_id:
            self._counters.stale_distributor_results += 1
            self._record_event(
                "distributor_result_stale",
                now_mono=now_mono,
                piece_uuid=piece_uuid,
                request_id=request_id,
                active_request_id=slot.distributor_request_id,
                reason="request_mismatch",
            )
            return False
        if not slot.distributor_requested and slot.final_route != DISCARD_ROUTE:
            self._counters.stale_distributor_results += 1
            self._record_event(
                "distributor_result_stale",
                now_mono=now_mono,
                piece_uuid=piece_uuid,
                request_id=request_id,
                reason="request_not_active",
            )
            return False
        if slot.ejected:
            self._counters.stale_distributor_results += 1
            self._record_event(
                "distributor_result_stale",
                now_mono=now_mono,
                piece_uuid=piece_uuid,
                request_id=request_id,
                reason="already_ejected",
            )
            return False
        slot.distributor_ready = True
        slot.extras["distributor_state"] = "ready"
        slot.extras["distributor_ready_at"] = (
            time.monotonic() if now_mono is None else float(now_mono)
        )
        slot.extras.setdefault("distributor_ready_source", "callback")
        self._record_event(
            "distributor_ready",
            now_mono=now_mono,
            piece_uuid=piece_uuid,
            request_id=request_id or slot.distributor_request_id,
        )
        return True

    def auto_rotate_allowed(self) -> bool:
        return bool(
            self._auto_rotate
            and (not self._require_phase_verification or self._phase_verified)
        )

    def gate_status(self, *, now_mono: float | None = None, include_cooldown: bool = True) -> dict[str, Any]:
        ts = time.monotonic() if now_mono is None else float(now_mono)
        reasons: list[dict[str, Any]] = []
        if not self._enabled:
            reasons.append({"scope": "global", "gate": "enabled", "reason": "sector_carousel_disabled", "blocking": True})
        if self._require_phase_verification and not self._phase_verified:
            reasons.append({"scope": "global", "gate": "phase", "reason": "phase_verification_required", "blocking": True})
        if self._rotation_in_progress:
            reasons.append({"scope": "global", "gate": "motion", "reason": "rotation_in_progress", "blocking": True})
        if self._c4_hw_busy():
            reasons.append({"scope": "global", "gate": "hardware", "reason": "hw_busy", "blocking": True})
        if include_cooldown and self._last_rotate_at != -float("inf"):
            remaining = max(0.0, self._rotate_cooldown_s - (ts - self._last_rotate_at))
            if remaining > 0.0:
                reasons.append({
                    "scope": "global",
                    "gate": "cooldown",
                    "reason": "rotate_cooldown",
                    "blocking": True,
                    "remaining_s": remaining,
                })
        if not any(slot.occupied for slot in self._slots):
            reasons.append({"scope": "global", "gate": "pipeline", "reason": "empty_pipeline", "blocking": True})

        slot_gates: list[dict[str, Any]] = []
        for slot in self._slots:
            ready, reason = slot.ready_to_leave(now_mono=ts, settle_s=self._settle_s)
            item = {
                "slot_index": int(slot.slot_index),
                "station_index": int(slot.slot_index),
                "physical_sector_id": slot.physical_sector_id,
                "piece_uuid": slot.piece_uuid,
                "phase": slot.phase.value,
                "contamination_state": slot.contamination_state.value,
                "contaminated": slot.contaminated,
                "reject_reason": slot.reject_reason,
                "final_route": slot.final_route,
                "routing_decision_present": slot.routing_decision_present,
                "ready_to_leave": bool(ready),
                "gate": None if ready else _gate_for_slot_phase(slot.phase),
                "reason": reason,
                "blocked_reason": slot.blocked_reason,
                "age_ms": max(0.0, (ts - slot.entered_phase_at) * 1000.0),
            }
            slot_gates.append(item)
            if not ready:
                reasons.append({
                    "scope": "slot",
                    "slot_index": int(slot.slot_index),
                    "physical_sector_id": slot.physical_sector_id,
                    "gate": item["gate"],
                    "reason": reason,
                    "contamination_state": slot.contamination_state.value,
                    "reject_reason": slot.reject_reason,
                    "final_route": slot.final_route,
                    "blocking": True,
                    "age_ms": item["age_ms"],
                })
        hard_reasons = [item for item in reasons if item.get("blocking")]
        return {
            "can_rotate": len(hard_reasons) == 0,
            "can_auto_rotate": bool(self.auto_rotate_allowed() and len(hard_reasons) == 0),
            "evaluated_at_mono": ts,
            "reasons": reasons,
            "slots": slot_gates,
        }

    def invariant_status(self, *, now_mono: float | None = None) -> dict[str, Any]:
        _ = time.monotonic() if now_mono is None else float(now_mono)
        violations: list[dict[str, Any]] = []
        if len(self._slots) != self.SLOT_COUNT:
            violations.append({"code": "slot_count_mismatch", "expected": self.SLOT_COUNT, "actual": len(self._slots)})
        sectors = [slot.physical_sector_id for slot in self._slots]
        if len(sectors) != len(set(sectors)):
            violations.append({"code": "duplicate_physical_sector_id", "values": sectors})
        pieces = [slot.piece_uuid for slot in self._slots if slot.piece_uuid]
        duplicates = sorted({piece for piece in pieces if pieces.count(piece) > 1})
        if duplicates:
            violations.append({"code": "duplicate_piece_uuid", "piece_uuids": duplicates})
        for slot in self._slots:
            if slot.phase is SlotPhase.EMPTY and slot.piece_uuid is not None:
                violations.append({"code": "empty_phase_has_piece", "slot_index": slot.slot_index, "piece_uuid": slot.piece_uuid})
            if slot.phase is not SlotPhase.EMPTY and slot.piece_uuid is None:
                violations.append({"code": "occupied_phase_missing_piece", "slot_index": slot.slot_index, "phase": slot.phase.value})
            if slot.phase is SlotPhase.DROPPED_PENDING_CLEAR and not slot.ejected:
                violations.append({"code": "dropped_pending_clear_without_eject", "slot_index": slot.slot_index})
            if (
                slot.contamination_state is SlotContaminationState.SPILL_SUSPECTED
                and slot.final_route is not None
            ):
                violations.append({"code": "spillover_has_route", "slot_index": slot.slot_index, "final_route": slot.final_route})
            if (
                slot.contamination_state
                not in {SlotContaminationState.CLEAN, SlotContaminationState.SPILL_SUSPECTED}
                and slot.final_route != DISCARD_ROUTE
            ):
                violations.append({"code": "contaminated_slot_without_discard_route", "slot_index": slot.slot_index, "contamination_state": slot.contamination_state.value})
            if slot.contamination_state is not SlotContaminationState.CLEAN and not slot.reject_reason:
                violations.append({"code": "contaminated_slot_missing_reject_reason", "slot_index": slot.slot_index, "contamination_state": slot.contamination_state.value})
            if (
                slot.observed_count_estimate is not None
                and slot.observed_count_estimate < slot.expected_count
            ):
                violations.append({"code": "observed_count_below_expected", "slot_index": slot.slot_index, "expected_count": slot.expected_count, "observed_count_estimate": slot.observed_count_estimate})
        if self._pending_landing_leases and self._slots[0].occupied:
            violations.append({"code": "landing_lease_while_slot1_occupied", "pending_count": len(self._pending_landing_leases)})
        if len(self._pending_landing_leases) > 1:
            violations.append({"code": "multiple_pending_landing_leases", "pending_count": len(self._pending_landing_leases)})
        return {"ok": not violations, "violations": violations}

    def status_snapshot(self, *, now_mono: float | None = None) -> dict[str, Any]:
        ts = time.monotonic() if now_mono is None else float(now_mono)
        snap = self.snapshot(now_mono=ts)
        snap["gates"] = self.gate_status(now_mono=ts)
        snap["invariants"] = self.invariant_status(now_mono=ts)
        snap["recent_events"] = self.recent_events(limit=50)
        return snap

    def recent_events(self, *, limit: int = 50) -> list[dict[str, Any]]:
        bounded = max(0, min(int(limit), self._event_log_limit))
        return [dict(item) for item in self._event_log[-bounded:]]

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
                self._apply_classification_to_slot(
                    slot,
                    classification,
                    dossier=dossier,
                    now_mono=now_mono,
                )
                slot.extras["classification_source"] = "legacy_front_state"
                slot.extras["c4_piece_uuid"] = c4_piece_uuid
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
            "auto_rotate_allowed": self.auto_rotate_allowed(),
            "discard_route_mode": self._discard_route_mode,
            "requires_phase_verification": bool(self._require_phase_verification),
            "phase_verified": bool(self._phase_verified),
            "phase_verification": (
                dict(self._phase_verification)
                if self._phase_verification is not None
                else None
            ),
            "motion_owner": "sector_carousel" if self._rotation_in_progress else None,
            "metrics": {
                "last_step_started_at_mono": self._last_step_started_at,
                "last_step_done_at_mono": self._last_step_done_at,
                "last_step_duration_ms": self._last_step_duration_ms,
                "last_effective_step_period_ms": self._last_effective_step_period_ms,
            },
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
            "invariants": self.invariant_status(now_mono=ts),
            "rotation_in_progress": bool(self._rotation_in_progress),
            "pending_landing_leases": len(self._pending_landing_leases),
            "pending_landing_lease_details": [
                {
                    "lease_id": lease.lease_id,
                    "expires_at": lease.expires_at,
                    "granted_at": lease.granted_at,
                    "track_global_id": lease.track_global_id,
                    "handoff_quality": lease.handoff_quality,
                    "handoff_multi_risk": lease.handoff_multi_risk,
                    "handoff_context": dict(lease.handoff_context or {}),
                }
                for lease in self._pending_landing_leases.values()
            ],
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
            for lease_id, lease in self._pending_landing_leases.items()
            if lease.expires_at <= now_mono
        ]
        for lease_id in expired:
            self._pending_landing_leases.pop(lease_id, None)
            self._counters.landing_lease_timeouts += 1

    def _consume_lease_for_handoff(self, lease_id: str, now_mono: float) -> bool:
        self._expire_landing_leases(now_mono)
        lease = self._pending_landing_leases.pop(lease_id, None)
        return lease is not None

    def _ready_for_rotation(self, now_mono: float) -> bool:
        for slot in self._slots:
            ready, _reason = slot.ready_to_leave(
                now_mono=now_mono,
                settle_s=self._settle_s,
            )
            if not ready:
                return False
        return True

    def _start_capture(self, slot: SectorSlot) -> None:
        if slot.capture_started or slot.piece_uuid is None:
            return
        slot.capture_started = True
        self._counters.capture_starts += 1
        self._record_event(
            "capture_started",
            piece_uuid=slot.piece_uuid,
            slot_index=slot.slot_index,
        )
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
            request_id = uuid.uuid4().hex[:12]
            piece_uuid = slot.piece_uuid
            slot.classifier_request_id = request_id
            slot.extras["classifier_request_id"] = request_id
            try:
                future = self._classifier_submit(slot)
            except Exception:
                slot.classifier_request_id = None
                slot.blocked_reason = "classifier_submit_raised"
                self._count_error("classifier_submit_raised")
                self._logger.exception("SectorCarouselHandler: classifier_submit raised")
                return
            self._counters.classifier_submits += 1
            self._record_event(
                "classifier_submitted",
                now_mono=now_mono,
                piece_uuid=piece_uuid,
                request_id=request_id,
                slot_index=slot.slot_index,
            )
            if isinstance(future, Future):
                slot.classifier_future = future
                slot.extras["classifier_piece_uuid"] = piece_uuid
            else:
                if slot.piece_uuid != piece_uuid or slot.classifier_request_id != request_id:
                    self._counters.stale_classifier_results += 1
                    self._record_event(
                        "classifier_result_stale",
                        now_mono=now_mono,
                        piece_uuid=piece_uuid,
                        request_id=request_id,
                    )
                    return
                self._apply_classification_to_slot(
                    slot,
                    future,
                    request_id=request_id,
                    now_mono=now_mono,
                )
                slot.extras["classified_at"] = now_mono
                self._counters.classifier_completions += 1
                return
        if isinstance(future, Future) and future.done():
            request_id = slot.classifier_request_id
            piece_uuid = slot.piece_uuid
            try:
                result = future.result(timeout=0.0)
            except Exception as exc:
                result = {"error": str(exc)}
                self._count_error("classifier_future_raised")
            if slot.piece_uuid != piece_uuid or slot.classifier_request_id != request_id:
                self._counters.stale_classifier_results += 1
                slot.classifier_future = None
                self._record_event(
                    "classifier_result_stale",
                    now_mono=now_mono,
                    piece_uuid=piece_uuid,
                    request_id=request_id,
                    active_piece_uuid=slot.piece_uuid,
                    active_request_id=slot.classifier_request_id,
                )
                return
            self._apply_classification_to_slot(
                slot,
                result,
                request_id=request_id,
                now_mono=now_mono,
            )
            slot.classifier_future = None
            slot.extras["classified_at"] = now_mono
            self._counters.classifier_completions += 1

    def _request_or_poll_distributor(self, slot: SectorSlot, now_mono: float) -> None:
        if slot.classification is None:
            slot.blocked_reason = "missing_classification"
            return
        if slot.final_route == DISCARD_ROUTE and self._discard_route_mode == "bypass":
            if not slot.distributor_ready:
                slot.distributor_ready = True
                slot.extras["distributor_state"] = "bypassed"
                slot.extras["distributor_mode"] = "bypass_for_discard"
                slot.extras["distributor_bypass_reason"] = "discard_default_exit"
                slot.extras["distributor_ready_source"] = "discard_bypass"
                slot.extras["distributor_ready_at"] = now_mono
                self._record_event(
                    "distributor_bypassed_for_discard",
                    now_mono=now_mono,
                    piece_uuid=slot.piece_uuid,
                    reject_reason=slot.reject_reason,
                )
            return
        port = self._distributor
        if port is None:
            slot.distributor_ready = True
            slot.extras["distributor_mode"] = "simulated"
            slot.extras["distributor_ready_source"] = "no_port"
            return
        if not slot.distributor_requested:
            request_id = uuid.uuid4().hex[:12]
            slot.distributor_request_id = request_id
            slot.extras["distributor_state"] = "requested"
            slot.extras["distributor_request_created_at"] = now_mono
            self._record_event(
                "distributor_requested",
                now_mono=now_mono,
                piece_uuid=slot.piece_uuid,
                request_id=request_id,
            )
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
                slot.distributor_request_id = None
                slot.extras["distributor_state"] = "rejected"
                slot.blocked_reason = "distributor_busy"
                self._counters.distributor_rejects += 1
                self._record_event(
                    "distributor_rejected",
                    now_mono=now_mono,
                    piece_uuid=slot.piece_uuid,
                    request_id=request_id,
                )
                return
            slot.distributor_requested = True
            slot.extras["distributor_state"] = "accepted"
            self._counters.distributor_requests += 1
        try:
            slot.distributor_ready = bool(port.pending_ready(slot.piece_uuid))
            if slot.distributor_ready:
                slot.extras["distributor_state"] = "ready"
                slot.extras["distributor_ready_at"] = now_mono
                slot.extras.setdefault("distributor_ready_source", "port")
                self._record_event(
                    "distributor_ready",
                    now_mono=now_mono,
                    piece_uuid=slot.piece_uuid,
                    request_id=slot.distributor_request_id,
                )
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
            self._record_event(
                "eject_failed",
                now_mono=now_mono,
                piece_uuid=slot.piece_uuid,
            )
            return
        self._counters.ejects += 1
        port = self._distributor
        if port is not None and slot.distributor_requested:
            try:
                port.handoff_commit(str(slot.piece_uuid), now_mono=now_mono)
                slot.extras["distributor_state"] = "committed"
                slot.extras["distributor_committed_at"] = now_mono
                self._record_event(
                    "distributor_committed",
                    now_mono=now_mono,
                    piece_uuid=slot.piece_uuid,
                    request_id=slot.distributor_request_id,
                )
            except Exception:
                self._count_error("handoff_commit_raised")
                self._logger.exception("SectorCarouselHandler: handoff_commit raised")
        slot.ejected = True
        slot.set_phase(SlotPhase.DROPPED_PENDING_CLEAR, now_mono=now_mono)
        self._counters.drops_completed += 1
        if slot.final_route == DISCARD_ROUTE:
            self._counters.discarded_slots += 1
            slot.extras["discard_ejected_at"] = now_mono
            self._record_event(
                "discard_eject_done",
                now_mono=now_mono,
                piece_uuid=slot.piece_uuid,
                reject_reason=slot.reject_reason,
            )
        self._record_event(
            "eject_done",
            now_mono=now_mono,
            piece_uuid=slot.piece_uuid,
            final_route=slot.final_route,
        )

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

    def _count_contamination(
        self,
        *,
        slot: SectorSlot,
        previous_state: SlotContaminationState,
        state: SlotContaminationState,
        reject_reason: str,
    ) -> None:
        if state is SlotContaminationState.SPILL_SUSPECTED:
            if previous_state is not SlotContaminationState.SPILL_SUSPECTED:
                self._counters.spillover_suspected_count += 1
            return
        if previous_state is not SlotContaminationState.CLEAN:
            return
        self._counters.multi_object_detected_count += 1
        if reject_reason == "c3_double_drop":
            self._counters.c3_double_drop_count += 1
            self._counters.discard_due_to_double_drop_count += 1
        elif reject_reason == "c3_suspect_multi":
            self._counters.c3_suspect_multi_count += 1
        elif reject_reason in {"capture_ambiguous", "ambiguous_capture"}:
            self._counters.discard_due_to_ambiguous_capture_count += 1
        estimate = slot.observed_count_estimate
        if isinstance(estimate, int) and estimate > slot.expected_count:
            self._counters.estimated_extra_parts += estimate - slot.expected_count

    def _record_event(
        self,
        event_type: str,
        *,
        now_mono: float | None = None,
        **payload: Any,
    ) -> None:
        ts = time.monotonic() if now_mono is None else float(now_mono)
        event = {
            "ts_mono": ts,
            "event_type": str(event_type),
            "rotation_in_progress": bool(self._rotation_in_progress),
            "phase_verified": bool(self._phase_verified),
            "blocked": self._blocked_reason(),
            "slots": self._compact_slots(),
        }
        event.update({key: value for key, value in payload.items() if value is not None})
        self._event_log.append(event)
        if len(self._event_log) > self._event_log_limit:
            del self._event_log[: len(self._event_log) - self._event_log_limit]

    def _compact_slots(self) -> list[dict[str, Any]]:
        return [
            {
                "station_index": int(slot.slot_index),
                "physical_sector_id": slot.physical_sector_id,
                "piece_uuid": slot.piece_uuid,
                "phase": slot.phase.value,
                "contamination_state": slot.contamination_state.value,
                "reject_reason": slot.reject_reason,
                "final_route": slot.final_route,
                "blocked_reason": slot.blocked_reason,
            }
            for slot in self._slots
        ]


def _gate_for_slot_phase(phase: SlotPhase) -> str:
    if phase is SlotPhase.CAPTURING:
        return "capture"
    if phase is SlotPhase.SETTLING:
        return "settle"
    if phase is SlotPhase.CLASSIFYING:
        return "classification"
    if phase is SlotPhase.AWAITING_DIST:
        return "distributor"
    if phase in {SlotPhase.DROPPING, SlotPhase.DROPPED_PENDING_CLEAR}:
        return "eject"
    return "unknown"


def _payload_indicates_c3_suspect_multi(payload: dict[str, Any]) -> bool:
    quality = _normalized_token(payload.get("handoff_quality"))
    if quality in {"suspect_multi", "confirmed_multi_risk", "confirmed_multi"}:
        return True
    if _truthy(payload.get("handoff_multi_risk")):
        return True
    details = payload.get("c3_handoff_quality_details")
    if isinstance(details, dict):
        if _truthy(details.get("handoff_multi_risk")):
            return True
        detail_quality = _normalized_token(details.get("handoff_quality"))
        return detail_quality in {
            "suspect_multi",
            "confirmed_multi_risk",
            "confirmed_multi",
        }
    return False


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


_DISCARD_LABELS = {
    DISCARD_ROUTE,
    "discard_bin",
    "reject",
    "reject_bin",
    "rejected",
    "trash",
    "unknown",
    "multi_object",
}


def _classification_is_discard(classification: Any) -> bool:
    if isinstance(classification, dict):
        observed_count = _observed_count_from_classification(classification)
        if observed_count is not None and observed_count > 1:
            return True
        if _truthy(classification.get("multi_object")):
            return True
        for key in (
            "final_route",
            "route",
            "target_route",
            "target_bin",
            "final_label",
            "label",
            "class_label",
            "classification",
        ):
            value = _normalized_token(classification.get(key))
            if value in _DISCARD_LABELS:
                return True
        reason = _normalized_token(classification.get("reject_reason"))
        return reason in {
            "c3_double_drop",
            "multi_object",
            "capture_ambiguous",
            "ambiguous_capture",
        }
    value = _normalized_token(classification)
    return value in _DISCARD_LABELS


def _discard_reason_from_classification(classification: Any) -> str:
    if isinstance(classification, dict):
        for key in ("reject_reason", "reason"):
            reason = _normalized_token(classification.get(key))
            if reason:
                return reason
        observed_count = _observed_count_from_classification(classification)
        if observed_count is not None and observed_count > 1:
            return "multi_object"
        if _truthy(classification.get("multi_object")):
            return "multi_object"
    value = _normalized_token(classification)
    if value == "reject":
        return "classifier_reject"
    if value == "unknown":
        return "ambiguous_capture"
    return "classification_discard"


def _route_from_classification(classification: Any) -> str | None:
    if isinstance(classification, dict):
        for key in (
            "final_route",
            "route",
            "target_route",
            "target_bin",
            "final_label",
            "label",
            "class_label",
            "classification",
        ):
            value = classification.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
    if isinstance(classification, str) and classification.strip():
        return classification.strip()
    return None


def _observed_count_from_classification(classification: Any) -> int | None:
    if not isinstance(classification, dict):
        return None
    for key in (
        "observed_count_estimate",
        "object_count_estimate",
        "object_count",
        "count",
    ):
        value = classification.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return max(1, value)
        if isinstance(value, float):
            return max(1, int(round(value)))
        if isinstance(value, str):
            try:
                return max(1, int(round(float(value))))
            except ValueError:
                continue
    return None


def _normalized_token(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip().lower().replace("-", "_").replace(" ", "_")
    return token or None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)
