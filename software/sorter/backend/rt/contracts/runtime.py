from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .tracking import TrackBatch


@dataclass(frozen=True, slots=True)
class RuntimeInbox:
    """Input surface: what the runtime sees each tick.

    Tracks arrive via the perception thread writing into a thread-safe
    latest-tracks slot (reader never blocks; gets last complete batch).
    """

    tracks: TrackBatch | None
    capacity_downstream: int


@dataclass(frozen=True, slots=True)
class RuntimeHealth:
    """Runtime lifecycle & tick health snapshot."""

    state: str
    blocked_reason: str | None
    last_tick_ms: float


class Runtime(ABC):
    """One per hardware component. Pull-driven."""

    runtime_id: str

    @abstractmethod
    def tick(self, inbox: RuntimeInbox, now_mono: float) -> None: ...

    @abstractmethod
    def available_slots(self) -> int:
        """How many pieces can I accept from upstream RIGHT NOW."""

    @abstractmethod
    def on_piece_delivered(self, piece_uuid: str, now_mono: float) -> None:
        """Upstream confirms a handoff just completed."""

    @abstractmethod
    def health(self) -> RuntimeHealth: ...

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None
