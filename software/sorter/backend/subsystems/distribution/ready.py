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
            # has actually been flung — independent of any gate flag. Take it
            # from Positioning rather than reading the slot here: classification
            # steps between Positioning finishing and this first READY step and
            # can fling the piece in that window. Reading the slot then latched
            # None (or the next piece) and READY waited forever for a drop that
            # had already happened.
            self._positioned_uuid = None
            if transport is not None:
                self._positioned_uuid = getattr(
                    self.shared, "distribution_positioned_uuid", None
                )
                if self._positioned_uuid is None:
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
                if getattr(transport, "slot_handoff", False) and not self._positionedPieceDropped(
                    transport
                ):
                    # It left the positioning slot but never reached the drop
                    # slot: classification withdrew it (the piece was lost or the
                    # channel was force-cleared) or placed a different piece.
                    # Nothing fell, so there is nothing to send.
                    self.logger.warning(
                        f"Ready: positioned piece {self._positioned_uuid[:8]} was withdrawn "
                        f"without dropping (slot now "
                        f"{current.uuid[:8] if current is not None else 'empty'}) -> IDLE"
                    )
                    return DistributionState.IDLE
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

    def _positionedPieceDropped(self, transport) -> bool:
        dropped = transport.getPieceForDistributionDrop()
        return dropped is not None and dropped.uuid == self._positioned_uuid

    def cleanup(self) -> None:
        super().cleanup()
        self.signaled = False
        self._signaled_at = 0.0
        self._positioned_uuid = None
