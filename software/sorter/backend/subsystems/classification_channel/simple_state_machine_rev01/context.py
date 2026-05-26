import threading
from typing import Optional

import numpy as np


class SimpleStateMachineRev01Context:
    """Mutable state shared across the rev01 state classes for one run."""

    def __init__(self) -> None:
        self.captured_frames: list[np.ndarray] = []
        self.last_capture_at: float = 0.0
        self.rotating_started_at: float = 0.0
        self.classify_started_at: float = 0.0
        self.discharging_started_at: float = 0.0
        self.classification_result: object = None
        self.classification_error: Optional[str] = None
        self.classify_thread: Optional[threading.Thread] = None
        self.classify_lock = threading.Lock()

    def reset(self) -> None:
        self.captured_frames = []
        self.last_capture_at = 0.0
        self.rotating_started_at = 0.0
        self.classify_started_at = 0.0
        self.discharging_started_at = 0.0
        self.classification_result = None
        self.classification_error = None
        self.classify_thread = None
