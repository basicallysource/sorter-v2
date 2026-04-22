"""FrameOutput protocol — encodes a frame for delivery."""

from __future__ import annotations

from typing import Protocol, Union

import numpy as np


class FrameOutput(Protocol):
    def encode(self, frame: np.ndarray, quality: int = 80) -> Union[bytes, str]: ...
