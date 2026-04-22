"""Heatmap diff annotation overlay."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from vision.heatmap_diff import HeatmapDiff


class HeatmapOverlay:
    """Draws heatmap diff visualization when baseline is captured.

    Used on feeder (carousel heatmap), carousel standalone, and classification cameras.
    """

    category = "heatmap"

    def __init__(
        self,
        heatmap: HeatmapDiff,
        label: str = "",
        text_y: int = 30,
    ) -> None:
        self._heatmap = heatmap
        self._label = label
        self._text_y = text_y

    def annotate(self, frame: np.ndarray) -> np.ndarray:
        if self._heatmap.has_baseline:
            return self._heatmap.annotateFrame(frame, label=self._label, text_y=self._text_y)
        return frame
