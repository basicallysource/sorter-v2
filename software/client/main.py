from global_config import mkGlobalConfig
from server.api import app
from sorter_controller import SorterController
from message_queue.handler import handleServerToMainEvent
import uvicorn
import threading
import queue
import time

server_to_main_queue = queue.Queue()
main_to_server_queue = queue.Queue()


def runServer() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8000)


def main() -> None:
    gc = mkGlobalConfig()
    controller = SorterController()
    gc.logger.info("client starting...")

    server_thread = threading.Thread(target=runServer, daemon=True)
    server_thread.start()

    while True:
        try:
            event = server_to_main_queue.get(block=False)
            handleServerToMainEvent(gc, controller, event)
        except queue.Empty:
            pass

        time.sleep(gc.timeouts.main_loop_sleep)


if __name__ == "__main__":
    main()
