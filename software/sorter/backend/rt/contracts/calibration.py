from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .feed import Zone


@dataclass(frozen=True, slots=True)
class PictureSettings:
    """Camera picture settings applied at warmup or reconfigure."""

    exposure: int | None
    white_balance: int | None
    focus: int | None
    gain: int | None


class CalibrationStrategy(Protocol):
    """Calibration strategy: produces zones and optional camera settings."""

    key: str

    def compute_zones(self, camera_id: str) -> tuple[Zone, ...]: ...

    def picture_settings(self, camera_id: str) -> PictureSettings | None: ...

    def needs_warmup(self) -> bool: ...

    def run_warmup(self, hw: Any) -> None: ...
