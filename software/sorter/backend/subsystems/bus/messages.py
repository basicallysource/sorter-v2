from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class StationId(str, Enum):
    C1 = "c1"
    C2 = "c2"
    C3 = "c3"
    CLASSIFICATION = "classification"
    DISTRIBUTION = "distribution"


@dataclass(frozen=True)
class StationGate:
    station: StationId
    open: bool
    reason: Optional[str] = None
    updated_at_mono: float = 0.0


@dataclass(frozen=True)
class ChuteMotion:
    in_progress: bool
    target_bin: object | None = None
    updated_at_mono: float = 0.0


@dataclass(frozen=True)
class PieceRequest:
    source: StationId
    target: StationId
    sent_at_mono: float


@dataclass(frozen=True)
class PieceDelivered:
    source: StationId
    target: StationId
    delivered_at_mono: float


Message = StationGate | ChuteMotion | PieceRequest | PieceDelivered


__all__ = [
    "ChuteMotion",
    "Message",
    "PieceDelivered",
    "PieceRequest",
    "StationGate",
    "StationId",
]
