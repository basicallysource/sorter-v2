from global_config import GlobalConfig
from defs.events import ServerToMainThreadEvent
from sorter_controller import SorterController
from irl.config import IRLInterface


def handleServerToMainEvent(
    gc: GlobalConfig,
    controller: SorterController,
    irl: IRLInterface,
    event: ServerToMainThreadEvent,
) -> None:
    if event.tag == "pause":
        gc.logger.info("received pause command")
        controller.pause()
        irl.disableSteppers()
    elif event.tag == "resume":
        gc.logger.info("received resume command")
        irl.enableSteppers()
        controller.resume()
    elif event.tag == "heartbeat":
        gc.logger.info(f"received heartbeat from server at {event.data.timestamp}")
    else:
        gc.logger.warn(f"unknown event tag: {event.tag}")
