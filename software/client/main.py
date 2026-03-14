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
    setSortingProfile,
    setDistributionLayout,
)
from sorter_controller import SorterController
from telemetry import Telemetry
from message_queue.handler import handleServerToMainEvent
from defs.events import HeartbeatEvent, HeartbeatData, MainThreadToServerCommand
from blob_manager import appendKnownObjectRecord
from irl.config import mkIRLConfig, mkIRLInterface
from vision import VisionManager
import uvicorn
import threading
import queue
import time
import asyncio
import sys

SHUTDOWN_MOTOR_STOP_DELAY_MS = 100
FRAME_BROADCAST_INTERVAL_MS = 30

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
            if command.tag == "known_object":
                try:
                    appendKnownObjectRecord(
                        gc.machine_id,
                        gc.run_id,
                        command.data.model_dump(),
                    )
                except Exception as e:
                    gc.logger.warn(f"failed to append known object record: {e}")
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


def runFrameBroadcaster(gc: GlobalConfig, vision, broadcast_queue) -> None:
    prof = gc.profiler
    while True:
        prof.hit("frame_broadcast.calls")
        prof.mark("frame_broadcast.interval_ms")
        with prof.timer("frame_broadcast.total_ms"):
            with prof.timer("frame_broadcast.get_all_frame_events_ms"):
                frame_events = vision.getAllFrameEvents()
            prof.observeValue("frame_broadcast.frame_count", float(len(frame_events)))
            for frame_event in frame_events:
                broadcast_queue.put(frame_event)
        time.sleep(FRAME_BROADCAST_INTERVAL_MS / 1000.0)


def main() -> None:
    gc = mkGlobalConfig()
    setGlobalConfig(gc)
    rv = mkRuntimeVariables(gc)
    setRuntimeVariables(rv)
    setCommandQueue(server_to_main_queue)
    irl_config = mkIRLConfig()
    irl = mkIRLInterface(irl_config, gc)

    if not gc.disable_servos:
        gc.logger.info("Opening all layer servos...")
        for servo in irl.servos:
            servo.open()

    gc.logger.info("Homing chute to zero...")
    irl.chute.home()

    telemetry = Telemetry(gc)
    vision = VisionManager(irl_config, gc)
    vision.setTelemetry(telemetry)
    controller = SorterController(
        irl, irl_config, gc, vision, main_to_server_queue, rv, telemetry
    )
    setController(controller)
    setSortingProfile(controller.coordinator.sorting_profile)
    setDistributionLayout(controller.coordinator.distribution_layout)
    gc.logger.info("client starting...")

    vision.start()
    if not vision.loadFeederBaseline():
        gc.logger.error("Feeder baseline setup incomplete. See warnings above for details.")
        sys.exit(1)
    vision.startRecording()
    controller.start()

    server_thread = threading.Thread(target=runServer, daemon=True)
    server_thread.start()

    broadcaster_thread = threading.Thread(
        target=runBroadcaster, args=(gc,), daemon=True
    )
    broadcaster_thread.start()

    last_heartbeat = time.time()

    frame_broadcast_thread = threading.Thread(
        target=runFrameBroadcaster,
        args=(gc, vision, main_to_server_queue),
        daemon=True,
    )
    frame_broadcast_thread.start()

    try:
        while True:
            gc.profiler.hit("main.loop.calls")
            gc.profiler.mark("main.loop.interval_ms")
            try:
                event = server_to_main_queue.get(block=False)
                handleServerToMainEvent(gc, controller, irl, event)
            except queue.Empty:
                pass

            current_time = time.time()

            # send periodic heartbeat
            if (
                current_time - last_heartbeat
                >= gc.timeouts.heartbeat_interval_ms / 1000.0
            ):
                heartbeat = HeartbeatEvent(
                    tag="heartbeat", data=HeartbeatData(timestamp=current_time)
                )
                main_to_server_queue.put(heartbeat)
                last_heartbeat = current_time

            # push carousel heatmap frames on main thread so detection stays responsive
            gray = vision.getLatestFeederGray()
            if gray is not None:
                vision._carousel_heatmap.pushFrame(gray)

            with gc.profiler.timer("main.loop.controller_step_ms"):
                controller.step()

            time.sleep(gc.timeouts.main_loop_sleep_ms / 1000.0)
    except KeyboardInterrupt:
        gc.logger.info("Shutting down...")

        vision.stop()

        # Clear any pending motor commands
        while not irl.mcu.command_queue.empty():
            try:
                irl.mcu.command_queue.get_nowait()
                irl.mcu.command_queue.task_done()
            except:
                break

        # Send motor shutdown commands and wait for them to complete
        gc.logger.info("Stopping all motors...")
        irl.disableSteppers()
        irl.mcu.flush()
        irl.mcu.close()
        gc.logger.info("Cleanup complete")
        gc.logger.flushLogs()
        sys.exit(0)


if __name__ == "__main__":
    main()
