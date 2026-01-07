from global_config import GlobalConfig
from defs.events import ServerToMainThreadEvent
from sorter_controller import SorterController


def handleServerToMainEvent(
    gc: GlobalConfig, controller: SorterController, event: ServerToMainThreadEvent
) -> None:
    if event.tag == "heartbeat":
        gc.logger.info(f"received heartbeat from server at {event.data.timestamp}")
    else:
        gc.logger.warn(f"unknown event tag: {event.tag}")
