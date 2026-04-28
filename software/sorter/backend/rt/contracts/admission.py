from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    """Verdict on whether an inbound piece can be admitted to this runtime."""

    allowed: bool
    reason: str


class AdmissionStrategy(Protocol):
    """How a Runtime decides whether to accept an incoming ReadySignal request.

    Collapses what was scattered as the C3-to-C4 admission gate (raw-detection
    cap, zone-count, arc-clear check, transport-count) into a single pluggable
    decision.
    """

    key: str

    def can_admit(
        self,
        inbound_piece_hint: dict[str, Any],
        runtime_state: dict[str, Any],
    ) -> AdmissionDecision: ...
