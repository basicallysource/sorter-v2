from enum import Enum


class SorterLifecycle(Enum):
    INITIALIZING = "initializing"
    SHUTDOWN = "shutdown"
    STOPPING = "stopping"
    STARTING = "starting"
    READY = "ready"
    PAUSED = "paused"
    RUNNING = "running"
