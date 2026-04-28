"""LandingLeasePort — software escapement between adjacent C-rings.

C3 holds a port reference (passed in at bootstrap). Before C3 fires an
exit pulse it asks the port "may I send the next piece — is the
downstream landing arc clear?" The port returns a lease id when the
downstream PieceTrackBank can guarantee chute-spacing, or ``None`` when
the request would clash with an existing track or another pending
landing.

The port replaces the old slot.try_claim gate used to be the only
upstream-to-downstream coordination. The slot was time-based (3 s
expiry per claim) and identity-blind; the lease is geometry-based
(min_spacing_deg around predicted landing angle) and explicitly tied to
a downstream PieceTrack admission.

Implementations wrap a ``PieceTrackBank`` — see
``rt/runtimes/c4.py::C4LandingLeasePort`` for the C3->C4 wiring.
"""

from __future__ import annotations

from typing import Protocol


class LandingLeasePort(Protocol):
    """Software escapement gate exposed by a downstream channel."""

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
        """Reserve a future landing slot.

        Returns a lease id on grant, ``None`` on refusal. The caller is
        responsible for calling ``consume_lease`` once the piece has
        physically arrived downstream, OR letting the lease expire if
        the upstream pulse fails to deliver.
        """
        ...

    def consume_lease(self, lease_id: str) -> None:
        """Mark the lease as fulfilled (the new piece has been admitted)."""
        ...


__all__ = ["LandingLeasePort"]
