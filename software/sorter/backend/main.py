from dotenv import load_dotenv
import os
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from local_state import initialize_local_state
initialize_local_state()

from local_state import get_api_keys, remember_recent_known_object
_saved_api_keys = get_api_keys()
if _saved_api_keys.get("openrouter"):
    os.environ["OPENROUTER_API_KEY"] = _saved_api_keys["openrouter"]

from global_config import mkGlobalConfig, GlobalConfig
from runtime_variables import mkRuntimeVariables
from server.api import app
from server.shared_state import (
    broadcastEvent,
    setGlobalConfig,
    setRuntimeVariables,
    setCommandQueue,
    setController,
    setArucoManager,
    setCameraService,
    setVisionManager,
    setHardwareInitializeFn,
    setHardwareResetFn,
    setHardwareRuntimeIRL,
    setHardwareStartFn,
)
from aruco_config_manager import ArucoConfigManager
from sorter_controller import SorterController
from telemetry import Telemetry
from run_recorder import RunRecorder
from message_queue.handler import handleServerToMainEvent
from defs.events import HeartbeatEvent, HeartbeatData, MainThreadToServerCommand
from defs.events import RuntimeStatsEvent, RuntimeStatsData
from irl.config import mkIRLConfig, mkIRLInterface
from subsystems.feeder.calibration import calibrateFeederChannels
from vision import VisionManager
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
    from irl.config import IRLInterface, BinLayoutConfig, mkLayoutFromConfig
    from irl.bin_layout import getBinLayout
    irl = IRLInterface()
    irl.servos = []
    irl.distribution_layout = mkLayoutFromConfig(config.bin_layout_config)
    irl.machine_profile = None
    return irl


FRAME_BROADCAST_INTERVAL_MS = 100
RUNTIME_STATS_BROADCAST_INTERVAL_MS = 1000

server_to_main_queue = queue.Queue()
main_to_server_queue = queue.Queue()


def runServer() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error", ws="wsproto")


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
            if command.tag == "known_object":
                obj_payload = command.data.model_dump()
                gc.runtime_stats.observeKnownObject(obj_payload)
                remember_recent_known_object(obj_payload)
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
    rv = mkRuntimeVariables(gc)
    setRuntimeVariables(rv)
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

    with gc.profiler.timer("startup.telemetry_init_ms"):
        telemetry = Telemetry(gc)
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
    with gc.profiler.timer("startup.vision_init_ms"):
        vision = VisionManager(irl_config, gc, irl, camera_service)
        vision.setTelemetry(telemetry)
        setVisionManager(vision)
    # Controller is deferred until hardware is started
    controller = None
    controller_lock = threading.RLock()
    gc.logger.info("client starting in standby mode (hardware not initialized)...")

    with gc.profiler.timer("startup.camera_service_start_ms"):
        camera_service.start()
    with gc.profiler.timer("startup.vision_start_ms"):
        vision.start()
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
        with controller_lock:
            irl.__dict__.clear()
            irl.__dict__.update(next_irl.__dict__)

    def _cleanup_runtime_hardware(reason: str) -> None:
        nonlocal irl, controller

        gc.logger.info(f"Cleaning up hardware runtime: {reason}")
        setHardwareRuntimeIRL(None)

        with controller_lock:
            old_controller = controller
            controller = None
            setController(None)
            if old_controller is not None:
                try:
                    old_controller.stop()
                except Exception as exc:
                    gc.logger.warning(f"Failed to stop controller cleanly: {exc}")

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
        setHardwareRuntimeIRL(None)

    # Register the hardware start function for the /api/system/home endpoint
    def _home_hardware() -> None:
        nonlocal irl, controller

        with controller_lock:
            current_controller = controller
        active_irl = shared_state.getActiveIRL()
        if current_controller is not None or active_irl is not None and getattr(active_irl, "interfaces", {}):
            _cleanup_runtime_hardware("preparing for homing")

        shared_state.hardware_homing_step = "Discovering hardware..."
        gc.logger.info("Starting hardware initialization...")
        real_irl = mkIRLInterface(irl_config, gc)
        _replace_irl(real_irl)
        setHardwareRuntimeIRL(irl)
        manual_feed_mode = getattr(irl_config, "feeding_mode", "auto_channels") == "manual_carousel"

        if manual_feed_mode:
            gc.logger.info(
                "Manual carousel feed mode enabled: automatic C-channel feeding and feeder calibration are disabled."
            )

        if gc.disable_servos:
            gc.logger.info("Servo control disabled via --disable servos")
        else:
            shared_state.hardware_homing_step = "Opening servos..."
            gc.logger.info("Opening all layer servos...")
            for servo in irl.servos:
                try:
                    servo.open()
                except Exception as e:
                    gc.logger.warning(f"Failed to open servo: {e}. Continuing without initialization.")

        feeder_detection_ready = vision.initFeederDetection(manual_feed_mode=manual_feed_mode)
        if manual_feed_mode:
            if not feeder_detection_ready:
                gc.logger.warning(
                    "Manual carousel feed mode is enabled, but carousel trigger detection is not fully configured."
                )
        elif feeder_detection_ready:
            shared_state.hardware_homing_step = "Calibrating feeder channels..."
            calibrateFeederChannels(gc, irl, irl_config)
        else:
            gc.logger.warning("Feeder channel polygons not found — continuing without feeder detection")

        if irl_config.camera_layout == "split_feeder":
            has_classification = (
                vision._classification_top_capture is not None
                or vision._classification_bottom_capture is not None
            )
            if has_classification and vision.usesClassificationBaseline():
                if not vision.loadClassificationBaseline():
                    gc.logger.warning("Classification baseline not found — continuing without classification")
        elif vision.usesClassificationBaseline() and not vision.loadClassificationBaseline():
            gc.logger.warning("Classification baseline not found — continuing without classification")

        shared_state.hardware_homing_step = "Homing carousel..."
        carousel_hw = getattr(irl, "carousel_hw", None)
        if carousel_hw is not None:
            gc.logger.info("Homing carousel...")
            if carousel_hw.home():
                gc.logger.info("Carousel homed successfully.")
            else:
                gc.logger.warning("Carousel homing failed. Continuing without homing.")

        # Home chute/distributor if available
        shared_state.hardware_homing_step = "Homing distributor..."

        next_controller = SorterController(
            irl, irl_config, gc, vision, main_to_server_queue, rv, telemetry
        )
        with controller_lock:
            controller = next_controller
        setController(next_controller)
        next_controller.start()
        try:
            get_waveshare_inventory_manager().trigger_refresh()
        except Exception:
            pass

        # Home the chute through the distribution state machine
        chute = getattr(next_controller.coordinator.distribution, "chute", None) if hasattr(next_controller, "coordinator") else None
        if chute is not None:
            gc.logger.info("Homing chute...")
            try:
                if chute.home():
                    gc.logger.info("Chute homed successfully.")
                else:
                    gc.logger.warning("Chute homing failed. Continuing without homing.")
            except Exception as e:
                gc.logger.warning(f"Chute homing failed: {e}. Continuing without homing.")

        shared_state.hardware_homing_step = None
        gc.logger.info("Hardware initialization and homing complete.")

    def _initialize_hardware() -> None:
        """Bring up the IRL and enable steppers without homing carousel/chute.

        Used by the setup wizard's Motion Direction Check step so the operator
        can jog each stepper before endstops have been verified.
        """
        nonlocal irl, controller

        with controller_lock:
            current_controller = controller
        active_irl = shared_state.getActiveIRL()
        if current_controller is not None or active_irl is not None and getattr(active_irl, "interfaces", {}):
            _cleanup_runtime_hardware("preparing for stepper jog")

        shared_state.hardware_homing_step = "Discovering hardware..."
        gc.logger.info("Initializing hardware (no homing)...")
        real_irl = mkIRLInterface(irl_config, gc)
        _replace_irl(real_irl)
        setHardwareRuntimeIRL(irl)

        if gc.disable_servos:
            gc.logger.info("Servo control disabled via --disable servos")
        else:
            shared_state.hardware_homing_step = "Opening servos..."
            for servo in irl.servos:
                try:
                    servo.open()
                except Exception as e:
                    gc.logger.warning(f"Failed to open servo: {e}. Continuing without initialization.")

        shared_state.hardware_homing_step = None
        gc.logger.info("Hardware initialized (steppers ready, no homing performed).")

    setHardwareStartFn(_home_hardware)
    setHardwareInitializeFn(_initialize_hardware)
    setHardwareResetFn(lambda: _cleanup_runtime_hardware("system reset"))

    server_thread = threading.Thread(target=runServer, daemon=True)
    server_thread.start()

    broadcaster_thread = threading.Thread(
        target=runBroadcaster, args=(gc,), daemon=True
    )
    broadcaster_thread.start()

    last_heartbeat = time.time()
    last_frame_broadcast = time.time()
    last_runtime_stats_broadcast = time.time()

    try:
        while True:
            gc.profiler.hit("main.loop.calls")
            gc.profiler.mark("main.loop.interval_ms")
            try:
                event = server_to_main_queue.get(block=False)
                with controller_lock:
                    current_controller = controller
                if current_controller is not None:
                    handleServerToMainEvent(gc, current_controller, event)
            except queue.Empty:
                pass

            current_time = time.time()

            # send periodic heartbeat
            # can probably remove this later, just helps debug web sockets from time to time
            if (
                current_time - last_heartbeat
                >= gc.timeouts.heartbeat_interval_ms / 1000.0
            ):
                heartbeat = HeartbeatEvent(
                    tag="heartbeat", data=HeartbeatData(timestamp=current_time)
                )
                main_to_server_queue.put(heartbeat)
                last_heartbeat = current_time

            # broadcast cached camera frames and record to disk
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
                with gc.profiler.timer("main.loop.record_frames_ms"):
                    vision.recordFrames()
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

            with controller_lock:
                current_controller = controller
            if current_controller is not None:
                with gc.profiler.timer("main.loop.controller_step_ms"):
                    current_controller.step()

            time.sleep(gc.timeouts.main_loop_sleep_ms / 1000.0)
    except KeyboardInterrupt:
        gc.logger.info("Shutting down...")

        gc.run_recorder.save()

        vision.stop()
        camera_service.stop()

        gc.logger.info("Stopping all motors...")
        _cleanup_runtime_hardware("process shutdown")

        gc.logger.info("Cleanup complete")
        gc.logger.flushLogs()
        backend_process_guard.release()
        sys.exit(0)


if __name__ == "__main__":
    main()
