from global_config import GlobalConfig
from defs.events import ServerToMainThreadEvent
from sorter_controller import SorterController


def handleServerToMainEvent(gc: GlobalConfig, controller: SorterController, event: ServerToMainThreadEvent) -> None:
    if event.tag == "machine_started":
        gc.logger.info(f"machine started at {event.data.timestamp}")
    else:
        gc.logger.warn(f"unknown event tag: {event.tag}")
