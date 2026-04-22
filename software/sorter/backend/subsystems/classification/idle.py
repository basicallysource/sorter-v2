from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import ClassificationState
from .carousel import Carousel
from irl.config import IRLInterface
from global_config import GlobalConfig


class Idle(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        carousel: Carousel,
    ):
        super().__init__(irl, gc)
        self.shared = shared
        self.carousel = carousel

    def step(self) -> Optional[ClassificationState]:
        return ClassificationState.DETECTING

    def cleanup(self) -> None:
        super().cleanup()
