from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SlotPhase(str, Enum):
    EMPTY = "empty"
    CAPTURING = "capturing"
    SETTLING = "settling"
    CLASSIFYING = "classifying"
    AWAITING_DIST = "awaiting_dist"
    DROPPING = "dropping"
    DROPPED_PENDING_CLEAR = "dropped_pending_clear"


class SlotContaminationState(str, Enum):
    CLEAN = "clean"
    SUSPECT_MULTI = "suspect_multi"
    CONFIRMED_MULTI = "confirmed_multi"
    SPILL_SUSPECTED = "spill_suspected"


DISCARD_ROUTE = "discard"


@dataclass(slots=True)
class SectorSlot:
    slot_index: int
    physical_sector_id: int | None = None
    piece_uuid: str | None = None
    expected_count: int = 1
    observed_count_estimate: int | None = None
    contamination_state: SlotContaminationState = SlotContaminationState.CLEAN
    reject_reason: str | None = None
    final_route: str | None = None
    normal_classification: Any | None = None
    phase: SlotPhase = SlotPhase.EMPTY
    entered_phase_at: float = 0.0
    frame_pool: list[Any] = field(default_factory=list)
    classification: Any | None = None
    classifier_request_id: str | None = None
    distributor_request_id: str | None = None
    classifier_future: Any | None = None
    capture_started: bool = False
    capture_done: bool = False
    distributor_requested: bool = False
    distributor_ready: bool = False
    eject_attempted: bool = False
    ejected: bool = False
    blocked_reason: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def occupied(self) -> bool:
        return self.piece_uuid is not None and self.phase is not SlotPhase.EMPTY

    def clear(self, *, now_mono: float = 0.0) -> None:
        self.piece_uuid = None
        self.expected_count = 1
        self.observed_count_estimate = None
        self.contamination_state = SlotContaminationState.CLEAN
        self.reject_reason = None
        self.final_route = None
        self.normal_classification = None
        self.phase = SlotPhase.EMPTY
        self.entered_phase_at = float(now_mono)
        self.frame_pool.clear()
        self.classification = None
        self.classifier_request_id = None
        self.distributor_request_id = None
        self.classifier_future = None
        self.capture_started = False
        self.capture_done = False
        self.distributor_requested = False
        self.distributor_ready = False
        self.eject_attempted = False
        self.ejected = False
        self.blocked_reason = None
        self.extras.clear()

    def set_phase(self, phase: SlotPhase, *, now_mono: float) -> None:
        if self.phase is phase:
            return
        self.phase = phase
        self.entered_phase_at = float(now_mono)
        self.blocked_reason = None

    @property
    def contaminated(self) -> bool:
        return self.contamination_state is not SlotContaminationState.CLEAN

    @property
    def discard_route(self) -> bool:
        return self.final_route == DISCARD_ROUTE

    @property
    def routing_decision_present(self) -> bool:
        return self.classification is not None or self.final_route is not None

    def mark_contaminated(
        self,
        *,
        state: SlotContaminationState,
        reject_reason: str,
        observed_count_estimate: int | None = None,
        now_mono: float | None = None,
    ) -> None:
        self.contamination_state = state
        self.reject_reason = str(reject_reason)
        if observed_count_estimate is not None:
            self.observed_count_estimate = max(1, int(observed_count_estimate))
        if state is SlotContaminationState.SPILL_SUSPECTED:
            self.blocked_reason = "spillover_suspected"
            self.final_route = None
            return
        self.final_route = DISCARD_ROUTE
        if self.classification is not None and self.normal_classification is None:
            self.normal_classification = self.classification
        self.classification = {
            "final_label": "DISCARD",
            "final_route": DISCARD_ROUTE,
            "reject_reason": self.reject_reason,
            "contamination_state": state.value,
            "observed_count_estimate": self.observed_count_estimate,
            "classified_at": float(now_mono) if now_mono is not None else None,
        }

    def ready_to_leave(self, *, now_mono: float, settle_s: float) -> tuple[bool, str | None]:
        if not self.occupied:
            return True, None
        if self.contamination_state is SlotContaminationState.SPILL_SUSPECTED:
            return False, "spillover_suspected"
        if self.phase is SlotPhase.CAPTURING:
            return (True, None) if self.capture_done else (False, "capture_pending")
        if self.phase is SlotPhase.SETTLING:
            if float(now_mono) - float(self.entered_phase_at) >= float(settle_s):
                return True, None
            return False, "settle_pending"
        if self.phase is SlotPhase.CLASSIFYING:
            return (
                (True, None)
                if self.routing_decision_present
                else (False, "classification_pending")
            )
        if self.phase is SlotPhase.AWAITING_DIST:
            return (
                (True, None)
                if self.distributor_ready
                else (False, "distributor_pending")
            )
        if self.phase is SlotPhase.DROPPING:
            return (True, None) if self.ejected else (False, "eject_pending")
        if self.phase is SlotPhase.DROPPED_PENDING_CLEAR:
            return True, None
        return False, "unknown_phase"

    def snapshot(self, *, now_mono: float | None = None) -> dict[str, Any]:
        age_s = None
        if now_mono is not None:
            age_s = max(0.0, float(now_mono) - float(self.entered_phase_at))
        return {
            "slot_index": int(self.slot_index),
            "station_index": int(self.slot_index),
            "physical_sector_id": (
                int(self.physical_sector_id)
                if self.physical_sector_id is not None
                else None
            ),
            "piece_uuid": self.piece_uuid,
            "expected_count": int(self.expected_count),
            "observed_count_estimate": self.observed_count_estimate,
            "contamination_state": self.contamination_state.value,
            "contaminated": self.contaminated,
            "reject_reason": self.reject_reason,
            "final_route": self.final_route,
            "normal_classification_present": self.normal_classification is not None,
            "phase": self.phase.value,
            "entered_phase_at": float(self.entered_phase_at),
            "phase_age_s": age_s,
            "frame_count": len(self.frame_pool),
            "classification_present": self.classification is not None,
            "routing_decision_present": self.routing_decision_present,
            "classifier_request_id": self.classifier_request_id,
            "distributor_request_id": self.distributor_request_id,
            "clear_pending_next_rotate": self.phase is SlotPhase.DROPPED_PENDING_CLEAR,
            "capture_started": bool(self.capture_started),
            "capture_done": bool(self.capture_done),
            "distributor_requested": bool(self.distributor_requested),
            "distributor_ready": bool(self.distributor_ready),
            "eject_attempted": bool(self.eject_attempted),
            "ejected": bool(self.ejected),
            "blocked_reason": self.blocked_reason,
            "extras": dict(self.extras),
        }

    def invariant_violations(self) -> list[dict[str, Any]]:
        violations: list[dict[str, Any]] = []

        def add(code: str, **payload: Any) -> None:
            violations.append({"code": code, "slot_index": self.slot_index, **payload})

        if self.phase is SlotPhase.EMPTY and self.piece_uuid is not None:
            add("empty_phase_has_piece", piece_uuid=self.piece_uuid)
        if self.phase is not SlotPhase.EMPTY and self.piece_uuid is None:
            add("occupied_phase_missing_piece", phase=self.phase.value)
        if self.phase is SlotPhase.DROPPED_PENDING_CLEAR and not self.ejected:
            add("dropped_pending_clear_without_eject")
        if self.contamination_state is SlotContaminationState.SPILL_SUSPECTED:
            if self.final_route is not None:
                add("spillover_has_route", final_route=self.final_route)
        elif (
            self.contamination_state is not SlotContaminationState.CLEAN
            and self.final_route != DISCARD_ROUTE
        ):
            add(
                "contaminated_slot_without_discard_route",
                contamination_state=self.contamination_state.value,
            )
        if self.contamination_state is not SlotContaminationState.CLEAN and not self.reject_reason:
            add(
                "contaminated_slot_missing_reject_reason",
                contamination_state=self.contamination_state.value,
            )
        if (
            self.observed_count_estimate is not None
            and self.observed_count_estimate < self.expected_count
        ):
            add(
                "observed_count_below_expected",
                expected_count=self.expected_count,
                observed_count_estimate=self.observed_count_estimate,
            )
        return violations
