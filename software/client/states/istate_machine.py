from abc import ABC, abstractmethod
from typing import Optional
from defs.sorting_state import SortingState


class IStateMachine(ABC):
    @abstractmethod
    def step(self) -> Optional[SortingState]:
        pass

    @abstractmethod
    def cleanup(self) -> None:
        pass
