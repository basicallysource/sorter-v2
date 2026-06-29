"""Station state machine and hardware ownership.

The AGX runs ONE long-lived process (``app.py``). Cameras and the Pico serial buses can
only be held by one owner at a time, so this manager is the single place that acquires and
releases them, moving the station between modes:

    IDLE         nothing running; safe to (re)configure and calibrate
    CALIBRATING  a calibration routine owns the hardware (Phase 3)
    RUNNING      the sorter controller + vision loop are live

The old ``main.py`` hard-exited (``sys.exit``) when polygons/baselines were missing. Here
those preconditions become readiness flags surfaced over the API; ``start_run`` raises
``NotReadyError`` instead, so the web UI can gate the Run button and explain what's missing.
"""

from __future__ import annotations

import queue
import threading
import time
from enum import Enum
from typing import Any, Optional

from global_config import GlobalConfig


class StationMode(str, Enum):
    IDLE = "idle"
    CALIBRATING = "calibrating"
    RUNNING = "running"
    ERROR = "error"


class NotReadyError(Exception):
    """Raised when a mode transition is blocked by missing prerequisites.

    ``missing`` lists the unmet readiness keys so the UI can render specifics.
    """

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(f"not ready: missing {', '.join(missing)}")


# How often the run loop broadcasts cached camera frames to websocket clients.
FRAME_BROADCAST_INTERVAL_MS = 100


class StationManager:
    def __init__(self, gc: GlobalConfig, aruco_manager: Any):
        self.gc = gc
        self.aruco_manager = aruco_manager
        # Built lazily: mkIRLConfig() requires camera assignment, which on a fresh machine
        # the user hasn't done yet. The station must still boot into IDLE so the web UI can
        # drive first-time setup, so we only construct this when entering run/calibration.
        self.irl_config: Any = None

        self._mode = StationMode.IDLE
        self._lock = threading.RLock()
        self._error: Optional[str] = None

        # Hardware + runtime objects, built lazily on first run and torn down on stop.
        self._irl: Any = None
        self._vision: Any = None
        self._controller: Any = None
        self._telemetry: Any = None
        self._runtime_variables: Any = None

        # Cross-thread queues between the web server and the run loop.
        self.server_to_main_queue: "queue.Queue[Any]" = queue.Queue()
        self.main_to_server_queue: "queue.Queue[Any]" = queue.Queue()

        self._run_thread: Optional[threading.Thread] = None
        self._broadcaster_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Active calibration sessions/jobs (only one at a time; each owns hardware while open).
        self._camera_session: Any = None
        self._polygon_session: Any = None
        self._baseline_job: Any = None

    # ----- introspection -------------------------------------------------

    @property
    def mode(self) -> StationMode:
        return self._mode

    def readiness(self) -> dict[str, bool]:
        """Per-step completion flags, computed from persisted state (no hardware needed)."""
        from blob_manager import (
            get_camera_setup,
            get_channel_polygons,
            get_classification_polygons,
        )
        from calibration.cameras import REQUIRED_ROLES
        from calibration.classification_baseline import baseline_exists

        setup = get_camera_setup() or {}
        cameras_assigned = all(role in setup for role in REQUIRED_ROLES)

        return {
            "cameras_assigned": cameras_assigned,
            "feeder_polygons": get_channel_polygons() is not None,
            "classification_polygons": get_classification_polygons() is not None,
            "classification_baseline": baseline_exists(["classification"]),
        }

    def missing_to_run(self) -> list[str]:
        """Readiness keys that must be satisfied before the sorter can run."""
        ready = self.readiness()
        required = [
            "cameras_assigned",
            "feeder_polygons",
            "classification_polygons",
            "classification_baseline",
        ]
        return [k for k in required if not ready.get(k, False)]

    def state(self) -> dict[str, Any]:
        return {
            "mode": self._mode.value,
            "error": self._error,
            "readiness": self.readiness(),
            "missing_to_run": self.missing_to_run(),
        }

    # ----- run lifecycle -------------------------------------------------

    def start_run(self) -> None:
        with self._lock:
            if self._mode == StationMode.RUNNING:
                return
            if self._mode == StationMode.CALIBRATING:
                raise RuntimeError("cannot start run while calibrating")

            missing = self.missing_to_run()
            if missing:
                raise NotReadyError(missing)

            self._error = None
            self._stop_event.clear()
            self._build_and_start()
            self._mode = StationMode.RUNNING

    def stop_run(self) -> None:
        with self._lock:
            if self._mode != StationMode.RUNNING:
                return
            self._stop_event.set()

        # Join outside the lock so the run loop can drain.
        if self._run_thread is not None:
            self._run_thread.join(timeout=10)
        if self._broadcaster_thread is not None:
            self._broadcaster_thread.join(timeout=5)

        with self._lock:
            self._teardown()
            self._mode = StationMode.IDLE

    def shutdown(self) -> None:
        """Release ALL hardware from ANY mode. Idempotent; safe to call from a signal
        handler so Ctrl-C / SIGTERM always exits cleanly (cameras, Picos, motors freed)."""
        try:
            self.end_camera_assignment(save=False)
        except Exception as e:
            self.gc.logger.warning(f"camera session cleanup failed: {e}")
        try:
            self.end_polygon_session(save=False)
        except Exception as e:
            self.gc.logger.warning(f"polygon session cleanup failed: {e}")
        try:
            self.cancel_baseline(wait=True)
        except Exception as e:
            self.gc.logger.warning(f"baseline cleanup failed: {e}")
        try:
            self.stop_run()
        except Exception as e:
            self.gc.logger.warning(f"run cleanup failed: {e}")

    def _reconcile_baseline(self) -> None:
        """If the baseline job finished, drop it and return to IDLE."""
        if self._baseline_job is not None and self._baseline_job.finished:
            self._baseline_job = None
            if self._mode == StationMode.CALIBRATING:
                self._mode = StationMode.IDLE

    def _assert_calibration_free(self) -> None:
        self._reconcile_baseline()
        if self._mode == StationMode.RUNNING:
            raise RuntimeError("stop the run before calibrating")
        if (
            self._camera_session is not None
            or self._polygon_session is not None
            or self._baseline_job is not None
        ):
            raise RuntimeError("another calibration step is already active")

    # ----- camera assignment (calibration) -------------------------------

    def begin_camera_assignment(self) -> Any:
        with self._lock:
            if self._camera_session is not None:
                return self._camera_session  # idempotent re-entry
            self._assert_calibration_free()
            from calibration.cameras import CameraAssignmentSession

            self._camera_session = CameraAssignmentSession(self.gc)
            self._mode = StationMode.CALIBRATING
            return self._camera_session

    @property
    def camera_session(self) -> Any:
        return self._camera_session

    def end_camera_assignment(self, save: bool) -> None:
        with self._lock:
            session = self._camera_session
            if session is None:
                return
            if save:
                session.save()
            session.close()
            self._camera_session = None
            if self._mode == StationMode.CALIBRATING:
                self._mode = StationMode.IDLE

    # ----- polygon editing (calibration) ---------------------------------

    def begin_polygon_session(self) -> Any:
        with self._lock:
            if self._polygon_session is not None:
                return self._polygon_session  # idempotent re-entry
            self._assert_calibration_free()
            from calibration.polygons import PolygonSession

            self._polygon_session = PolygonSession(self.gc)
            self._mode = StationMode.CALIBRATING
            return self._polygon_session

    @property
    def polygon_session(self) -> Any:
        return self._polygon_session

    def end_polygon_session(self, save: bool) -> None:
        with self._lock:
            session = self._polygon_session
            if session is None:
                return
            session.close()
            self._polygon_session = None
            if self._mode == StationMode.CALIBRATING:
                self._mode = StationMode.IDLE

    # ----- classification baseline "wiggle" (calibration) ----------------

    def start_baseline(self, camera: str = "all", wipe: bool = True) -> dict:
        with self._lock:
            self._assert_calibration_free()
            from calibration.classification_baseline import BaselineJob
            from blob_manager import get_chute_wiggle_settings

            chute = get_chute_wiggle_settings()
            job = BaselineJob(
                self.gc, camera=camera, wipe=wipe,
                chute_hz=chute["hz"], chute_steps=chute["steps"],
            )
            self._baseline_job = job
            self._mode = StationMode.CALIBRATING
            job.start()
            return job.status()

    def get_chute_settings(self) -> dict:
        """Current chute wiggle params — live values if a baseline is running, else persisted."""
        from blob_manager import get_chute_wiggle_settings

        job = self._baseline_job
        if job is not None and not job.finished:
            s = job.status()
            return {"hz": s["chute_hz"], "steps": s["chute_steps"]}
        return get_chute_wiggle_settings()

    def set_chute_settings(self, hz: float, steps: int) -> dict:
        """Persist chute wiggle params and apply live to a running baseline job."""
        from blob_manager import set_chute_wiggle_settings

        set_chute_wiggle_settings(hz, steps)
        job = self._baseline_job
        if job is not None and not job.finished:
            job.update_chute(hz, steps)
        return {"hz": float(hz), "steps": int(steps)}

    def baseline_status(self) -> Optional[dict]:
        with self._lock:
            if self._baseline_job is None:
                return None
            status = self._baseline_job.status()
            self._reconcile_baseline()
            return status

    def cancel_baseline(self, wait: bool = False) -> None:
        with self._lock:
            job = self._baseline_job
        if job is None:
            return
        job.cancel()
        if wait:
            job.join(timeout=15)
        with self._lock:
            self._reconcile_baseline()

    # ----- internals -----------------------------------------------------

    def _ensure_irl_config(self) -> Any:
        """Build the IRL config on demand (needs camera assignment to exist)."""
        if self.irl_config is None:
            from irl.config import make_irl_config

            self.irl_config = make_irl_config()
        return self.irl_config

    def _build_and_start(self) -> None:
        """Construct the hardware/runtime objects and launch the run + broadcaster threads.

        Mirrors the old ``main.main()`` boot sequence, but as a relaunchable unit owned by
        the manager rather than a one-shot process.
        """
        from runtime_variables import make_runtime_variables
        from irl.config import make_irl_interface
        from telemetry import Telemetry
        from vision import VisionManager
        from sorter_controller import SorterController
        from subsystems.feeder.calibration import calibrate_feeder_channels
        import server.api as api

        gc = self.gc
        irl_config = self._ensure_irl_config()
        self._runtime_variables = make_runtime_variables(gc)
        api.set_runtime_variables(self._runtime_variables)
        api.set_command_queue(self.server_to_main_queue)

        irl = make_irl_interface(irl_config, gc)
        self._irl = irl

        gc.logger.info("Opening all layer servos...")
        for servo in irl.servos:
            try:
                servo.open()
            except Exception as e:
                gc.logger.warning(f"Failed to open servo: {e}. Continuing.")

        gc.logger.info("Homing chute to zero...")
        irl.chute.home()

        self._telemetry = Telemetry(gc)
        vision = VisionManager(irl_config, gc, irl)
        vision.set_telemetry(self._telemetry)
        self._vision = vision
        api.set_vision_manager(vision)

        controller = SorterController(
            irl,
            self.irl_config,
            gc,
            vision,
            self.main_to_server_queue,
            self._runtime_variables,
            self._telemetry,
        )
        self._controller = controller
        api.set_controller(controller)

        vision.start()
        if not vision.init_feeder_detection():
            raise NotReadyError(["feeder_polygons"])
        calibrate_feeder_channels(gc, irl, self.irl_config)

        if not vision.load_classification_baseline():
            raise NotReadyError(["classification_baseline"])
        if vision.is_carousel_hsv_mode() and not vision.load_carousel_hsv_baseline():
            raise NotReadyError(["classification_baseline"])

        controller.start()

        self._run_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._run_thread.start()
        self._broadcaster_thread = threading.Thread(target=self._broadcaster_loop, daemon=True)
        self._broadcaster_thread.start()

    def _teardown(self) -> None:
        gc = self.gc
        try:
            if self.gc.run_recorder is not None:
                gc.run_recorder.save()
        except Exception:
            pass
        try:
            if self._vision is not None:
                self._vision.stop()
        except Exception as e:
            gc.logger.warning(f"vision stop failed: {e}")
        try:
            if self._irl is not None:
                gc.logger.info("Stopping all motors...")
                self._irl.shutdown()
        except Exception as e:
            gc.logger.warning(f"irl shutdown failed: {e}")

        self._controller = None
        self._vision = None
        self._irl = None
        self._run_thread = None
        self._broadcaster_thread = None

    def _run_loop(self) -> None:
        """Relocated main-thread loop from the old ``main.py``: pump commands, heartbeat,
        broadcast frames, and step the controller until ``stop_run`` is requested."""
        from message_queue.handler import handle_server_to_main_event
        from defs.events import HeartbeatEvent, HeartbeatData

        gc = self.gc
        controller = self._controller
        vision = self._vision

        last_heartbeat = time.time()
        last_frame_broadcast = time.time()

        while not self._stop_event.is_set():
            gc.profiler.hit("main.loop.calls")
            gc.profiler.mark("main.loop.interval_ms")
            try:
                event = self.server_to_main_queue.get(block=False)
                handle_server_to_main_event(gc, controller, event)
            except queue.Empty:
                pass

            now = time.time()
            if now - last_heartbeat >= gc.timeouts.heartbeat_interval_ms / 1000.0:
                self.main_to_server_queue.put(
                    HeartbeatEvent(tag="heartbeat", data=HeartbeatData(timestamp=now))
                )
                last_heartbeat = now

            if now - last_frame_broadcast >= FRAME_BROADCAST_INTERVAL_MS / 1000.0:
                for frame_event in vision.get_all_frame_events():
                    self.main_to_server_queue.put(frame_event)
                with gc.profiler.timer("main.loop.record_frames_ms"):
                    vision.record_frames()
                last_frame_broadcast = now

            with gc.profiler.timer("main.loop.controller_step_ms"):
                controller.step()

            time.sleep(gc.timeouts.main_loop_sleep_ms / 1000.0)

    def _broadcaster_loop(self) -> None:
        """Drain the main->server queue and push events to websocket clients.

        Frame events are coalesced to the latest per camera so a slow client can't back
        up the queue. Relocated from the old ``main.runBroadcaster``.
        """
        import asyncio
        import server.api as api

        while api.server_loop is None and not self._stop_event.is_set():
            time.sleep(0.01)

        gc = self.gc
        while not self._stop_event.is_set():
            latest_frame_commands: dict[Any, Any] = {}
            pending: list[Any] = []
            while True:
                try:
                    command = self.main_to_server_queue.get(block=False)
                except queue.Empty:
                    break
                if command.tag == "frame":
                    latest_frame_commands[command.data.camera] = command
                else:
                    pending.append(command)
            pending.extend(latest_frame_commands.values())

            for command in pending:
                if command.tag not in ("frame", "heartbeat"):
                    gc.logger.info(f"broadcasting {command.tag} event")
                future = asyncio.run_coroutine_threadsafe(
                    api.broadcast_event(command.model_dump()), api.server_loop
                )
                try:
                    future.result(timeout=1.0)
                except Exception:
                    pass

            time.sleep(gc.timeouts.main_loop_sleep_ms / 1000.0)
