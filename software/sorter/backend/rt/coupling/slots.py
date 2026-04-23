"""Pull-backpressure primitives.

`CapacitySlot` — one-directional "I have room" signal between two neighbouring
runtimes. Non-blocking: queries return the current headroom; `try_claim`
atomically reserves a slot or returns `False`; `release` frees a slot. Never
blocks — this is semaphore semantics without `threading.Semaphore`'s blocking
`.acquire()` footgun, so the main-loop tick thread cannot stall.

Claims can carry a monotonic deadline. Every observation / mutation sweeps
expired claims first, so a piece that was announced by an upstream pulse
but never physically arrived downstream cannot orphan the slot forever —
the expiry reclaims it after a generous handoff budget.

Typical wiring: upstream runtime calls
``try_claim(now_mono=now, hold_time_s=2.0)`` when it physically releases a
piece downstream; downstream calls ``release()`` when the piece has left
its region. Capacity can be re-tuned at runtime via ``set_capacity()``.
"""

from __future__ import annotations

import math
from threading import Lock


# Sentinel deadline for claims that should never expire (backward-compatible
# callers that don't pass ``hold_time_s``). Using +inf keeps the sweep
# loop's comparison uniform.
_NO_EXPIRY = math.inf


class CapacitySlot:
    """Non-blocking 'I have room' signal between two runtimes."""

    __slots__ = ("name", "_capacity", "_claims", "_lock")

    def __init__(self, name: str, capacity: int) -> None:
        if capacity < 0:
            raise ValueError(f"capacity must be >= 0, got {capacity}")
        self.name = str(name)
        self._capacity = int(capacity)
        # Each entry is the monotonic deadline of a live claim. ``+inf``
        # means "no expiry". Kept in insertion order — release() pops the
        # oldest (FIFO) which matches the physical piece-hand-off order.
        self._claims: list[float] = []
        self._lock = Lock()

    def _sweep_locked(self, now_mono: float | None) -> None:
        if now_mono is None:
            return
        deadline = float(now_mono)
        self._claims = [c for c in self._claims if c > deadline]

    def available(self, now_mono: float | None = None) -> int:
        """Current headroom. Non-blocking. Observational.

        Passing ``now_mono`` sweeps expired claims before answering, so
        orphaned reservations are automatically reclaimed on the next
        scheduling tick.
        """
        with self._lock:
            self._sweep_locked(now_mono)
            return max(0, self._capacity - len(self._claims))

    def try_claim(
        self,
        *,
        now_mono: float | None = None,
        hold_time_s: float | None = None,
    ) -> bool:
        """Atomically reserve one slot; False if no room. Never blocks.

        ``hold_time_s`` sets a monotonic deadline after which the claim
        self-releases. Defaults to no expiry (legacy semantics). Passing
        ``hold_time_s`` without ``now_mono`` keeps a finite deadline
        anchored at ``0`` (effectively immediate expiry) — callers that
        want a timeout must provide both.
        """
        with self._lock:
            self._sweep_locked(now_mono)
            if len(self._claims) >= self._capacity:
                return False
            if hold_time_s is None:
                deadline = _NO_EXPIRY
            else:
                base = 0.0 if now_mono is None else float(now_mono)
                deadline = base + float(hold_time_s)
            self._claims.append(deadline)
            return True

    def release(self) -> None:
        """Free one previously-claimed slot. No-op if nothing taken.

        Pops the oldest claim (FIFO) so ordering matches the physical
        hand-off: whichever piece was claimed first is the one that
        arrived first downstream.
        """
        with self._lock:
            if self._claims:
                self._claims.pop(0)

    def set_capacity(self, capacity: int) -> None:
        """Adjust capacity at runtime. Shrinks gracefully: in-flight claims
        are preserved; ``available()`` simply reports 0 until pieces drain."""
        if capacity < 0:
            raise ValueError(f"capacity must be >= 0, got {capacity}")
        with self._lock:
            self._capacity = int(capacity)

    def capacity(self) -> int:
        """Current maximum capacity (excludes reservations)."""
        with self._lock:
            return self._capacity

    def taken(self, now_mono: float | None = None) -> int:
        """Current reservation count, after optional expiry sweep."""
        with self._lock:
            self._sweep_locked(now_mono)
            return len(self._claims)

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"CapacitySlot(name={self.name!r}, "
                f"taken={len(self._claims)}/{self._capacity})"
            )


__all__ = ["CapacitySlot"]
