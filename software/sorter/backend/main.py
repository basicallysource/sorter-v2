"""Sorter backend entry point — rt-runtime only.

Post-cutover (2026-04-22): the legacy SorterController / coordinator /
subsystems runtime is gone. The live sorting loop is now the rt/ graph
(C1 -> C2 -> C3 -> C4 -> Distributor) assembled by
:func:`rt.bootstrap.build_rt_runtime`. Main.py wires up:

1. Process guard + GlobalConfig + RunRecorder
2. IRL config + ArucoConfigManager
3. CameraService
4. FastAPI + WS server thread + broadcaster thread
5. Hardware home/init/reset callbacks for the ``/api/system/*`` routes
6. rt_handle lifecycle (full runtime starts with backend/reset; homing is separate)
7. server_to_main_queue lifecycle command drain (pause/resume)
"""

from dotenv import load_dotenv
import os
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from local_state import initialize_local_state
initialize_local_state()

from local_state import get_api_keys
_saved_api_keys = get_api_keys()
if _saved_api_keys.get("openrouter"):
    os.environ["OPENROUTER_API_KEY"] = _saved_api_keys["openrouter"]

from global_config import mkGlobalConfig, GlobalConfig
from server.api import app
from server.shared_state import (
    broadcastEvent,
    publishSorterState,
    setGlobalConfig,
    setCommandQueue,
    setArucoManager,
    setCameraService,
    setHardwareRuntimeIRL,
    setRtHandle,
    setSorterLifecycle,
)
from server.sorter_lifecycle import SorterLifecyclePort
from aruco_config_manager import ArucoConfigManager
from run_recorder import RunRecorder
from defs.events import HeartbeatEvent, HeartbeatData
from defs.events import RuntimeStatsEvent, RuntimeStatsData
from irl.config import mkIRLConfig, mkIRLInterface
from process_guard import acquire_backend_process_guard, ProcessGuardError
from hardware.waveshare_bus_service import close_all_waveshare_bus_services
from server.waveshare_inventory import get_waveshare_inventory_manager
import uvicorn
import threading
import queue
import time
import asyncio
import sys


def _mkIRLInterfaceStandby(config, gc):
    """Create a minimal IRLInterface without hardware discovery (standby mode)."""
    from irl.config import IRLInterface, mkLayoutFromConfig
    irl = IRLInterface()
    irl.servos = []
    irl.distribution_layout = mkLayoutFromConfig(config.bin_layout_config)
    irl.machine_profile = None
    # Keep the irl_config reachable off the handle so routers that go
    # through ``shared_state.getActiveIRL()`` can still read machine_setup /
    # classification_channel_config etc.
    irl.irl_config = config
    return irl


FRAME_BROADCAST_INTERVAL_MS = 100
RUNTIME_STATS_BROADCAST_INTERVAL_MS = 1000

SERVO_BUS_ALERT_PREFIX = "Servo bus offline"

server_to_main_queue = queue.Queue()
main_to_server_queue = queue.Queue()


def _checkServoBusHealth(gc: GlobalConfig, irl) -> None:
    """After ``servo.open()``, surface a fatal hardware banner if every
    configured layer servo reports ``available=False``. Mirrors the
    pre-cutover behavior so operator still gets the red banner.
    """
    import server.shared_state as shared_state

    servos = list(getattr(irl, "servos", []) or [])
    if not servos:
        return
    available = [bool(getattr(s, "available", True)) for s in servos]
    if any(available):
        return

    message = (
        f"{SERVO_BUS_ALERT_PREFIX} — no layer servos responded at boot. "
        "Check Waveshare USB + power, then press Resume."
    )
    gc.logger.error(message)
    try:
        gc.runtime_stats.setServoBusOffline()
    except Exception:
        pass
    try:
        with shared_state.hardware_lifecycle_lock:
            shared_state.setHardwareStatus(error=message)
    except Exception:
        pass


def runServer() -> None:
    # Bind to loopback by default. Setting SORTER_API_HOST=0.0.0.0 (or a
    # specific IP) exposes the API to the LAN.
    host = os.getenv("SORTER_API_HOST", "127.0.0.1") or "127.0.0.1"
    uvicorn.run(app, host=host, port=8000, log_level="error", ws="wsproto")


def runBroadcaster(gc: GlobalConfig) -> None:
    import server.shared_state as shared_state

    while shared_state.server_loop is None:
        time.sleep(0.01)

    while True:
        latest_frame_commands = {}
        pending_commands = []

        while True:
            try:
                command = main_to_server_queue.get(block=False)
            except queue.Empty:
                break

            if command.tag == "frame":
                latest_frame_commands[command.data.camera] = command
            else:
                pending_commands.append(command)

        pending_commands.extend(latest_frame_commands.values())

        for command in pending_commands:
            if (
                command.tag != "frame"
                and command.tag != "heartbeat"
                and command.tag != "runtime_stats"
            ):
                gc.logger.info(f"broadcasting {command.tag} event")
            future = asyncio.run_coroutine_threadsafe(
                broadcastEvent(command.model_dump()), shared_state.server_loop
            )
            try:
                future.result(timeout=1.0)
            except Exception:
                pass

        time.sleep(gc.timeouts.main_loop_sleep_ms / 1000.0)


def main() -> None:
    import server.shared_state as shared_state

    script_path = Path(__file__).resolve()
    repo_root = script_path.parents[2]
    try:
        backend_process_guard = acquire_backend_process_guard(
            script_path=script_path,
            repo_root=repo_root,
            port=8000,
        )
    except ProcessGuardError as exc:
        print(f"[process_guard] {exc}", file=sys.stderr)
        sys.exit(1)

    gc = mkGlobalConfig()
    gc.run_recorder = RunRecorder(gc)
    setGlobalConfig(gc)
    setCommandQueue(server_to_main_queue)
    startup_total_start = time.time()

    with gc.profiler.timer("startup.irl_config_ms"):
        irl_config = mkIRLConfig()

    # Initialize ArUco tag configuration manager
    with gc.profiler.timer("startup.aruco_config_ms"):
        aruco_config_path = Path(__file__).resolve().parent / "aruco_config.json"
        aruco_mgr = ArucoConfigManager(str(aruco_config_path))
        setArucoManager(aruco_mgr)

    # Create a minimal IRL interface (no hardware discovery yet)
    irl = _mkIRLInterfaceStandby(irl_config, gc)
    # Expose to routers immediately — even in standby, getActiveIRL() should
    # return a readable shape so routers can fetch machine_setup metadata.
    setHardwareRuntimeIRL(irl)
    stepper_thermal_guard = None

    with gc.profiler.timer("startup.camera_service_init_ms"):
        from vision.camera_service import CameraService
        from defs.events import CameraHealthEvent, CameraHealthData
        camera_service = CameraService(irl_config, gc)
        setCameraService(camera_service)

        def _on_camera_health_change(health_map: dict[str, str]) -> None:
            event = CameraHealthEvent(
                tag="camera_health",
                data=CameraHealthData(cameras=health_map),
            )
            main_to_server_queue.put(event)

        camera_service.set_health_event_callback(_on_camera_health_change)

    gc.logger.info("backend starting in standby (hardware not initialized)...")

    # Bring up the API/broadcast threads before the heavier camera startup.
    server_thread = threading.Thread(target=runServer, daemon=True)
    server_thread.start()

    broadcaster_thread = threading.Thread(
        target=runBroadcaster, args=(gc,), daemon=True
    )
    broadcaster_thread.start()

    with gc.profiler.timer("startup.camera_service_start_ms"):
        camera_service.start()
    with gc.profiler.timer("startup.camera_overlays_ms"):
        from server.camera_annotations import attach_camera_annotations

        attach_camera_annotations(camera_service)
    with gc.profiler.timer("startup.waveshare_inventory_ms"):
        waveshare_inventory = get_waveshare_inventory_manager()
        waveshare_inventory.start()
        waveshare_inventory.refresh()

    startup_total_ms = (time.time() - startup_total_start) * 1000
    gc.logger.info(f"standby startup complete in {startup_total_ms:.0f}ms")
    startup_report = gc.profiler.getReport()
    if startup_report:
        print(startup_report)

    def _replace_irl(next_irl) -> None:
        nonlocal irl
        # Keep the IRLInterface identity stable for any refs already held;
        # only swap the attributes.
        irl.__dict__.clear()
        irl.__dict__.update(next_irl.__dict__)

    def _thermal_guard_steppers() -> dict[str, object]:
        return {
            name: stepper
            for name, stepper in {
                "c_channel_1": getattr(irl, "c_channel_1_rotor_stepper", None),
                "c_channel_2": getattr(irl, "c_channel_2_rotor_stepper", None),
                "c_channel_3": getattr(irl, "c_channel_3_rotor_stepper", None),
                "carousel": getattr(irl, "carousel_stepper", None),
                "chute": getattr(irl, "chute_stepper", None),
            }.items()
            if stepper is not None
        }

    def _handle_stepper_thermal_fault(fault) -> None:
        message = f"{fault.message}. Motors stopped and runtime paused."
        gc.logger.error(message)
        rt = shared_state.rt_handle
        if rt is not None:
            try:
                rt.pause()
                gc.runtime_stats.setLifecycleState("paused")
                layout = getattr(getattr(irl, "irl_config", None), "camera_layout", None)
                publishSorterState("paused", layout)
            except Exception:
                gc.logger.exception("Failed to pause rt runtime after stepper thermal fault")
        with shared_state.hardware_lifecycle_lock:
            shared_state.setHardwareStatus(
                state="error",
                error=message,
                clear_homing_step=True,
            )

    def _start_stepper_thermal_guard(reason: str) -> None:
        nonlocal stepper_thermal_guard
        _stop_stepper_thermal_guard(f"restart for {reason}")
        steppers = _thermal_guard_steppers()
        if not steppers:
            return
        from rt.services.stepper_thermal_guard import StepperThermalGuard

        interval_s = float(os.getenv("SORTER_STEPPER_THERMAL_GUARD_INTERVAL_S", "2.0"))
        stop_on_prewarn = (
            os.getenv("SORTER_STEPPER_THERMAL_STOP_ON_PREWARN", "1").strip().lower()
            not in {"0", "false", "no", "off"}
        )
        stepper_thermal_guard = StepperThermalGuard(
            steppers=steppers,
            on_fault=_handle_stepper_thermal_fault,
            logger=gc.logger,
            interval_s=interval_s,
            stop_on_prewarn=stop_on_prewarn,
        )
        stepper_thermal_guard.start()
        gc.logger.info(
            "Stepper thermal guard started for %s (%s)",
            ", ".join(sorted(steppers)),
            reason,
        )

    def _stop_stepper_thermal_guard(reason: str) -> None:
        nonlocal stepper_thermal_guard
        guard = stepper_thermal_guard
        if guard is None:
            return
        gc.logger.info(f"Stopping stepper thermal guard ({reason})")
        try:
            guard.stop()
        except Exception as exc:
            gc.logger.warning(f"Stepper thermal guard stop raised: {exc}")
        stepper_thermal_guard = None

    def _stop_rt_handle(reason: str) -> None:
        """Tear down the rt/ runtime graph, if running."""
        rt = shared_state.rt_handle
        if rt is None:
            return
        gc.logger.info(f"Stopping rt runtime ({reason})")
        try:
            rt.stop()
        except Exception as exc:
            gc.logger.warning(f"rt runtime stop raised: {exc}")
        setRtHandle(None)
        layout = getattr(getattr(irl, "irl_config", None), "camera_layout", None)
        gc.runtime_stats.setLifecycleState("initializing")
        publishSorterState("initializing", layout)

    def _build_rt_handle(*, start: bool, paused: bool = False, reason: str) -> None:
        mode = "live" if start else "idle"
        gc.logger.info(f"Building rt runtime ({mode}; reason={reason})")
        from rt.bootstrap import build_rt_runtime

        rt_handle = build_rt_runtime(
            camera_service=camera_service,
            gc=gc,
            irl=irl,
            logger=gc.logger,
        )
        if start:
            rt_handle.start(paused=paused)
            gc.logger.info(
                "rt runtime started%s.",
                " (paused)" if paused else "",
            )
            gc.runtime_stats.setLifecycleState("paused" if paused else "running")
        else:
            rt_handle.start_perception()
            gc.logger.info("rt runtime perception primed.")
            gc.runtime_stats.setLifecycleState("initializing")
        setRtHandle(rt_handle)
        layout = getattr(getattr(irl, "irl_config", None), "camera_layout", None)
        if start:
            publishSorterState("paused" if paused else "running", layout)
        else:
            publishSorterState("initializing", layout)

    def _cleanup_runtime_hardware(reason: str) -> None:
        nonlocal irl

        gc.logger.info(f"Cleaning up hardware runtime: {reason}")

        _stop_stepper_thermal_guard(reason)
        _stop_rt_handle(reason)

        for servo in list(getattr(irl, "servos", [])):
            try:
                if hasattr(servo, "stop"):
                    servo.stop()
            except Exception as exc:
                gc.logger.warning(f"Failed to stop servo during cleanup: {exc}")

        try:
            irl.disableSteppers()
        except Exception as exc:
            gc.logger.warning(f"Failed to disable steppers during cleanup: {exc}")

        try:
            irl.shutdown()
        except Exception as exc:
            gc.logger.warning(f"Failed to shut down hardware interfaces cleanly: {exc}")

        try:
            close_all_waveshare_bus_services()
        except Exception as exc:
            gc.logger.warning(f"Failed to close Waveshare bus services cleanly: {exc}")
        try:
            get_waveshare_inventory_manager().trigger_refresh()
        except Exception:
            pass

        standby_irl = _mkIRLInterfaceStandby(irl_config, gc)
        _replace_irl(standby_irl)
        setHardwareRuntimeIRL(irl)

    def _home_hardware() -> None:
        """Discover hardware, home carousel + chute, then spin up rt-runtime."""
        nonlocal irl

        if shared_state.rt_handle is not None:
            _cleanup_runtime_hardware("preparing for homing")
        elif getattr(irl, "interfaces", {}):
            _cleanup_runtime_hardware("preparing for homing")

        shared_state.setHardwareStatus(homing_step="Discovering hardware...")
        gc.logger.info("Starting hardware initialization...")
        real_irl = mkIRLInterface(irl_config, gc)
        # Preserve irl_config reference so routers going through getActiveIRL
        # can reach it without holding a direct ref to main.py's closure.
        real_irl.irl_config = irl_config
        _replace_irl(real_irl)
        setHardwareRuntimeIRL(irl)
        _start_stepper_thermal_guard("hardware home")

        machine_setup = getattr(irl_config, "machine_setup", None)
        if machine_setup is not None:
            gc.logger.info(
                f"Machine setup: {machine_setup.key} "
                f"(auto_feeder={machine_setup.automatic_feeder}, "
                f"carousel_transport={machine_setup.uses_carousel_transport})"
            )

        if gc.disable_servos:
            gc.logger.info("Servo control disabled via --disable servos")
        else:
            shared_state.setHardwareStatus(homing_step="Opening servos...")
            gc.logger.info("Opening all layer servos...")
            for servo in irl.servos:
                try:
                    servo.open()
                except Exception as e:
                    gc.logger.warning(
                        f"Failed to open servo: {e}. Continuing without initialization."
                    )
            _checkServoBusHealth(gc, irl)

        if bool(getattr(machine_setup, "homes_carousel", True)):
            shared_state.setHardwareStatus(homing_step="Homing carousel...")
            carousel_hw = getattr(irl, "carousel_hw", None)
            if carousel_hw is not None:
                gc.logger.info("Homing carousel...")
                if carousel_hw.home():
                    gc.logger.info("Carousel homed successfully.")
                else:
                    gc.logger.warning("Carousel homing failed. Continuing without homing.")
        else:
            gc.logger.info(
                "Skipping carousel homing for machine setup %r."
                % getattr(machine_setup, "key", "unknown")
            )

        # Home chute/distributor if available.
        shared_state.setHardwareStatus(homing_step="Homing distributor...")
        chute = getattr(irl, "chute", None)
        if chute is not None and hasattr(chute, "home"):
            gc.logger.info("Homing chute...")
            try:
                if chute.home():
                    gc.logger.info("Chute homed successfully.")
                else:
                    gc.logger.warning("Chute homing failed. Continuing without homing.")
            except Exception as e:
                gc.logger.warning(f"Chute homing failed: {e}. Continuing without homing.")

        # Build and start the rt runtime.
        shared_state.setHardwareStatus(homing_step="Starting rt runtime...")
        try:
            _build_rt_handle(start=True, paused=True, reason="hardware home")
        except Exception as exc:
            gc.logger.error(f"rt runtime build/start failed: {exc}")
            shared_state.setHardwareStatus(error=f"rt runtime failed: {exc}")
            shared_state.setHardwareStatus(clear_homing_step=True)
            return

        try:
            get_waveshare_inventory_manager().trigger_refresh()
        except Exception:
            pass

        shared_state.setHardwareStatus(clear_homing_step=True)
        gc.logger.info("Hardware initialization + rt runtime online.")

    def _initialize_hardware() -> None:
        """Bring up IRL + enable steppers without homing carousel/chute.

        Used by the setup wizard's Motion Direction Check step.
        """
        nonlocal irl

        if shared_state.rt_handle is not None or getattr(irl, "interfaces", {}):
            _cleanup_runtime_hardware("preparing for stepper jog")

        shared_state.setHardwareStatus(homing_step="Discovering hardware...")
        gc.logger.info("Initializing hardware (no homing)...")
        real_irl = mkIRLInterface(irl_config, gc)
        real_irl.irl_config = irl_config
        _replace_irl(real_irl)
        setHardwareRuntimeIRL(irl)
        _start_stepper_thermal_guard("hardware initialize")

        if gc.disable_servos:
            gc.logger.info("Servo control disabled via --disable servos")
        else:
            shared_state.setHardwareStatus(homing_step="Opening servos...")
            for servo in irl.servos:
                try:
                    servo.open()
                except Exception as e:
                    gc.logger.warning(
                        f"Failed to open servo: {e}. Continuing without initialization."
                    )
            _checkServoBusHealth(gc, irl)

        shared_state.setHardwareStatus(homing_step="Preparing rt runtime...")
        try:
            _build_rt_handle(start=True, paused=True, reason="hardware initialize")
        except Exception as exc:
            gc.logger.error(f"rt runtime build failed during initialize: {exc}")
            raise

        shared_state.setHardwareStatus(clear_homing_step=True)
        gc.logger.info("Hardware initialized (steppers ready, no homing performed).")

    setSorterLifecycle(
        SorterLifecyclePort(
            home_hardware=_home_hardware,
            initialize_hardware=_initialize_hardware,
            reset_hardware=lambda: _cleanup_runtime_hardware("system reset"),
            prepare_rt_handle=lambda: _build_rt_handle(
                start=True, paused=True, reason="standby prepare"
            ),
        )
    )

    try:
        with gc.profiler.timer("startup.rt_handle_prepare_ms"):
            _build_rt_handle(start=True, paused=True, reason="startup standby")
    except Exception as exc:
        gc.logger.error(f"rt runtime build/start failed during standby startup: {exc}")
        shared_state.setHardwareStatus(error=f"rt runtime failed: {exc}")

    last_heartbeat = time.time()
    last_frame_broadcast = time.time()
    last_runtime_stats_broadcast = time.time()

    try:
        while True:
            gc.profiler.hit("main.loop.calls")
            gc.profiler.mark("main.loop.interval_ms")

            # Drain server->main command queue. Post-cutover the only
            # meaningful commands are pause/resume which we forward straight
            # to the rt_handle.
            try:
                event = server_to_main_queue.get(block=False)
                rt = shared_state.rt_handle
                if event.tag == "pause":
                    gc.logger.info("received pause command")
                    if rt is not None:
                        try:
                            rt.pause()
                            gc.runtime_stats.setLifecycleState("paused")
                            layout = getattr(getattr(irl, "irl_config", None), "camera_layout", None)
                            publishSorterState("paused", layout)
                        except Exception:
                            gc.logger.exception("rt.pause raised")
                elif event.tag == "resume":
                    gc.logger.info("received resume command")
                    if rt is not None:
                        try:
                            rt.resume()
                            gc.runtime_stats.setLifecycleState("running")
                            layout = getattr(getattr(irl, "irl_config", None), "camera_layout", None)
                            publishSorterState("running", layout)
                        except Exception:
                            gc.logger.exception("rt.resume raised")
                elif event.tag == "heartbeat":
                    gc.logger.info(
                        f"received heartbeat from server at {event.data.timestamp}"
                    )
                else:
                    gc.logger.warn(f"unknown event tag: {event.tag}")
            except queue.Empty:
                pass

            current_time = time.time()

            # Heartbeat (keeps the WS channel from idle-disconnecting).
            if (
                current_time - last_heartbeat
                >= gc.timeouts.heartbeat_interval_ms / 1000.0
            ):
                heartbeat = HeartbeatEvent(
                    tag="heartbeat", data=HeartbeatData(timestamp=current_time)
                )
                main_to_server_queue.put(heartbeat)
                last_heartbeat = current_time

            # Frame broadcast: pump camera_service's ring into the WS channel.
            if (
                current_time - last_frame_broadcast
                >= FRAME_BROADCAST_INTERVAL_MS / 1000.0
            ):
                frame_events = camera_service.get_all_frame_events()
                gc.profiler.observeValue(
                    "main.loop.frame_events_count", float(len(frame_events))
                )
                for frame_event in frame_events:
                    main_to_server_queue.put(frame_event)
                last_frame_broadcast = current_time

            if (
                current_time - last_runtime_stats_broadcast
                >= RUNTIME_STATS_BROADCAST_INTERVAL_MS / 1000.0
            ):
                runtime_stats = RuntimeStatsEvent(
                    tag="runtime_stats",
                    data=RuntimeStatsData(payload=gc.runtime_stats.snapshot()),
                )
                main_to_server_queue.put(runtime_stats)
                last_runtime_stats_broadcast = current_time

            # rt orchestrator ticks itself on its own thread — main loop
            # only pumps frames + commands now.
            time.sleep(gc.timeouts.main_loop_sleep_ms / 1000.0)
    except KeyboardInterrupt:
        gc.logger.info("Shutting down...")

        gc.run_recorder.save()

        _stop_rt_handle("process shutdown")
        try:
            camera_service.stop()
        except Exception as exc:
            gc.logger.warning(f"camera_service.stop raised: {exc}")

        gc.logger.info("Stopping all motors...")
        _cleanup_runtime_hardware("process shutdown")

        gc.logger.info("Cleanup complete")
        gc.logger.flushLogs()
        backend_process_guard.release()
        sys.exit(0)


if __name__ == "__main__":
    main()
