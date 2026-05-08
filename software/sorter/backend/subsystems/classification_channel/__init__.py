from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .five_sector_platter import C4FiveSectorPlatter, C4SectorState
    from .state_machine import ClassificationChannelStateMachine

__all__ = [
    "C4FiveSectorPlatter",
    "C4SectorState",
    "ClassificationChannelStateMachine",
]


def __getattr__(name: str):
    if name in {"C4FiveSectorPlatter", "C4SectorState"}:
        from .five_sector_platter import C4FiveSectorPlatter, C4SectorState

        if name == "C4FiveSectorPlatter":
            return C4FiveSectorPlatter
        return C4SectorState
    if name == "ClassificationChannelStateMachine":
        from .state_machine import ClassificationChannelStateMachine

        return ClassificationChannelStateMachine
    raise AttributeError(name)
