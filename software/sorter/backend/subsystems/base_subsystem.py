from abc import ABC, abstractmethod


class BaseSubsystem(ABC):
    def __init__(self):
        self.ready_for_piece = True

    @abstractmethod
    def step(self) -> None:
        pass

    @abstractmethod
    def cleanup(self) -> None:
        pass
