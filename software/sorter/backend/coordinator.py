from subsystems import (
    SharedVariables,
)
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from runtime_variables import RuntimeVariables
from vision import VisionManager
from sorting_profile import mkSortingProfile
import queue
from machine_setup import get_machine_setup_definition
from machine_runtime import build_machine_runtime
from subsystems.bus import TickBus


class Coordinator:
    def __init__(
        self,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        vision: VisionManager,
        event_queue: queue.Queue,
        rv: RuntimeVariables,
    ):
        self.irl = irl
        self.irl_config = irl_config
        self.gc = gc
        self.logger = gc.logger
        self.vision = vision
        self.event_queue = event_queue
        self.bus = TickBus()
        self.gc.runtime_stats.setBusProvider(self.bus)
        self.shared = SharedVariables(gc=gc, bus=self.bus)
        self.feeding_mode = getattr(irl_config, "feeding_mode", "auto_channels")
        self.machine_setup = getattr(
            irl_config,
            "machine_setup",
            get_machine_setup_definition(None),
        )
        self.machine_runtime = build_machine_runtime(self.machine_setup.key)
        self.manual_feed_mode = self.machine_setup.manual_feed_mode
        self.gc.use_channel_bus = bool(
            getattr(self.gc, "use_channel_bus", False)
            or getattr(self.machine_setup, "uses_classification_channel", False)
        )
        self.sorting_profile = mkSortingProfile(gc)
        self._sync_set_progress_tracker()

        self.distribution_layout = irl.distribution_layout

        self.transport = self.machine_runtime.create_transport(
            gc=gc,
            event_queue=event_queue,
        )
        self.shared.transport = self.transport
        self.shared.carousel = (
            self.transport if hasattr(self.transport, "rotate") else None
        )

        self.distribution = self.machine_runtime.create_distribution(
            irl=irl,
            gc=gc,
            shared=self.shared,
            sorting_profile=self.sorting_profile,
            distribution_layout=self.distribution_layout,
            event_queue=event_queue,
        )
        self.classification = self.machine_runtime.create_classification(
            irl=irl,
            irl_config=irl_config,
            gc=gc,
            shared=self.shared,
            vision=vision,
            event_queue=event_queue,
            telemetry=telemetry,
            transport=self.transport,
        )
        self.feeder = self.machine_runtime.create_feeder(
            irl=irl,
            irl_config=irl_config,
            gc=gc,
            shared=self.shared,
            vision=vision,
        )
        if self.manual_feed_mode:
            self.logger.info(
                "Coordinator: manual carousel feed mode enabled; automatic C-channel feeding is disabled."
            )
        elif not self.machine_setup.runtime_supported:
            self.logger.warning(
                "Coordinator: machine setup %r is persisted, but runtime orchestration "
                "is not implemented yet."
                % self.machine_setup.key
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
            self.bus.begin_tick()
            with prof.timer("coordinator.step.distribution_ms"):
                self.distribution.step()
            with prof.timer("coordinator.step.classification_ms"):
                self.classification.step()
            with prof.timer("coordinator.step.feeder_ms"):
                if self.manual_feed_mode:
                    prof.hit("coordinator.step.feeder_skipped.manual_feed_mode")
                else:
                    self.feeder.step()

    def cleanup(self) -> None:
        self.feeder.cleanup()
        self.classification.cleanup()
        self.distribution.cleanup()
