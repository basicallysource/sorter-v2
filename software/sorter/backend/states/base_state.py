from irl.config import IRLInterface
from global_config import GlobalConfig


class BaseState:
    """What every subsystem state holds: the hardware, the config and the logger."""

    def __init__(self, irl: IRLInterface, gc: GlobalConfig):
        self.irl = irl
        self.gc = gc
        self.logger = gc.logger

    def step(self):
        return None

    def cleanup(self) -> None:
        pass
