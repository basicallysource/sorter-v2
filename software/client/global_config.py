import os
from logger import Logger


class Timeouts:
    main_loop_sleep: float
    heartbeat_interval: float

    def __init__(self):
        self.main_loop_sleep = 0.1
        self.heartbeat_interval = 5.0


class GlobalConfig:
    logger: Logger
    debug_level: int
    timeouts: Timeouts

    def __init__(self):
        self.debug_level = 0


def mkTimeouts() -> Timeouts:
    timeouts = Timeouts()
    return timeouts


def mkGlobalConfig() -> GlobalConfig:
    gc = GlobalConfig()
    gc.debug_level = int(os.getenv("DEBUG_LEVEL", "0"))
    gc.logger = Logger(gc.debug_level)
    gc.timeouts = mkTimeouts()
    return gc
