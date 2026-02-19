from typing import Optional, TYPE_CHECKING
import time
import queue
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import ClassificationState
from .carousel import Carousel
from irl.config import IRLInterface
from global_config import GlobalConfig
from defs.events import KnownObjectEvent, KnownObjectData, KnownObjectStatus

if TYPE_CHECKING:
    from irl.stepper import Stepper

ROTATE_DURATION_MS = 1000


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
        self.start_time: Optional[float] = None
        self.command_sent = False

    def _emitObjectEvent(self, obj) -> None:
        event = KnownObjectEvent(
            tag="known_object",
            data=KnownObjectData(
                uuid=obj.uuid,
                created_at=obj.created_at,
                updated_at=obj.updated_at,
                status=KnownObjectStatus(obj.status),
                part_id=obj.part_id,
                category_id=obj.category_id,
                confidence=obj.confidence,
                destination_bin=obj.destination_bin,
                thumbnail=obj.thumbnail,
                top_image=obj.top_image,
                bottom_image=obj.bottom_image,
            ),
        )
        self.event_queue.put(event)

    def step(self) -> Optional[ClassificationState]:
        if not self.shared.distribution_ready:
            return None

        if self.start_time is None:
            self.start_time = time.time()
            self.logger.info("Rotating: starting rotation")
            self.stepper.rotate(-90.0)
            self.command_sent = True

        elapsed_ms = (time.time() - self.start_time) * 1000
        if elapsed_ms < ROTATE_DURATION_MS:
            return None

        self.logger.info("Rotating: rotation complete")
        exiting = self.carousel.rotate()
        if exiting:
            self.logger.info(f"Rotating: piece {exiting.uuid[:8]} exited carousel")

        piece_at_exit = self.carousel.getPieceAtExit()
        if piece_at_exit is not None and (
            piece_at_exit.part_id is not None
            or piece_at_exit.status in ("unknown", "not_found")
        ):
            label = piece_at_exit.part_id or piece_at_exit.status
            self.logger.info(
                f"Rotating: piece {piece_at_exit.uuid[:8]} ({label}) now at exit, queueing for distribution"
            )
            piece_at_exit.status = "distributing"
            piece_at_exit.updated_at = time.time()
            self._emitObjectEvent(piece_at_exit)
            self.shared.distribution_ready = False
            self.shared.pending_piece = piece_at_exit
        else:
            self.shared.pending_piece = None

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
        self.start_time = None
        self.command_sent = False
