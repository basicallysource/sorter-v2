"""Detection bbox overlays — MOG2 channel detector and GeminiSam dynamic detection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

import cv2
import numpy as np

if TYPE_CHECKING:
    from vision.classification_detection import ClassificationDetectionResult
    from vision.mog2_channel_detector import Mog2ChannelDetector


class DetectorOverlay:
    """Draws MOG2 channel detector bounding boxes and section labels.

    Used for feeder (default) and split_feeder channel cameras.
    """

    category = "detections"

    def __init__(
        self,
        detector: Mog2ChannelDetector,
        get_detections: Callable,
    ) -> None:
        self._detector = detector
        self._get_detections = get_detections

    def annotate(self, frame: np.ndarray) -> np.ndarray:
        frame = self._detector.annotateFrame(frame)
        from subsystems.feeder.analysis import getBboxSections

        for det in self._get_detections():
            x1, y1, x2, y2 = det.bbox
            secs = getBboxSections(det.bbox, det.channel)
            exit_zone = bool(secs & det.channel.exit_sections)
            drop = bool(secs & det.channel.dropzone_sections)
            label = f"ch{det.channel_id} {sorted(secs)} e={exit_zone} d={drop}"
            cv2.putText(frame, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 0), 1)
        return frame


class DynamicDetectionOverlay:
    """Draws GeminiSam bounding boxes (purple rectangles + index labels).

    Used for feeder channels and carousel in gemini_sam mode.
    """

    category = "detections"

    def __init__(
        self,
        get_detection: Callable[[], Optional[ClassificationDetectionResult]],
    ) -> None:
        self._get_detection = get_detection

    def annotate(self, frame: np.ndarray) -> np.ndarray:
        detection = self._get_detection()
        if detection is None:
            return frame
        for index, bbox in enumerate(detection.bboxes, start=1):
            x1, y1, x2, y2 = [int(value) for value in bbox]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (168, 85, 247), 2, cv2.LINE_AA)
            cv2.putText(
                frame,
                str(index),
                (x1 + 6, max(18, y1 + 18)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (168, 85, 247),
                2,
                cv2.LINE_AA,
            )
        return frame
