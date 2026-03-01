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
    from irl.stepper import Stepper

ROTATE_TIMEOUT_MS = 5000


class Rotating(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        carousel: Carousel,
        stepper: "Stepper",
        event_queue: queue.Queue,
    ):
        super().__init__(irl, gc)
        self.shared = shared
        self.carousel = carousel
        self.stepper = stepper
        self.event_queue = event_queue
        self.rotation_done = False
        self.wait_started_at: Optional[float] = None
        self.last_wait_log_ms = 0.0

    def step(self) -> Optional[ClassificationState]:
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
                queue_size = self.stepper.mcu.command_queue.qsize()
                worker_alive = self.stepper.mcu.worker_thread.is_alive()
                self.logger.info(
                    f"Rotating: still waiting for distribution_ready ({waited_ms:.0f}ms, mcu_queue={queue_size}, mcu_worker_alive={worker_alive})"
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

        if not self.rotation_done:
            self.logger.info("Rotating: starting blocking rotation")
            try:
                self.stepper.rotateBlocking(-90.0, timeout_ms=ROTATE_TIMEOUT_MS)
            except RuntimeError as e:
                self.logger.error(f"Rotating: rotation failed: {e}")
                return ClassificationState.IDLE
            self.rotation_done = True
            self.logger.info("Rotating: rotation confirmed by MCU")

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
            self.shared.classification_ready = True
            return ClassificationState.IDLE

    def cleanup(self) -> None:
        super().cleanup()
        self.rotation_done = False
        self.wait_started_at = None
        self.last_wait_log_ms = 0.0
