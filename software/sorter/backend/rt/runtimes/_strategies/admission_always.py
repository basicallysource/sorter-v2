"""Default `AlwaysAdmit` admission strategy.

Placeholder for C2/C3 where the admission gate is degenerate — the real
admission contract lives at C3 to C4 (Phase 4). Until then, the runtime
always accepts inbound ReadySignal requests.
"""

from __future__ import annotations

from typing import Any

from rt.contracts.admission import AdmissionDecision
from rt.contracts.registry import register_admission


@register_admission("always")
class AlwaysAdmit:
    """Admission strategy that admits every inbound piece."""

    key = "always"

    def can_admit(
        self,
        inbound_piece_hint: dict[str, Any],  # noqa: ARG002 — interface conformance
        runtime_state: dict[str, Any],  # noqa: ARG002 — interface conformance
    ) -> AdmissionDecision:
        return AdmissionDecision(allowed=True, reason="always_admit")


__all__ = ["AlwaysAdmit"]
