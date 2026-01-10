import os
from logger import Logger


class Timeouts:
    main_loop_sleep_ms: float
    heartbeat_interval_ms: float

    def __init__(self):
        self.main_loop_sleep_ms = 10
        self.heartbeat_interval_ms = 5000


class DefaultMotorSpeeds:
    first_v_channel: int
    second_v_channel: int
    third_v_channel: int

    def __init__(self):
        self.first_v_channel = 50
        self.second_v_channel = -140
        self.third_v_channel = -140


class GlobalConfig:
    logger: Logger
    debug_level: int
    timeouts: Timeouts
    default_motor_speeds: DefaultMotorSpeeds

    def __init__(self):
        self.debug_level = 0


def mkTimeouts() -> Timeouts:
    timeouts = Timeouts()
    return timeouts


def mkDefaultMotorSpeeds() -> DefaultMotorSpeeds:
    motor_speeds = DefaultMotorSpeeds()
    return motor_speeds


def mkGlobalConfig() -> GlobalConfig:
    gc = GlobalConfig()
    gc.debug_level = int(os.getenv("DEBUG_LEVEL", "0"))
    gc.logger = Logger(gc.debug_level)
    gc.timeouts = mkTimeouts()
    gc.default_motor_speeds = mkDefaultMotorSpeeds()
    return gc
