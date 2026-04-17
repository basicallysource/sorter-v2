"""Classification frame annotation overlay."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

import cv2
import numpy as np

if TYPE_CHECKING:
    from vision.classification_detection import ClassificationDetectionResult
    from vision.heatmap_diff import HeatmapDiff


class ClassificationOverlay:
    """Draws classification detection bboxes, labels, and margins.

    Handles both baseline (heatmap) and dynamic (gemini_sam) modes.
    """

    category = "detections"

    def __init__(
        self,
        cam: str,
        get_heatmap: Callable[[], Optional[HeatmapDiff]],
        uses_baseline: Callable[[], bool],
        get_combined_bbox: Callable[[str], Optional[tuple]],
        get_edge_biased_margins: Callable[[tuple, str], tuple],
        get_dynamic_detection: Callable[..., Optional[ClassificationDetectionResult]],
        get_diff_config: Callable[[], object],
        get_annotation_label: Callable[[str], str],
    ) -> None:
        self._cam = cam
        self._get_heatmap = get_heatmap
        self._uses_baseline = uses_baseline
        self._get_combined_bbox = get_combined_bbox
        self._get_edge_biased_margins = get_edge_biased_margins
        self._get_dynamic_detection = get_dynamic_detection
        self._get_diff_config = get_diff_config
        self._get_annotation_label = get_annotation_label

    def annotate(self, frame: np.ndarray) -> np.ndarray:
        uses_baseline = self._uses_baseline()
        heatmap = self._get_heatmap()

        if uses_baseline and heatmap is not None and heatmap.has_baseline:
            frame = heatmap.annotateFrame(
                frame,
                label=self._get_annotation_label(self._cam),
                text_y=30,
            )

        if not uses_baseline:
            detection = self._get_dynamic_detection(self._cam, force=False)
            if detection is not None:
                for candidate in detection.bboxes:
                    x1, y1, x2, y2 = [int(value) for value in candidate]
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (168, 85, 247), 2, cv2.LINE_AA)
                if detection.bbox is not None:
                    x1, y1, x2, y2 = [int(value) for value in detection.bbox]
                    cv2.putText(
                        frame,
                        "cloud",
                        (x1, max(16, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.45,
                        (168, 85, 247),
                        1,
                        cv2.LINE_AA,
                    )

        bbox = self._get_combined_bbox(self._cam) if uses_baseline else None
        diff_config = self._get_diff_config()
        if bbox is not None:
            margins = self._get_edge_biased_margins(bbox, self._cam)
            fh, fw = frame.shape[:2]
            mx1 = max(0, bbox[0] - margins[0])
            my1 = max(0, bbox[1] - margins[1])
            mx2 = min(fw, bbox[2] + margins[2])
            my2 = min(fh, bbox[3] + margins[3])
            cv2.rectangle(frame, (mx1, my1), (mx2, my2), (0, 200, 255), 2, cv2.LINE_AA)
            bias_parts = []
            base = diff_config.crop_margin_px
            for side, val in zip(["L", "T", "R", "B"], margins):
                if val != base:
                    bias_parts.append(f"{side}:{val}")
            bias_label = f"  ({', '.join(bias_parts)})" if bias_parts else ""
            method_label = (
                "baseline"
                if uses_baseline
                else diff_config.algorithm.replace("_", " ")
            )
            cv2.putText(
                frame,
                f"{method_label} crop +{base}px{bias_label}",
                (mx1, my1 - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 200, 255),
                1,
            )

        return frame
