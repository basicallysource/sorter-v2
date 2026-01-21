import time
from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import DistributionState
from irl.config import IRLInterface
from global_config import GlobalConfig
from sorting_profile import SortingProfile

SEND_DURATION_MS = 500


class Sending(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        sorting_profile: SortingProfile,
    ):
        super().__init__(irl, gc)
        self.shared = shared
        self.sorting_profile = sorting_profile
        self.sequence_complete = False

    def step(self) -> Optional[DistributionState]:
        self._ensureExecutionThreadStarted()
        if self.sequence_complete:
            self.shared.distribution_ready = True
            return DistributionState.IDLE
        return None

    def cleanup(self) -> None:
        super().cleanup()
        self.sequence_complete = False

    def _executionLoop(self) -> None:
        self.logger.info("Distribution: sending piece to bin")
        time.sleep(SEND_DURATION_MS / 1000.0)
        if self._stop_event.is_set():
            return
        self.logger.info("Distribution: piece sent")
        self.sequence_complete = True
