from typing import Optional
import time
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import DistributionState
from irl.config import IRLInterface
from global_config import GlobalConfig


class Ready(BaseState):
    def __init__(self, irl: IRLInterface, gc: GlobalConfig, shared: SharedVariables):
        super().__init__(irl, gc)
        self.shared = shared
        self.signaled = False
        self._signaled_at: float = 0.0

    def step(self) -> Optional[DistributionState]:
        if not self.signaled:
            self.logger.info("Ready: distribution positioned, signaling ready")
            self.shared.distribution_ready = True
            self.signaled = True
            self._signaled_at = time.monotonic()

        if not self.shared.distribution_ready:
            wait_ms = (time.monotonic() - self._signaled_at) * 1000
            self.logger.info(f"Ready: piece dropped -> SENDING (waited={wait_ms:.0f}ms)")
            return DistributionState.SENDING

        if hasattr(self.gc, "runtime_stats"):
            self.gc.runtime_stats.observeBlockedReason(
                "distribution", "waiting_piece_drop"
            )

        return None

    def cleanup(self) -> None:
        super().cleanup()
        self.signaled = False
        self._signaled_at = 0.0
