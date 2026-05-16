"""Detection bbox overlays — MOG2 channel detector and GeminiSam dynamic detection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

import cv2
import numpy as np

if TYPE_CHECKING:
    from vision.classification_detection import ClassificationDetectionResult
    from vision.mog2_channel_detector import Mog2ChannelDetector


CENTER_MARKER_COLOR = (255, 255, 255)
CENTER_MARKER_OUTLINE = (0, 0, 0)
CENTER_MARKER_RADIUS = 4
CENTER_MARKER_ARM_PX = 9


def _bbox_center(bbox) -> tuple[int, int]:
    x1, y1, x2, y2 = [int(round(value)) for value in bbox]
    return int(round((x1 + x2) / 2.0)), int(round((y1 + y2) / 2.0))


def _draw_center_marker(frame: np.ndarray, center: tuple[int, int]) -> None:
    cx, cy = center
    cv2.circle(frame, (cx, cy), CENTER_MARKER_RADIUS + 2, CENTER_MARKER_OUTLINE, 2, cv2.LINE_AA)
    cv2.circle(frame, (cx, cy), CENTER_MARKER_RADIUS, CENTER_MARKER_COLOR, -1, cv2.LINE_AA)
    cv2.line(
        frame,
        (cx - CENTER_MARKER_ARM_PX, cy),
        (cx + CENTER_MARKER_ARM_PX, cy),
        CENTER_MARKER_OUTLINE,
        3,
        cv2.LINE_AA,
    )
    cv2.line(
        frame,
        (cx, cy - CENTER_MARKER_ARM_PX),
        (cx, cy + CENTER_MARKER_ARM_PX),
        CENTER_MARKER_OUTLINE,
        3,
        cv2.LINE_AA,
    )
    cv2.line(
        frame,
        (cx - CENTER_MARKER_ARM_PX, cy),
        (cx + CENTER_MARKER_ARM_PX, cy),
        CENTER_MARKER_COLOR,
        1,
        cv2.LINE_AA,
    )
    cv2.line(
        frame,
        (cx, cy - CENTER_MARKER_ARM_PX),
        (cx, cy + CENTER_MARKER_ARM_PX),
        CENTER_MARKER_COLOR,
        1,
        cv2.LINE_AA,
    )


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
            _draw_center_marker(frame, _bbox_center(det.bbox))
            secs = getBboxSections(det.bbox, det.channel)
            exit_zone = bool(secs & det.channel.exit_sections)
            drop = bool(secs & det.channel.dropzone_sections)
            label = f"ch{det.channel_id} {sorted(secs)} e={exit_zone} d={drop}"
            cv2.putText(frame, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 0), 1)
        return frame

    def metadata(self) -> list[dict[str, object]]:
        from subsystems.feeder.analysis import getBboxSections

        items: list[dict[str, object]] = []
        for det in self._get_detections():
            sections = getBboxSections(det.bbox, det.channel)
            items.append({
                "type": "detector_bbox",
                "category": self.category,
                "bbox": [int(round(value)) for value in det.bbox],
                "center": list(_bbox_center(det.bbox)),
                "channel_id": int(det.channel_id),
                "sections": sorted(int(section) for section in sections),
                "in_exit_zone": bool(sections & det.channel.exit_sections),
                "in_drop_zone": bool(sections & det.channel.dropzone_sections),
            })
        return items


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
            _draw_center_marker(frame, _bbox_center(bbox))
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

    def metadata(self) -> list[dict[str, object]]:
        detection = self._get_detection()
        if detection is None:
            return []
        return [
            {
                "type": "dynamic_detection_bbox",
                "category": self.category,
                "index": index,
                "bbox": [int(value) for value in bbox],
                "center": list(_bbox_center(bbox)),
            }
            for index, bbox in enumerate(detection.bboxes, start=1)
        ]
