import os
from logger import Logger


class GlobalConfig:
    def __init__(self):
        self.logger = None
        self.debug_level = 0


def mkGlobalConfig():
    gc = GlobalConfig()
    gc.debug_level = int(os.getenv("DEBUG_LEVEL", "0"))
    gc.logger = Logger(gc.debug_level)
    return gc
