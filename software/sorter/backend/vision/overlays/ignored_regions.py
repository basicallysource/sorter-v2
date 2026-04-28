from __future__ import annotations

from typing import Callable

import cv2
import numpy as np

from .scaling import overlay_scale_for_frame, scaled_px


class IgnoredRegionOverlay:
    # Static tracker-ignored regions ("ghosts") are useful for debugging,
    # but the normal operator view should not draw them over the live stream.
    category = "ghosts"

    def __init__(self, get_regions: Callable[[], list[dict[str, object]]]):
        self._get_regions = get_regions

    def annotate(self, frame: np.ndarray) -> np.ndarray:
        regions = self._get_regions() or []
        if not regions:
            return frame

        annotated = frame.copy()
        scale = overlay_scale_for_frame(frame)
        box_thickness = scaled_px(1, scale)
        font_scale = 0.45 * scale
        font_thickness = scaled_px(1, scale)
        pill_pad = scaled_px(4, scale)
        pill_margin = scaled_px(2, scale)
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
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (90, 90, 90), box_thickness, cv2.LINE_AA)

            label = str(region.get("label") or "ignored")
            (tw, th), baseline = cv2.getTextSize(
                label,
                cv2.FONT_HERSHEY_SIMPLEX,
                font_scale,
                font_thickness,
            )
            pill_h = th + pill_pad * 2
            pill_w = tw + pill_pad * 2
            pill_x1 = x1
            pill_y1 = max(0, y1 - pill_h - pill_margin)
            pill_x2 = pill_x1 + pill_w
            pill_y2 = pill_y1 + pill_h
            cv2.rectangle(annotated, (pill_x1, pill_y1), (pill_x2, pill_y2), (35, 35, 35), -1)
            cv2.putText(
                annotated,
                label,
                (pill_x1 + pill_pad, pill_y2 - pill_pad),
                cv2.FONT_HERSHEY_SIMPLEX,
                font_scale,
                (170, 170, 170),
                font_thickness,
                cv2.LINE_AA,
            )

        return annotated
