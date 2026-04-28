from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PurgeCounts:
    """Channel-agnostic snapshot used by the generic purge strategy to
    decide when a channel can be considered clear."""

    piece_count: int
    owned_count: int
    pending_detections: int

    @property
    def is_empty(self) -> bool:
        return (
            self.piece_count <= 0
            and self.owned_count <= 0
            and self.pending_detections <= 0
        )


class PurgePort(Protocol):
    """A channel's binding surface for :class:`GenericPurgeStrategy`.

    Each C-channel runtime exposes one of these so the purge coordinator
    can arm/drive/observe/disarm it without knowing channel internals.
    """

    key: str

    def arm(self) -> None: ...

    def disarm(self) -> None: ...

    def counts(self) -> PurgeCounts: ...

    def drain_step(self, now_mono: float) -> bool: ...
