from global_config import mkGlobalConfig, GlobalConfig
from server.api import app, broadcastEvent
from sorter_controller import SorterController
from message_queue.handler import handleServerToMainEvent
from defs.events import HeartbeatEvent, HeartbeatData, MainThreadToServerCommand
from irl.config import mkIRLConfig, mkIRLInterface
import uvicorn
import threading
import queue
import time
import asyncio
import sys

SHUTDOWN_MOTOR_STOP_DELAY_MS = 100

server_to_main_queue = queue.Queue()
main_to_server_queue = queue.Queue()


def runServer() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")


def runBroadcaster(gc: GlobalConfig) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    while True:
        try:
            command = main_to_server_queue.get(block=False)
            gc.logger.info(f"broadcasting {command.tag} event")
            loop.run_until_complete(broadcastEvent(command.model_dump()))
        except queue.Empty:
            pass

        time.sleep(gc.timeouts.main_loop_sleep_ms / 1000.0)


def main() -> None:
    gc = mkGlobalConfig()
    irl_config = mkIRLConfig()
    irl = mkIRLInterface(irl_config, gc)
    controller = SorterController(irl, gc)
    gc.logger.info("client starting...")

    server_thread = threading.Thread(target=runServer, daemon=True)
    server_thread.start()

    broadcaster_thread = threading.Thread(
        target=runBroadcaster, args=(gc,), daemon=True
    )
    broadcaster_thread.start()

    last_heartbeat = time.time()

    try:
        while True:
            try:
                event = server_to_main_queue.get(block=False)
                handleServerToMainEvent(gc, controller, event)
            except queue.Empty:
                pass

            # send periodic heartbeat
            current_time = time.time()
            if (
                current_time - last_heartbeat
                >= gc.timeouts.heartbeat_interval_ms / 1000.0
            ):
                heartbeat = HeartbeatEvent(
                    tag="heartbeat", data=HeartbeatData(timestamp=current_time)
                )
                main_to_server_queue.put(heartbeat)
                last_heartbeat = current_time

            controller.step()

            time.sleep(gc.timeouts.main_loop_sleep_ms / 1000.0)
    except KeyboardInterrupt:
        gc.logger.info("Shutting down...")

        # Clear any pending motor commands
        while not irl.mcu.command_queue.empty():
            try:
                irl.mcu.command_queue.get_nowait()
                irl.mcu.command_queue.task_done()
            except:
                break

        # Send motor shutdown commands and wait for them to complete
        gc.logger.info("Stopping all motors...")
        irl.shutdownMotors()
        irl.mcu.flush()  # Wait for shutdown commands to actually be sent

        irl.mcu.close()
        gc.logger.info("Cleanup complete")
        sys.exit(0)


if __name__ == "__main__":
    main()
