from typing import Optional, TYPE_CHECKING
import time
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import ClassificationState
from .carousel import Carousel
from irl.config import IRLInterface
from global_config import GlobalConfig
from vision.heatmap_diff import HeatmapDiff, TRIGGER_SCORE

if TYPE_CHECKING:
    from vision import VisionManager

WAIT_FOR_SETTLE_TO_TAKE_BASELINE_MS = 500
DETECTION_HOLD_MS = 1000


class Detecting(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        carousel: Carousel,
        vision: "VisionManager",
        heatmap: HeatmapDiff,
    ):
        super().__init__(irl, gc)
        self.shared = shared
        self.carousel = carousel
        self.vision = vision
        self.heatmap = heatmap
        self._baseline_pending = True
        self._entered_at: Optional[float] = None
        self._detected_at: Optional[float] = None

    def step(self) -> Optional[ClassificationState]:
        now = time.time()
        if self._entered_at is None:
            self._entered_at = now

        # always push frames into the ring buffer for temporal averaging
        gray = self.vision.getLatestFeederGray()
        if gray is None:
            return None
        self.heatmap.pushFrame(gray)

        corners = self.vision.feeding_platform_corners
        if corners is None:
            return None

        # take a baseline after settling
        if self._baseline_pending:
            elapsed_ms = (now - self._entered_at) * 1000
            if elapsed_ms < WAIT_FOR_SETTLE_TO_TAKE_BASELINE_MS:
                return None
            ok = self.heatmap.captureBaseline(corners, gray.shape)
            if not ok:
                return None
            self._baseline_pending = False
            self.logger.info("Detecting: captured heatmap baseline")
            return None

        score, hot_px = self.heatmap.computeDiff()
        if score >= TRIGGER_SCORE:
            if self._detected_at is None:
                self._detected_at = now
                self.logger.info(
                    f"Detecting: piece detected via heatmap diff "
                    f"(score={score:.1f}, hot_px={hot_px}), holding {DETECTION_HOLD_MS}ms"
                )
            elif (now - self._detected_at) * 1000 >= DETECTION_HOLD_MS:
                self.logger.info(
                    f"Detecting: confirming detection "
                    f"(score={score:.1f}, hot_px={hot_px})"
                )
                self.shared.classification_ready = False
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
        self.heatmap.clearBaseline()
        self._baseline_pending = True
        self._entered_at = None
        self._detected_at = None
