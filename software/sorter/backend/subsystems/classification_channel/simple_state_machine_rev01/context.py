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
        # The subset actually submitted to Brickognize — selected by CAPTURING
        # when it spawns the classify thread, read by AWAITING_DISTRIBUTION when
        # it dumps the burst artifacts (the spawn/apply split spans two states).
        self.selected_captures: list[np.ndarray] = []
        self.last_capture_frame_ts: float = 0.0
        self.capturing_started_at: float = 0.0
        self.rotating_started_at: float = 0.0
        self.classify_started_at: float = 0.0
        self.discharging_started_at: float = 0.0
        self.classification_result: object = None
        self.classification_error: Optional[str] = None
        self.classify_thread: Optional[threading.Thread] = None
        self.classify_lock = threading.Lock()
        self.known_object: Optional[KnownObject] = None
        # Latched True once >=2 pieces are confirmed on the channel (over several
        # distinct frames) during a cycle. A multi-feed: classification can't be
        # trusted, so the piece is routed to MISC and the discharge clears every
        # piece off. Debounced via observeMultiFeed so a single noisy frame (one
        # piece split into two boxes, or a spurious detection) can't trip it.
        self.multi_feed_detected: bool = False
        self._multi_feed_streak: int = 0
        self._multi_feed_last_ts: float = -1.0

    def observeMultiFeed(self, n_pieces: int, frame_ts: float, threshold: int) -> bool:
        # Count consecutive DISTINCT frames with >=2 on-channel pieces; latch
        # only after the streak reaches the threshold. Dedup by frame ts because
        # the state machine ticks faster than perception produces frames, so the
        # same slot is read many times — counting ticks would let one frame
        # inflate the streak. Returns True only on the tick the latch first trips.
        if self.multi_feed_detected:
            return False
        if frame_ts == self._multi_feed_last_ts:
            return False
        self._multi_feed_last_ts = frame_ts
        if n_pieces >= 2:
            self._multi_feed_streak += 1
        else:
            self._multi_feed_streak = 0
        if self._multi_feed_streak >= max(1, int(threshold)):
            self.multi_feed_detected = True
            return True
        return False

    def reset(self) -> None:
        self.config = _loadConfig()
        self.captured_crops = []
        self.captured_crop_timestamps = []
        self.selected_captures = []
        self.last_capture_frame_ts = 0.0
        self.capturing_started_at = 0.0
        self.rotating_started_at = 0.0
        self.classify_started_at = 0.0
        self.discharging_started_at = 0.0
        self.classification_result = None
        self.classification_error = None
        self.classify_thread = None
        self.known_object = None
        self.multi_feed_detected = False
        self._multi_feed_streak = 0
        self._multi_feed_last_ts = -1.0
