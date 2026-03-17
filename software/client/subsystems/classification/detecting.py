from typing import Optional, TYPE_CHECKING
import time
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import ClassificationState
from .carousel import Carousel
from irl.config import IRLInterface
from global_config import GlobalConfig

if TYPE_CHECKING:
    from vision import VisionManager

WAIT_FOR_SETTLE_TO_TAKE_BASELINE_MS = 0
DEBOUNCE_MS = 0


class Detecting(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        carousel: Carousel,
        vision: "VisionManager",
    ):
        super().__init__(irl, gc)
        self.shared = shared
        self.carousel = carousel
        self.vision = vision
        self._baseline_pending = True
        self._entered_at: Optional[float] = None
        self._detected_at: Optional[float] = None
        self._ready_at: Optional[float] = None

    def step(self) -> Optional[ClassificationState]:
        now = time.time()
        if self._entered_at is None:
            self._entered_at = now

        if self._baseline_pending:
            elapsed_ms = (now - self._entered_at) * 1000
            if elapsed_ms < WAIT_FOR_SETTLE_TO_TAKE_BASELINE_MS:
                return None
            if not self.vision.captureCarouselBaseline():
                return None
            self._baseline_pending = False
            self.logger.info("Detecting: captured heatmap baseline")

        if not self.shared.classification_ready:
            if not self.shared.distribution_ready:
                return None
            self.shared.classification_ready = True
            self._ready_at = now
            elapsed_since_enter = (now - self._entered_at) * 1000 if self._entered_at else 0
            self.logger.info(f"Detecting: classification_ready=True ({elapsed_since_enter:.0f}ms since enter)")
            return None

        triggered, score, hot_px = self.vision.isCarouselTriggered()
        if triggered:
            if self._detected_at is None:
                self._detected_at = now
                self.logger.info(
                    f"Detecting: piece detected via heatmap diff "
                    f"(score={score:.1f}, hot_px={hot_px}), debouncing {DEBOUNCE_MS}ms"
                )
            elif (now - self._detected_at) * 1000 >= DEBOUNCE_MS:
                self.logger.info(
                    f"Detecting: confirming detection "
                    f"(score={score:.1f}, hot_px={hot_px})"
                )
                self.shared.classification_ready = False
                wait_ms = (now - self._ready_at) * 1000 if self._ready_at else 0
                total_ms = (now - self._entered_at) * 1000 if self._entered_at else 0
                self.logger.info(f"Detecting: confirmed -> ROTATING (wait_for_piece={wait_ms:.0f}ms, total={total_ms:.0f}ms)")
                self.carousel.addPieceAtFeeder()
                return ClassificationState.ROTATING
        else:
            if self._detected_at is not None:
                elapsed = (now - self._detected_at) * 1000
                self.logger.info(
                    f"Detecting: detection lost after {elapsed:.0f}ms "
                    f"(score={score:.1f}, hot_px={hot_px})"
                )
            self._detected_at = None

        return None

    def cleanup(self) -> None:
        super().cleanup()
        self.vision.clearCarouselBaseline()
        self._baseline_pending = True
        self._entered_at = None
        self._detected_at = None
        self._ready_at = None
