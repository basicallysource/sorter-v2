from subsystems import (
    SharedVariables,
    FeederStateMachine,
    ClassificationStateMachine,
    DistributionStateMachine,
)
from subsystems.classification.carousel import Carousel
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from runtime_variables import RuntimeVariables
from vision import VisionManager
from sorting_profile import mkSortingProfile
from telemetry import Telemetry
import queue


class Coordinator:
    def __init__(
        self,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        vision: VisionManager,
        event_queue: queue.Queue,
        rv: RuntimeVariables,
        telemetry: Telemetry,
    ):
        self.irl = irl
        self.irl_config = irl_config
        self.gc = gc
        self.logger = gc.logger
        self.vision = vision
        self.event_queue = event_queue
        self.shared = SharedVariables()
        self.feeding_mode = getattr(irl_config, "feeding_mode", "auto_channels")
        self.manual_feed_mode = self.feeding_mode == "manual_carousel"
        self.sorting_profile = mkSortingProfile(gc)
        self._sync_set_progress_tracker()

        self.distribution_layout = irl.distribution_layout

        self.carousel = Carousel(gc.logger, event_queue)
        self.shared.carousel = self.carousel

        self.distribution = DistributionStateMachine(
            irl,
            gc,
            self.shared,
            self.sorting_profile,
            self.distribution_layout,
            event_queue,
        )
        self.classification = ClassificationStateMachine(
            irl, gc, self.shared, vision, event_queue, telemetry, self.carousel
        )
        self.feeder = FeederStateMachine(irl, irl_config, gc, self.shared, vision)
        if self.manual_feed_mode:
            self.logger.info(
                "Coordinator: manual carousel feed mode enabled; automatic C-channel feeding is disabled."
            )

    def _sync_set_progress_tracker(self) -> None:
        existing_tracker = getattr(self.gc, "set_progress_tracker", None)
        if existing_tracker is not None:
            existing_tracker.save()

        self.gc.set_progress_tracker = None
        if self.sorting_profile.is_set_based and self.sorting_profile.set_inventories:
            from set_progress import SetProgressTracker

            self.gc.set_progress_tracker = SetProgressTracker(
                self.sorting_profile.set_inventories,
                self.sorting_profile.artifact_hash,
            )

        try:
            from server.set_progress_sync import getSetProgressSyncWorker

            getSetProgressSyncWorker().notify()
        except Exception:
            pass

    def reload_sorting_profile(self) -> None:
        self.sorting_profile.reload()
        self._sync_set_progress_tracker()

    def step(self) -> None:
        prof = self.gc.profiler
        prof.hit("coordinator.step.calls")
        prof.mark("coordinator.step.interval_ms")

        with prof.timer("coordinator.step.total_ms"):
            with prof.timer("coordinator.step.feeder_ms"):
                if self.manual_feed_mode:
                    prof.hit("coordinator.step.feeder_skipped.manual_feed_mode")
                else:
                    self.feeder.step()
            with prof.timer("coordinator.step.classification_ms"):
                self.classification.step()
            with prof.timer("coordinator.step.distribution_ms"):
                self.distribution.step()

    def cleanup(self) -> None:
        self.feeder.cleanup()
        self.classification.cleanup()
        self.distribution.cleanup()
