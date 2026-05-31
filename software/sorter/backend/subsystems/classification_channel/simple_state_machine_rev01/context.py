import threading
from typing import Optional

import numpy as np

from defs.known_object import KnownObject

from .rev01_config import Rev01Config, configFromDict


def _loadConfig() -> Rev01Config:
    try:
        from toml_config import getClassificationChannelRev01Config
        return configFromDict(getClassificationChannelRev01Config())
    except Exception:
        return Rev01Config()


class SimpleStateMachineRev01Context:
    """Mutable state shared across the rev01 state classes for one run."""

    def __init__(self) -> None:
        self.config: Rev01Config = _loadConfig()
        self.captured_crops: list[np.ndarray] = []
        self.captured_crop_timestamps: list[float] = []
        self.last_capture_frame_ts: float = 0.0
        self.rotating_started_at: float = 0.0
        self.classify_started_at: float = 0.0
        self.discharging_started_at: float = 0.0
        self.classification_result: object = None
        self.classification_error: Optional[str] = None
        self.classify_thread: Optional[threading.Thread] = None
        self.classify_lock = threading.Lock()
        self.known_object: Optional[KnownObject] = None

    def reset(self) -> None:
        self.config = _loadConfig()
        self.captured_crops = []
        self.captured_crop_timestamps = []
        self.last_capture_frame_ts = 0.0
        self.rotating_started_at = 0.0
        self.classify_started_at = 0.0
        self.discharging_started_at = 0.0
        self.classification_result = None
        self.classification_error = None
        self.classify_thread = None
        self.known_object = None
