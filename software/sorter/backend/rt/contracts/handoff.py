from __future__ import annotations

from typing import Any, Protocol

from rt.contracts.classification import ClassifierResult


class HandoffPort(Protocol):
    """C4 → Distributor handoff surface.

    C4 asks the distributor to take a classified piece (``handoff_request``),
    waits for the distributor to signal ready, fires the eject pulse, then
    commits (``handoff_commit``) so the distributor arms delivery. If C4
    loses the piece between request and commit it must ``handoff_abort``.

    Replaces the previous trio of ``set_handoff_*_callback`` setters so the
    hot path boundary between C4 and the distributor is a named port rather
    than three unnamed callback conventions.
    """

    def available_slots(self) -> int:
        """Non-blocking probe: how many handoff slots the distributor has.

        ``0`` means ``handoff_request`` will reject with ``distributor_busy``.
        Callers should skip the full request path in that case rather than
        hammering the port every tick (see distributor_busy counter explosion
        observed on live hardware).
        """
        ...

    def handoff_request(
        self,
        *,
        piece_uuid: str,
        classification: ClassifierResult,
        dossier: dict[str, Any] | None = None,
        now_mono: float | None = None,
    ) -> bool: ...

    def handoff_commit(
        self,
        piece_uuid: str,
        now_mono: float | None = None,
    ) -> bool: ...

    def handoff_abort(
        self,
        piece_uuid: str,
        reason: str = "handoff_aborted",
        now_mono: float | None = None,
    ) -> bool: ...
