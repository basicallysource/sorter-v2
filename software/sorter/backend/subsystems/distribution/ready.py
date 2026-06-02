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
        self._positioned_uuid: str | None = None

    def step(self) -> Optional[DistributionState]:
        transport = self.shared.transport
        if not self.signaled:
            self.logger.info("Ready: distribution positioned, signaling ready")
            self.shared.set_distribution_gate(True, reason="ready_chute_aimed")
            self.signaled = True
            self._signaled_at = time.monotonic()
            # Remember which piece we positioned so we can tell, durably, when it
            # has actually been flung — independent of any gate flag.
            self._positioned_uuid = None
            if transport is not None:
                positioned = transport.getPieceForDistributionPositioning()
                self._positioned_uuid = (
                    positioned.uuid if positioned is not None else None
                )

        # Durable drop detection: the piece we positioned has left the
        # positioning slot, i.e. classification flung it into the chute via
        # advanceTransport. This does NOT depend on classification flipping
        # distribution_ready, so the READY -> SENDING transition can't be lost
        # in a gate race (the bug that froze distribution in READY forever).
        # The gate is kept only as a fallback for the other (dynamic/legacy)
        # classification paths that still drive it.
        piece_advanced = False
        if transport is not None and self._positioned_uuid is not None:
            current = transport.getPieceForDistributionPositioning()
            if current is None or current.uuid != self._positioned_uuid:
                piece_advanced = True

        if piece_advanced or not self.shared.distribution_ready:
            wait_ms = (time.monotonic() - self._signaled_at) * 1000
            self.logger.info(
                f"Ready: piece dropped -> SENDING (waited={wait_ms:.0f}ms, "
                f"advanced={piece_advanced}, gate_ready={self.shared.distribution_ready})"
            )
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
        self._positioned_uuid = None
