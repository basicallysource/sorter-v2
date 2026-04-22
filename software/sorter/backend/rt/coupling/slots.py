"""Pull-backpressure primitives.

`CapacitySlot` — one-directional "I have room" signal between two neighbouring
runtimes. Non-blocking: queries return the current headroom; `try_claim`
atomically reserves a slot or returns `False`; `release` frees a slot. Never
blocks — this is semaphore semantics without `threading.Semaphore`'s blocking
`.acquire()` footgun, so the main-loop tick thread cannot stall.

Typical wiring: upstream runtime calls `try_claim()` when it physically
releases a piece downstream; downstream calls `release()` when the piece has
left its region. Capacity can be re-tuned at runtime via `set_capacity()`.
"""

from __future__ import annotations

from threading import Lock


class CapacitySlot:
    """Non-blocking 'I have room' signal between two runtimes."""

    __slots__ = ("name", "_capacity", "_taken", "_lock")

    def __init__(self, name: str, capacity: int) -> None:
        if capacity < 0:
            raise ValueError(f"capacity must be >= 0, got {capacity}")
        self.name = str(name)
        self._capacity = int(capacity)
        self._taken = 0
        self._lock = Lock()

    def available(self) -> int:
        """Current headroom. Non-blocking. Observational."""
        with self._lock:
            return max(0, self._capacity - self._taken)

    def try_claim(self) -> bool:
        """Atomically reserve one slot; False if no room. Never blocks."""
        with self._lock:
            if self._taken >= self._capacity:
                return False
            self._taken += 1
            return True

    def release(self) -> None:
        """Free one previously-claimed slot. No-op if nothing taken."""
        with self._lock:
            if self._taken > 0:
                self._taken -= 1

    def set_capacity(self, capacity: int) -> None:
        """Adjust capacity at runtime. Shrinks gracefully: in-flight claims
        are preserved; `available()` simply reports 0 until pieces drain."""
        if capacity < 0:
            raise ValueError(f"capacity must be >= 0, got {capacity}")
        with self._lock:
            self._capacity = int(capacity)

    def capacity(self) -> int:
        """Current maximum capacity (excludes reservations)."""
        with self._lock:
            return self._capacity

    def taken(self) -> int:
        """Current reservation count."""
        with self._lock:
            return self._taken

    def __repr__(self) -> str:
        with self._lock:
            return f"CapacitySlot(name={self.name!r}, taken={self._taken}/{self._capacity})"


__all__ = ["CapacitySlot"]
