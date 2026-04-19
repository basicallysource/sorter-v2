from typing import Optional
import time

from defs.consts import LOOP_TICK_MS
from defs.known_object import ClassificationStatus
from global_config import GlobalConfig
from irl.config import IRLInterface
from piece_transport import ClassificationChannelTransport
from states.base_state import BaseState
from subsystems.classification_channel.states import ClassificationChannelState
from subsystems.shared_variables import SharedVariables
from utils.event import knownObjectToEvent

WAIT_FOR_SETTLE_TO_TAKE_BASELINE_MS = 0
DEBOUNCE_MS = 300


class Detecting(BaseState):
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
        self._baseline_pending = True
        self._entered_at: Optional[float] = None
        self._detected_at: Optional[float] = None
        self._ready_at: Optional[float] = None
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
        now = time.time()
        if self._entered_at is None:
            self._entered_at = now

        current_piece = self.transport.getPieceAtClassification()
        wait_piece = self.transport.getPieceAtWaitZone()
        if current_piece is not None:
            if current_piece.classification_status in (
                ClassificationStatus.pending,
                ClassificationStatus.classifying,
            ):
                return ClassificationChannelState.SNAPPING
            return ClassificationChannelState.EJECTING

        if self._baseline_pending:
            self._setOccupancyState("classification_channel.wait_for_baseline")
            elapsed_ms = (now - self._entered_at) * 1000
            if elapsed_ms < WAIT_FOR_SETTLE_TO_TAKE_BASELINE_MS:
                return None
            if self.vision.usesCarouselBaseline() and not self.vision.captureCarouselBaseline():
                return None
            self._baseline_pending = False

        if not self.shared.classification_ready:
            if wait_piece is not None and self.shared.distribution_ready:
                self._setOccupancyState("classification_channel.flush_wait_zone")
                self.shared.classification_ready = False
                return ClassificationChannelState.EJECTING
            self.shared.classification_ready = True
            self._ready_at = now
            self._setOccupancyState("classification_channel.wait_piece_trigger")
            return None

        triggered, score, hot_px = self.vision.isCarouselTriggered()
        if triggered:
            if self._detected_at is None:
                self._detected_at = now
                self._setOccupancyState("classification_channel.debounce_trigger")
                self.logger.info(
                    "ClassificationChannel: piece detected "
                    f"(score={score:.1f}, hot_px={hot_px}), settling {DEBOUNCE_MS}ms"
                )
            elif (now - self._detected_at) * 1000 >= DEBOUNCE_MS:
                self.shared.classification_ready = False
                obj = self.transport.registerIncomingPiece()
                obj.feeding_started_at = self._ready_at
                obj.carousel_detected_confirmed_at = now
                try:
                    latest_track = self.vision.getLatestFeederTrack("carousel", max_age_s=1.2)
                    if isinstance(latest_track, dict):
                        track_id = latest_track.get("global_id")
                        if isinstance(track_id, int):
                            obj.tracked_global_id = track_id
                except Exception:
                    obj.tracked_global_id = None
                self.event_queue.put(knownObjectToEvent(obj))
                self.logger.info(
                    "ClassificationChannel: confirmed incoming piece %s"
                    % obj.uuid[:8]
                )
                return ClassificationChannelState.SNAPPING
        else:
            if wait_piece is not None and self.shared.distribution_ready:
                self._setOccupancyState("classification_channel.flush_wait_zone")
                self.shared.classification_ready = False
                return ClassificationChannelState.EJECTING
            self._setOccupancyState("classification_channel.wait_piece_trigger")
            self._detected_at = None

        self.gc.profiler.observeValue(
            "classification_channel.detecting.loop_tick_ms",
            float(LOOP_TICK_MS),
        )
        return None

    def cleanup(self) -> None:
        super().cleanup()
        self.vision.clearCarouselBaseline()
        self.shared.classification_ready = False
        self._baseline_pending = True
        self._entered_at = None
        self._detected_at = None
        self._ready_at = None
