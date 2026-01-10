from defs.sorter_controller import SorterLifecycle
from irl.config import IRLInterface


class SorterController:
    def __init__(self, irl: IRLInterface):
        self.state = SorterLifecycle.INITIALIZING
        self.irl = irl

    def start(self) -> None:
        self.state = SorterLifecycle.RUNNING

    def stop(self) -> None:
        self.state = SorterLifecycle.READY

    def step(self) -> None:
        pass
