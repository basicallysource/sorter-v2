from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from toml_config import migrateFromDataJson
migrateFromDataJson()

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
    setVisionManager,
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
from subsystems.classification.carousel_stepper import sensorlessHomeCarousel
from vision import VisionManager
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
                gc.runtime_stats.observeKnownObject(command.data.model_dump())
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
    with gc.profiler.timer("startup.vision_init_ms"):
        vision = VisionManager(irl_config, gc, irl)
        vision.setTelemetry(telemetry)
        setVisionManager(vision)
    # Controller is deferred until hardware is started
    controller = None
    gc.logger.info("client starting in standby mode (hardware not initialized)...")

    with gc.profiler.timer("startup.vision_start_ms"):
        vision.start()

    startup_total_ms = (time.time() - startup_total_start) * 1000
    gc.logger.info(f"standby startup complete in {startup_total_ms:.0f}ms")
    startup_report = gc.profiler.getReport()
    if startup_report:
        print(startup_report)

    # Register the hardware start function for the /api/system/home endpoint
    def _home_hardware() -> None:
        nonlocal irl, controller

        shared_state.hardware_homing_step = "Discovering hardware..."
        gc.logger.info("Starting hardware initialization...")
        real_irl = mkIRLInterface(irl_config, gc)
        irl.__dict__.update(real_irl.__dict__)

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

        if vision.initFeederDetection():
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

        # Home carousel if endstop is available
        carousel_stepper = getattr(irl, "carousel_stepper", None)
        if carousel_stepper is not None:
            shared_state.hardware_homing_step = "Homing carousel..."
            gc.logger.info("Homing carousel...")
            try:
                from server.routers.hardware import _home_carousel_stepper
                _home_carousel_stepper(irl, gc)
                gc.logger.info("Carousel homed successfully.")
            except Exception as e:
                gc.logger.warning(f"Carousel homing failed: {e}. Continuing without homing.")

        # Home chute/distributor if available
        shared_state.hardware_homing_step = "Homing distributor..."

        controller = SorterController(
            irl, irl_config, gc, vision, main_to_server_queue, rv, telemetry
        )
        setController(controller)
        controller.start()

        # Home the chute through the distribution state machine
        chute = getattr(controller.coordinator.distribution, "chute", None) if hasattr(controller, "coordinator") else None
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

    shared_state._hardware_start_fn = _home_hardware

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
                if controller is not None:
                    handleServerToMainEvent(gc, controller, event)
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
                frame_events = vision.getAllFrameEvents()
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

            if controller is not None:
                with gc.profiler.timer("main.loop.controller_step_ms"):
                    controller.step()

            time.sleep(gc.timeouts.main_loop_sleep_ms / 1000.0)
    except KeyboardInterrupt:
        gc.logger.info("Shutting down...")

        gc.run_recorder.save()

        vision.stop()

        gc.logger.info("Stopping all motors...")
        irl.shutdown()

        gc.logger.info("Cleanup complete")
        gc.logger.flushLogs()
        sys.exit(0)


if __name__ == "__main__":
    main()
