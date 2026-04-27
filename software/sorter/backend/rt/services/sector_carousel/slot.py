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


@dataclass(slots=True)
class SectorSlot:
    slot_index: int
    physical_sector_id: int | None = None
    piece_uuid: str | None = None
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
            "phase": self.phase.value,
            "entered_phase_at": float(self.entered_phase_at),
            "phase_age_s": age_s,
            "frame_count": len(self.frame_pool),
            "classification_present": self.classification is not None,
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
