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

        annotated = frame
        fh, fw = annotated.shape[:2]
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
            # Clip to frame, then blend only the bbox slice — avoids the
            # ~25 MB full-frame copy that used to dominate 4K annotation.
            cx1, cy1 = max(0, x1), max(0, y1)
            cx2, cy2 = min(fw, x2), min(fh, y2)
            if cx2 > cx1 and cy2 > cy1:
                slice_view = annotated[cy1:cy2, cx1:cx2]
                # Blend toward (48,48,48) with the same 0.11/0.89 weighting as
                # the old full-frame addWeighted, but in-place on the slice.
                cv2.addWeighted(
                    slice_view, 0.89,
                    np.full_like(slice_view, 48), 0.11,
                    0.0,
                    dst=slice_view,
                )
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

    def metadata(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for region in self._get_regions() or []:
            bbox = region.get("bbox")
            if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                continue
            try:
                normalized_bbox = [int(round(float(v))) for v in bbox[:4]]
            except Exception:
                continue
            items.append({
                "type": "ignored_region",
                "category": self.category,
                "label": str(region.get("label") or "ignored"),
                "bbox": normalized_bbox,
            })
        return items
