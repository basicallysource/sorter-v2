from typing import Optional, TYPE_CHECKING
import time
import queue
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import ClassificationState
from .carousel import Carousel
from irl.config import IRLInterface
from global_config import GlobalConfig
from defs.known_object import ClassificationStatus

if TYPE_CHECKING:
    from hardware.sorter_interface import StepperMotor

PRE_ROTATE_DELAY_MS = 250


class Rotating(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        carousel: Carousel,
        stepper: "StepperMotor",
        event_queue: queue.Queue,
    ):
        super().__init__(irl, gc)
        self.shared = shared
        self.carousel = carousel
        self.stepper = stepper
        self.event_queue = event_queue
        self.entered_at: Optional[float] = None
        self.start_time: Optional[float] = None
        self.command_sent = False
        self.wait_started_at: Optional[float] = None
        self.last_wait_log_ms = 0.0
        self._state_entered_at: Optional[float] = None

    def step(self) -> Optional[ClassificationState]:
        if self._state_entered_at is None:
            self._state_entered_at = time.time()
        piece_at_intermediate = self.carousel.getPieceAtIntermediate()
        requires_distribution_ready = piece_at_intermediate is not None and (
            piece_at_intermediate.part_id is not None
            or piece_at_intermediate.classification_status
            in (ClassificationStatus.unknown, ClassificationStatus.not_found)
        )

        if requires_distribution_ready and not self.shared.distribution_ready:
            if self.wait_started_at is None:
                self.wait_started_at = time.time()
                self.last_wait_log_ms = 0.0
                self.logger.info(
                    "Rotating: waiting for distribution_ready before sending carousel rotate"
                )

            waited_ms = (time.time() - self.wait_started_at) * 1000
            if waited_ms - self.last_wait_log_ms >= 1000:
                self.last_wait_log_ms = waited_ms
                self.logger.info(
                    f"Rotating: still waiting for distribution_ready ({waited_ms:.0f}ms)"
                )
            return None

        if requires_distribution_ready and self.wait_started_at is not None:
            waited_ms = (time.time() - self.wait_started_at) * 1000
            self.logger.info(
                f"Rotating: distribution_ready after waiting {waited_ms:.0f}ms"
            )
            self.wait_started_at = None
            self.last_wait_log_ms = 0.0
        elif not requires_distribution_ready:
            self.wait_started_at = None
            self.last_wait_log_ms = 0.0

        if self.entered_at is None:
            self.entered_at = time.time()

        if self.start_time is None:
            elapsed_since_entry_ms = (time.time() - self.entered_at) * 1000
            if elapsed_since_entry_ms < PRE_ROTATE_DELAY_MS:
                return None
            self.start_time = time.time()
            self.logger.info("Rotating: starting rotation")
            self.stepper.move_degrees(90.0)
            self.command_sent = True

        if not self.stepper.stopped:
            return None

        total_ms = (time.time() - self._state_entered_at) * 1000 if self._state_entered_at else 0
        wait_ms = 0.0
        if self.wait_started_at is not None and self.entered_at is not None:
            wait_ms = (self.entered_at - self._state_entered_at) * 1000 if self._state_entered_at else 0
        rotate_ms = (time.time() - self.start_time) * 1000 if self.start_time else 0
        self.logger.info(f"Rotating: complete (dist_wait={wait_ms:.0f}ms, rotate={rotate_ms:.0f}ms, total={total_ms:.0f}ms)")
        exiting = self.carousel.rotate()
        if exiting:
            self.logger.info(f"Rotating: piece {exiting.uuid[:8]} exited carousel")

        piece_at_exit = self.carousel.getPieceAtExit()
        if piece_at_exit is not None:
            self.logger.info(
                f"Rotating: piece {piece_at_exit.uuid[:8]} ready at exit for distribution"
            )
            self.shared.distribution_ready = False

        piece_at_class = self.carousel.getPieceAtClassification()
        if piece_at_class is not None:
            self.logger.info(
                f"Rotating: piece {piece_at_class.uuid[:8]} at classification position"
            )
            return ClassificationState.SNAPPING
        else:
            self.logger.info("Rotating: no piece at classification, returning to idle")
            return ClassificationState.IDLE

    def cleanup(self) -> None:
        super().cleanup()
        self.entered_at = None
        self.start_time = None
        self.command_sent = False
        self.wait_started_at = None
        self.last_wait_log_ms = 0.0
        self._state_entered_at = None
