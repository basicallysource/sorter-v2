from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state_machine import ClassificationChannelStateMachine

__all__ = ["ClassificationChannelStateMachine"]


def __getattr__(name: str):
    if name == "ClassificationChannelStateMachine":
        from .state_machine import ClassificationChannelStateMachine

        return ClassificationChannelStateMachine
    raise AttributeError(name)
