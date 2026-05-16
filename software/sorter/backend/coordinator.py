from subsystems import (
    SharedVariables,
)
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from runtime_variables import RuntimeVariables
from vision import VisionManager
from sorting_profile import mkSortingProfile
import queue
import threading
import time
from machine_setup import get_machine_setup_definition
from machine_runtime import build_machine_runtime
from subsystems.bus import TickBus
from subsystems.channels.base import (
    CHANNEL_EXIT_STUCK_SOURCE_KIND,
    EXIT_RELEASE_DEFAULT_ACCELERATION_MICROSTEPS_PER_SECOND_SQ,
    EXIT_RELEASE_DEFAULT_CYCLES,
    EXIT_RELEASE_DEFAULT_MAX_AUTO_ATTEMPTS,
    EXIT_RELEASE_DEFAULT_OUTPUT_DEG,
    EXIT_RELEASE_DEFAULT_SPEED_MICROSTEPS_PER_SECOND,
    EXIT_WIGGLE_OVERLAP_THRESHOLD,
)
from subsystems.feeder.analysis import analyzeFeederChannels


CHANNEL_EXIT_RELEASE_GEAR_RATIO = 130.0 / 12.0
CHANNEL_EXIT_RELEASE_SETTLE_S = 0.12


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
        self._channel_exit_auto_threads: dict[str, threading.Thread] = {}
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
            irl_config=irl_config,
            gc=gc,
            shared=self.shared,
            sorting_profile=self.sorting_profile,
            distribution_layout=self.distribution_layout,
            event_queue=event_queue,
            vision=vision,
        )
        self.classification = self.machine_runtime.create_classification(
            irl=irl,
            irl_config=irl_config,
            gc=gc,
            shared=self.shared,
            vision=vision,
            event_queue=event_queue,
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

    def _is_channel_exit_incident(self, incident: dict | None) -> bool:
        if not isinstance(incident, dict):
            return False
        kind = incident.get("kind")
        source_kind = incident.get("source_kind")
        if kind == "channel_exit_stuck":
            return True
        if kind != "exit_stuck":
            return False
        if source_kind not in (None, CHANNEL_EXIT_STUCK_SOURCE_KIND):
            return False
        return incident.get("channel") in {"c2", "c3"}

    def _channel_exit_stepper(self, channel: str):
        if channel == "c2":
            return getattr(self.irl, "c_channel_2_rotor_stepper", None)
        if channel == "c3":
            return getattr(self.irl, "c_channel_3_rotor_stepper", None)
        return None

    def _channel_exit_release_plan(self, *, amplitude_output_deg: float, cycles: int) -> list[tuple[str, float, float]]:
        amplitude_stepper = float(amplitude_output_deg) * CHANNEL_EXIT_RELEASE_GEAR_RATIO
        plan: list[tuple[str, float, float]] = []
        for cycle in range(1, int(cycles) + 1):
            is_last_cycle = cycle == int(cycles)
            plan.extend(
                [
                    (f"auto-release.{cycle}.cw", amplitude_stepper, CHANNEL_EXIT_RELEASE_SETTLE_S),
                    (f"auto-release.{cycle}.ccw-cross", -2.0 * amplitude_stepper, CHANNEL_EXIT_RELEASE_SETTLE_S),
                    (f"auto-release.{cycle}.cw-return", amplitude_stepper, 0.0 if is_last_cycle else CHANNEL_EXIT_RELEASE_SETTLE_S),
                ]
            )
        return plan

    def _publish_channel_exit_auto_status(
        self,
        incident: dict,
        *,
        status: str,
        awaiting_operator: bool,
        **extra,
    ) -> bool:
        runtime_stats = getattr(self.gc, "runtime_stats", None)
        if runtime_stats is None or not hasattr(runtime_stats, "activeIncident"):
            return False
        active = runtime_stats.activeIncident()
        if not self._is_channel_exit_incident(active):
            return False
        if active.get("channel") != incident.get("channel"):
            return False
        updated = dict(active)
        updated.update(extra)
        updated["status"] = status
        updated["awaiting_operator"] = bool(awaiting_operator)
        runtime_stats.setActiveIncident(updated)
        return True

    def _clear_channel_exit_incident_if_current(self, incident: dict) -> bool:
        runtime_stats = getattr(self.gc, "runtime_stats", None)
        if runtime_stats is None or not hasattr(runtime_stats, "activeIncident"):
            return False
        active = runtime_stats.activeIncident()
        if not self._is_channel_exit_incident(active):
            return False
        if active.get("channel") != incident.get("channel"):
            return False
        runtime_stats.clearActiveIncident(kind=str(active.get("kind") or "exit_stuck"))
        return True

    def _channel_exit_overlap(self, channel: str) -> float | None:
        try:
            detections = self.vision.getFeederHeatmapDetections()
            analysis = analyzeFeederChannels(self.gc, detections)
        except Exception as exc:
            self.logger.warning(f"Coordinator: could not verify {channel} exit release: {exc}")
            return None
        key = "ch2_exit_overlap_max" if channel == "c2" else "ch3_exit_overlap_max"
        try:
            return float(getattr(analysis, key, 0.0) or 0.0)
        except Exception:
            return None

    def _run_channel_exit_auto_release(self, incident: dict) -> None:
        channel = str(incident.get("channel") or "")
        stepper = self._channel_exit_stepper(channel)
        if stepper is None:
            self._publish_channel_exit_auto_status(
                incident,
                status="waiting_for_operator",
                awaiting_operator=True,
                auto_release_failed=True,
                operator_message="Automatic exit release could not run because the channel stepper is unavailable.",
            )
            return

        max_attempts = max(1, int(incident.get("auto_attempts_max") or EXIT_RELEASE_DEFAULT_MAX_AUTO_ATTEMPTS))
        amplitude = float(incident.get("amplitude_output_deg") or EXIT_RELEASE_DEFAULT_OUTPUT_DEG)
        speed = int(incident.get("microsteps_per_second") or EXIT_RELEASE_DEFAULT_SPEED_MICROSTEPS_PER_SECOND)
        acceleration = int(
            incident.get("acceleration_microsteps_per_second_sq")
            or EXIT_RELEASE_DEFAULT_ACCELERATION_MICROSTEPS_PER_SECOND_SQ
        )
        cycles = max(1, int(incident.get("cycles") or EXIT_RELEASE_DEFAULT_CYCLES))
        plan = self._channel_exit_release_plan(amplitude_output_deg=amplitude, cycles=cycles)

        for attempt in range(1, max_attempts + 1):
            if not self._publish_channel_exit_auto_status(
                incident,
                status="auto_release_running",
                awaiting_operator=False,
                auto_attempt_number=attempt,
                auto_attempts_completed=attempt - 1,
                auto_attempts_max=max_attempts,
                operator_message=None,
            ):
                return
            ok = True
            error = None
            strokes_completed = 0
            try:
                try:
                    stepper.enabled = True
                except Exception:
                    pass
                try:
                    stepper.set_speed_limits(16, int(speed))
                except Exception as exc:
                    raise RuntimeError(f"Could not apply exit-release speed: {exc}") from exc
                set_acceleration = getattr(stepper, "set_acceleration", None)
                if callable(set_acceleration):
                    try:
                        set_acceleration(int(acceleration))
                    except Exception as exc:
                        raise RuntimeError(f"Could not apply exit-release acceleration: {exc}") from exc

                for _label, move_deg, settle_s in plan:
                    move_blocking = getattr(stepper, "move_degrees_blocking", None)
                    if callable(move_blocking):
                        moved = bool(move_blocking(float(move_deg), timeout_ms=5000))
                    else:
                        moved = bool(stepper.move_degrees(float(move_deg)))
                    if not moved:
                        raise RuntimeError("Exit-release move was not acknowledged.")
                    strokes_completed += 1
                    if settle_s > 0.0:
                        time.sleep(float(settle_s))
            except Exception as exc:
                ok = False
                error = str(exc)

            if not ok:
                self._publish_channel_exit_auto_status(
                    incident,
                    status="waiting_for_operator",
                    awaiting_operator=True,
                    auto_release_failed=True,
                    auto_attempt_number=attempt,
                    auto_attempts_completed=attempt - 1,
                    auto_attempts_max=max_attempts,
                    last_test_ok=False,
                    last_test_error=error,
                    last_test_strokes_completed=strokes_completed,
                    operator_message=f"Automatic exit release failed: {error}",
                )
                return

            time.sleep(0.35)
            overlap = self._channel_exit_overlap(channel)
            if overlap is not None and overlap < EXIT_WIGGLE_OVERLAP_THRESHOLD:
                self.logger.info(
                    f"Coordinator: {channel} exit-stuck auto release solved after "
                    f"attempt {attempt}/{max_attempts} (overlap {overlap:.2f})"
                )
                self._clear_channel_exit_incident_if_current(incident)
                return

            if attempt < max_attempts:
                self._publish_channel_exit_auto_status(
                    incident,
                    status="waiting_for_operator",
                    awaiting_operator=False,
                    auto_attempt_number=attempt,
                    auto_attempts_completed=attempt,
                    auto_attempts_max=max_attempts,
                    last_test_ok=True,
                    last_test_strokes_completed=strokes_completed,
                    exit_overlap_after_release=overlap,
                )
                continue

            self._publish_channel_exit_auto_status(
                incident,
                status="waiting_for_operator",
                awaiting_operator=True,
                auto_release_failed=True,
                auto_attempt_number=attempt,
                auto_attempts_completed=attempt,
                auto_attempts_max=max_attempts,
                last_test_ok=True,
                last_test_strokes_completed=strokes_completed,
                exit_overlap_after_release=overlap,
                operator_message="Automatic exit release tried 3 times and the piece still appears stuck. Please intervene manually.",
            )

    def _maybe_start_auto_incident_resolution(self, incident: dict) -> None:
        if not self._is_channel_exit_incident(incident):
            return
        try:
            from toml_config import incidentHandlingAutomatic

            if not incidentHandlingAutomatic("channel_exit_stuck"):
                return
        except Exception:
            return
        status = str(incident.get("status") or "")
        if status in {"auto_release_running", "manual_test_running", "running", "approved"}:
            return
        if bool(incident.get("auto_release_failed")):
            return
        channel = str(incident.get("channel") or "")
        thread = self._channel_exit_auto_threads.get(channel)
        if thread is not None and thread.is_alive():
            return
        thread = threading.Thread(
            target=self._run_channel_exit_auto_release,
            args=(dict(incident),),
            daemon=True,
        )
        self._channel_exit_auto_threads[channel] = thread
        thread.start()

    def step(self) -> None:
        prof = self.gc.profiler
        prof.hit("coordinator.step.calls")
        prof.mark("coordinator.step.interval_ms")

        with prof.timer("coordinator.step.total_ms"):
            self.bus.begin_tick()
            active_incident = self._active_incident()
            if active_incident is not None:
                self._maybe_start_auto_incident_resolution(active_incident)
                self._hold_process_for_incident(active_incident)
                prof.hit("coordinator.step.distribution_skipped.active_incident")
                prof.hit("coordinator.step.feeder_skipped.active_incident")
                with prof.timer("coordinator.step.classification_ms"):
                    self.classification.step()
                return
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
