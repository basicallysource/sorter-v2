"""FrameOverlay protocol — single annotation pass over a frame."""

from __future__ import annotations

from typing import Protocol

import numpy as np


class FrameOverlay(Protocol):
    """Composable, ordered annotation pass.

    Overlays must not mutate the input array; they receive a copy.
    The ``category`` attribute tags the overlay so consumers can filter
    e.g. ``"regions"`` out of the annotated output.
    """

    category: str

    def annotate(self, frame: np.ndarray) -> np.ndarray: ...
