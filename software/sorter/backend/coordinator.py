from subsystems.shared_variables import SharedVariables
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from vision import VisionManager
from sorting_profile import mkSortingProfile
import queue
import time
from piece_transport import ClassificationChannelTransport
from subsystems.bus import TickBus


class Coordinator:
    def __init__(
        self,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        vision: VisionManager,
        event_queue: queue.Queue,
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
        self.sorting_profile = mkSortingProfile(gc)
        self._sync_set_progress_tracker()

        self.distribution_layout = irl.distribution_layout

        from subsystems.classification_channel.state_machine import (
            ClassificationChannelStateMachine,
        )
        from subsystems.distribution.state_machine import DistributionStateMachine
        from subsystems.feeder.pulse_perception.flow import PulsePerceptionFeeding

        self.transport = ClassificationChannelTransport()
        self.shared.transport = self.transport
        self.distribution = DistributionStateMachine(
            irl,
            gc,
            self.shared,
            self.sorting_profile,
            self.distribution_layout,
            event_queue,
            post_distribute_cooldown_s=float(
                getattr(irl_config.classification_channel_config, "post_distribute_cooldown_s", 0.0)
                or 0.0
            ),
        )
        self.classification = ClassificationChannelStateMachine(
            irl=irl,
            irl_config=irl_config,
            gc=gc,
            shared=self.shared,
            vision=vision,
            event_queue=event_queue,
            transport=self.transport,
        )
        self.feeder = PulsePerceptionFeeding(irl, irl_config, gc, self.shared, vision)
        self.gc.runtime_stats.observeStateTransition("feeder", None, "feeding")

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
        self.sorting_profile.setKitProgress(self.gc.set_progress_tracker)

        try:
            from server.set_progress_sync import getSetProgressSyncWorker

            getSetProgressSyncWorker().notify()
        except Exception:
            pass

    def reload_sorting_profile(self) -> None:
        self.sorting_profile.reload()
        self._sync_set_progress_tracker()

    def _active_incident(self) -> dict | None:
        runtime_stats = getattr(self.gc, "runtime_stats", None)
        if runtime_stats is None or not hasattr(runtime_stats, "activeIncident"):
            return None
        try:
            incident = runtime_stats.activeIncident()
        except Exception:
            return None
        return incident if isinstance(incident, dict) else None

    def _hold_process_for_incident(self, incident: dict) -> None:
        kind = str(incident.get("kind") or "active_incident")
        reason = f"incident:{kind}"
        self.shared.set_classification_gate(False, reason=reason)
        self.shared.set_distribution_gate(False, reason=reason)
        if hasattr(self.gc, "runtime_stats"):
            self.gc.runtime_stats.observeBlockedReason("coordinator", "active_incident")

    def _classification_should_step_during_incident(self, incident: dict) -> bool:
        """The C4 stall watchdog keeps ticking during its own incident: its
        step is what notices the channel going clear and auto-resolves it.
        Other incidents are process-level holds: classification must not
        reopen the C3->C4 gate after the coordinator deliberately closed it."""
        return incident.get("source_kind") == "c4_stall_watchdog"

    def step(self) -> None:
        # GIL-stall detector: wall-clock vs this thread's CPU time. A large gap
        # means the control loop spent its tick waiting: on the GIL while
        # another thread held it (typically worker threads running YOLO and
        # image work), or on the serial bus. process_time() would count every
        # thread's CPU and hide the gap.
        _coord_cpu_t0 = time.thread_time()
        coordinator_started = time.perf_counter()
        self.bus.begin_tick()
        active_incident = self._active_incident()
        if active_incident is not None:
            self._hold_process_for_incident(active_incident)
            if self._classification_should_step_during_incident(active_incident):
                classification_started = time.perf_counter()
                self.classification.step()
                self.gc.runtime_stats.observePerfMs(
                    "coordinator.step.classification_ms",
                    (time.perf_counter() - classification_started) * 1000.0,
                )
            self.gc.runtime_stats.observePerfMs(
                "coordinator.step.total_ms",
                (time.perf_counter() - coordinator_started) * 1000.0,
            )
            return
        distribution_started = time.perf_counter()
        self.distribution.step()
        self.gc.runtime_stats.observePerfMs(
            "coordinator.step.distribution_ms",
            (time.perf_counter() - distribution_started) * 1000.0,
        )
        classification_started = time.perf_counter()
        self.classification.step()
        self.gc.runtime_stats.observePerfMs(
            "coordinator.step.classification_ms",
            (time.perf_counter() - classification_started) * 1000.0,
        )
        feeder_started = time.perf_counter()
        self.feeder.step()
        self.gc.runtime_stats.observePerfMs(
            "coordinator.step.feeder_ms",
            (time.perf_counter() - feeder_started) * 1000.0,
        )
        _coord_wall_ms = (time.perf_counter() - coordinator_started) * 1000.0
        _coord_cpu_ms = (time.thread_time() - _coord_cpu_t0) * 1000.0
        self.gc.runtime_stats.observePerfMs(
            "coordinator.step.total_ms",
            _coord_wall_ms,
        )
        self.gc.runtime_stats.observePerfMs(
            "coordinator.step.cpu_ms",
            _coord_cpu_ms,
        )
        self.gc.runtime_stats.observePerfMs(
            "coordinator.step.gil_stall_ms",
            max(0.0, _coord_wall_ms - _coord_cpu_ms),
        )

    def cleanup(self) -> None:
        self.feeder.cleanup()
        self.classification.cleanup()
        self.distribution.cleanup()
