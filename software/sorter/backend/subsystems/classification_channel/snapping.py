from typing import Optional
import time

from defs.known_object import ClassificationStatus
from global_config import GlobalConfig
from irl.config import IRLInterface
from piece_transport import ClassificationChannelTransport
from states.base_state import BaseState
from subsystems.classification_channel.states import ClassificationChannelState
from subsystems.shared_variables import SharedVariables

# Minimum dwell so the classification-channel tracker has a chance to
# accumulate a few piece crops before we advance the piece into the wait
# zone (where Brickognize actually fires).
SETTLE_MS = 1200


class Snapping(BaseState):
    """Dwell-only state.

    No single-frame detection, no Brickognize call. The classification
    channel trusts the polar tracker's accumulated crops; recognition is
    fired by ``Ejecting`` the moment the piece arrives in the wait zone.
    """

    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        transport: ClassificationChannelTransport,
        vision,
        event_queue,
    ):
        super().__init__(irl, gc)
        self.shared = shared
        self.transport = transport
        self.vision = vision
        self.event_queue = event_queue
        self._entered_at: Optional[float] = None
        self._occupancy_state: str | None = None

    def _setOccupancyState(self, state_name: str) -> None:
        if self._occupancy_state == state_name:
            return
        prev_state = self._occupancy_state
        self._occupancy_state = state_name
        self.gc.runtime_stats.observeStateTransition(
            "classification.occupancy",
            prev_state,
            state_name,
        )

    def step(self) -> Optional[ClassificationChannelState]:
        piece = self.transport.getPieceAtClassification()
        if piece is None:
            return ClassificationChannelState.DETECTING

        # Piece already resolved (classifying/classified/etc.) should never
        # sit in the hood slot — route out just in case.
        if piece.classification_status in (
            ClassificationStatus.classified,
            ClassificationStatus.unknown,
            ClassificationStatus.not_found,
            ClassificationStatus.multi_drop_fail,
        ):
            return ClassificationChannelState.EJECTING

        now = time.time()
        if self._entered_at is None:
            self._entered_at = now
            if piece.carousel_snapping_started_at is None:
                piece.carousel_snapping_started_at = now

        elapsed_ms = (now - self._entered_at) * 1000
        self._setOccupancyState("classification_channel.hood_dwell")
        if elapsed_ms < SETTLE_MS:
            return None

        if piece.carousel_snapping_completed_at is None:
            piece.carousel_snapping_completed_at = now
        return ClassificationChannelState.EJECTING

    def cleanup(self) -> None:
        super().cleanup()
        self._entered_at = None
