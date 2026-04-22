from __future__ import annotations

from typing import Callable

import cv2
import numpy as np


class IgnoredRegionOverlay:
    category = "detections"

    def __init__(self, get_regions: Callable[[], list[dict[str, object]]]):
        self._get_regions = get_regions

    def annotate(self, frame: np.ndarray) -> np.ndarray:
        regions = self._get_regions() or []
        if not regions:
            return frame

        annotated = frame.copy()
        for region in regions:
            bbox = region.get("bbox")
            if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                continue
            try:
                x1, y1, x2, y2 = [int(round(float(v))) for v in bbox[:4]]
            except Exception:
                continue
            if x2 <= x1 or y2 <= y1:
                continue

            overlay = annotated.copy()
            cv2.rectangle(overlay, (x1, y1), (x2, y2), (48, 48, 48), -1)
            cv2.addWeighted(overlay, 0.11, annotated, 0.89, 0.0, annotated)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (90, 90, 90), 1, cv2.LINE_AA)

            label = str(region.get("label") or "ignored")
            (tw, th), baseline = cv2.getTextSize(
                label,
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                1,
            )
            pill_h = th + 8
            pill_w = tw + 8
            pill_x1 = x1
            pill_y1 = max(0, y1 - pill_h - 2)
            pill_x2 = pill_x1 + pill_w
            pill_y2 = pill_y1 + pill_h
            cv2.rectangle(annotated, (pill_x1, pill_y1), (pill_x2, pill_y2), (35, 35, 35), -1)
            cv2.putText(
                annotated,
                label,
                (pill_x1 + 4, pill_y2 - 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (170, 170, 170),
                1,
                cv2.LINE_AA,
            )

        return annotated
