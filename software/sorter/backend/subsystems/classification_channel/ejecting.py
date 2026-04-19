from typing import Optional
import time

from defs.known_object import ClassificationStatus
from global_config import GlobalConfig
from irl.config import IRLConfig, IRLInterface
from piece_transport import ClassificationChannelTransport
from states.base_state import BaseState
from subsystems.classification_channel.states import ClassificationChannelState
from subsystems.shared_variables import SharedVariables

PRE_EJECT_DELAY_MS = 200


class Ejecting(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        shared: SharedVariables,
        transport: ClassificationChannelTransport,
    ):
        super().__init__(irl, gc)
        self.irl_config = irl_config
        self.shared = shared
        self.transport = transport
        self.entered_at: Optional[float] = None
        self.start_time: Optional[float] = None
        self.command_sent = False
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
        classification_piece = self.transport.getPieceAtClassification()
        wait_piece = self.transport.getPieceAtWaitZone()
        moving_piece = classification_piece or wait_piece

        if moving_piece is None:
            return ClassificationChannelState.DETECTING

        if classification_piece is not None and classification_piece.classification_status in (
            ClassificationStatus.pending,
            ClassificationStatus.classifying,
        ):
            self._setOccupancyState("classification_channel.wait_classification_result")
            self.gc.runtime_stats.observeBlockedReason(
                "classification", "waiting_classification_result"
            )
            return None

        should_drop_wait_piece = wait_piece is not None
        should_park_classification_piece = classification_piece is not None

        if should_drop_wait_piece and not self.shared.distribution_ready:
            self._setOccupancyState("classification_channel.wait_distribution_ready")
            self.gc.runtime_stats.observeBlockedReason(
                "classification", "waiting_distribution_ready"
            )
            return None

        now = time.time()
        if self.entered_at is None:
            self.entered_at = now

        if self.start_time is None:
            elapsed_since_entry_ms = (now - self.entered_at) * 1000
            self._setOccupancyState("classification_channel.pre_eject_delay")
            if elapsed_since_entry_ms < PRE_EJECT_DELAY_MS:
                return None

            cfg = self.irl_config.feeder_config.classification_channel_eject
            pulse_degrees = self.irl.carousel_stepper.degrees_for_microsteps(
                cfg.steps_per_pulse
            )
            if not self.irl.carousel_stepper.move_degrees(pulse_degrees):
                self.gc.runtime_stats.observeBlockedReason(
                    "classification", "classification_channel_eject_rejected"
                )
                return None

            self.start_time = now
            self.command_sent = True
            if moving_piece is not None and moving_piece.carousel_rotate_started_at is None:
                moving_piece.carousel_rotate_started_at = now

            if should_drop_wait_piece and should_park_classification_piece:
                self.logger.info(
                    "ClassificationChannel: dropping piece %s and parking piece %s with %.1f degrees"
                    % (
                        wait_piece.uuid[:8],
                        classification_piece.uuid[:8],
                        pulse_degrees,
                    )
                )
            elif should_drop_wait_piece and wait_piece is not None:
                self.logger.info(
                    "ClassificationChannel: dropping parked piece %s with %.1f degrees"
                    % (wait_piece.uuid[:8], pulse_degrees)
                )
            elif classification_piece is not None:
                self.logger.info(
                    "ClassificationChannel: parking piece %s into wait zone with %.1f degrees"
                    % (classification_piece.uuid[:8], pulse_degrees)
                )

        if not self.irl.carousel_stepper.stopped:
            self._setOccupancyState("classification_channel.wait_transport_motion_complete")
            return None

        result = self.transport.advanceTransport()
        dropped_piece = result.piece_for_distribution_drop
        if dropped_piece is not None and dropped_piece.carousel_rotated_at is None:
            dropped_piece.carousel_rotated_at = time.time()
        if dropped_piece is not None:
            self.logger.info(
                "ClassificationChannel: piece %s dropped into distributor path"
                % dropped_piece.uuid[:8]
            )
            self.shared.distribution_ready = False
        return ClassificationChannelState.DETECTING

    def cleanup(self) -> None:
        super().cleanup()
        self.entered_at = None
        self.start_time = None
        self.command_sent = False
