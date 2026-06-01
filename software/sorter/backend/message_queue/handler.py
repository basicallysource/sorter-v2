from global_config import GlobalConfig
from defs.events import ServerToMainThreadEvent
from sorter_controller import SorterController


def handleServerToMainEvent(
    gc: GlobalConfig,
    controller: SorterController,
    event: ServerToMainThreadEvent,
) -> None:
    if event.tag == "pause":
        gc.logger.info("received pause command")
        controller.pause()
    elif event.tag == "resume":
        gc.logger.info("received resume command")
        controller.resume()
    elif event.tag == "heartbeat":
        gc.logger.info(f"received heartbeat from server at {event.data.timestamp}")
    elif event.tag == "set_profiler_enabled":
        gc.logger.info(f"received set_profiler_enabled: {event.data.enabled}")
        gc.profiler.enabled = bool(event.data.enabled)
    else:
        gc.logger.warn(f"unknown event tag: {event.tag}")
