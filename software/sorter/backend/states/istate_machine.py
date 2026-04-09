from abc import ABC, abstractmethod
from typing import Optional, TypeVar, Generic
from enum import Enum

T = TypeVar("T", bound=Enum)


class IStateMachine(ABC, Generic[T]):
    @abstractmethod
    def step(self) -> Optional[T]:
        pass

    @abstractmethod
    def cleanup(self) -> None:
        pass
