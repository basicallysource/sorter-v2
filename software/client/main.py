from global_config import mkGlobalConfig, GlobalConfig
from server.api import app, broadcastEvent
from sorter_controller import SorterController
from message_queue.handler import handleServerToMainEvent
from defs.events import HeartbeatEvent, HeartbeatData, MainThreadToServerCommand
import uvicorn
import threading
import queue
import time
import asyncio

server_to_main_queue = queue.Queue()
main_to_server_queue = queue.Queue()


def runServer() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8000)


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

        time.sleep(gc.timeouts.main_loop_sleep)


def main() -> None:
    gc = mkGlobalConfig()
    controller = SorterController()
    gc.logger.info("client starting...")

    server_thread = threading.Thread(target=runServer, daemon=True)
    server_thread.start()

    broadcaster_thread = threading.Thread(
        target=runBroadcaster, args=(gc,), daemon=True
    )
    broadcaster_thread.start()

    last_heartbeat = time.time()

    while True:
        try:
            event = server_to_main_queue.get(block=False)
            handleServerToMainEvent(gc, controller, event)
        except queue.Empty:
            pass

        # send periodic heartbeat
        current_time = time.time()
        if current_time - last_heartbeat >= gc.timeouts.heartbeat_interval:
            heartbeat = HeartbeatEvent(
                tag="heartbeat", data=HeartbeatData(timestamp=current_time)
            )
            main_to_server_queue.put(heartbeat)
            last_heartbeat = current_time

        time.sleep(gc.timeouts.main_loop_sleep)


if __name__ == "__main__":
    main()
