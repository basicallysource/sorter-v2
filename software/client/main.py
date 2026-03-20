from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from global_config import mkGlobalConfig, GlobalConfig
from runtime_variables import mkRuntimeVariables
from server.api import (
    app,
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

FRAME_BROADCAST_INTERVAL_MS = 100

server_to_main_queue = queue.Queue()
main_to_server_queue = queue.Queue()


def runServer() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error", ws="wsproto")


def runBroadcaster(gc: GlobalConfig) -> None:
    import server.api as api

    while api.server_loop is None:
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
            if command.tag != "frame" and command.tag != "heartbeat":
                gc.logger.info(f"broadcasting {command.tag} event")
            future = asyncio.run_coroutine_threadsafe(
                broadcastEvent(command.model_dump()), api.server_loop
            )
            try:
                future.result(timeout=1.0)
            except Exception:
                pass

        time.sleep(gc.timeouts.main_loop_sleep_ms / 1000.0)



def main() -> None:
    gc = mkGlobalConfig()
    gc.run_recorder = RunRecorder(gc)
    setGlobalConfig(gc)
    rv = mkRuntimeVariables(gc)
    setRuntimeVariables(rv)
    setCommandQueue(server_to_main_queue)
    irl_config = mkIRLConfig()
    
    # Initialize ArUco tag configuration manager
    aruco_config_path = Path(__file__).resolve().parent / "aruco_config.json"
    aruco_mgr = ArucoConfigManager(str(aruco_config_path))
    setArucoManager(aruco_mgr)
    
    irl = mkIRLInterface(irl_config, gc)

    gc.logger.info("Opening all layer servos...")
    for servo in irl.servos:
        try:
            servo.open()
        except Exception as e:
            gc.logger.warning(f"Failed to open servo: {e}. Continuing without initialization.")

    gc.logger.info("Homing chute to zero...")
    irl.chute.home()
    # sensorlessHomeCarousel(gc, irl)

    telemetry = Telemetry(gc)
    vision = VisionManager(irl_config, gc, irl)
    vision.setTelemetry(telemetry)
    setVisionManager(vision)
    controller = SorterController(
        irl, irl_config, gc, vision, main_to_server_queue, rv, telemetry
    )
    setController(controller)
    gc.logger.info("client starting...")

    vision.start()
    if not vision.initFeederDetection():
        gc.logger.error("Feeder channel polygons not found. Run: uv run python scripts/polygon_editor.py")
        sys.exit(1)
    calibrateFeederChannels(gc, irl, irl_config)

    if not vision.loadClassificationBaseline():
        gc.logger.error("Classification baseline not found. Run: uv run python scripts/calibrate_classification_baseline.py (with pieces removed from classification chamber)")
        sys.exit(1)
    controller.start()

    server_thread = threading.Thread(target=runServer, daemon=True)
    server_thread.start()

    broadcaster_thread = threading.Thread(
        target=runBroadcaster, args=(gc,), daemon=True
    )
    broadcaster_thread.start()

    last_heartbeat = time.time()
    last_frame_broadcast = time.time()

    try:
        while True:
            gc.profiler.hit("main.loop.calls")
            gc.profiler.mark("main.loop.interval_ms")
            try:
                event = server_to_main_queue.get(block=False)
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
