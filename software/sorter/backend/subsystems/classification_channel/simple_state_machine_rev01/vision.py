import math
from typing import Optional

import cv2
import numpy as np

from global_config import GlobalConfig
from .constants import LOG_TAG


class Rev01Vision:
    """Thin read-only view over the VisionManager for rev01.

    Keeps all rev01 vision access in one place and applies the same
    center-in-polygon channel-membership test the feeder channels use
    (``analysis._isInChannel`` / ``determineObjectChannel``): a piece only
    counts as "on the channel" when its bbox center lies inside the carousel
    zone polygon. The shared carousel detection accessor returns everything in
    the polygon's bounding rectangle, which clips in neighbouring clutter (the
    loose-brick hopper in the corner), so the membership test is required.
    """

    def __init__(self, vision, gc: GlobalConfig):
        self._vision = vision
        self.gc = gc
        self.logger = gc.logger

    def _rawCandidates(self) -> list[tuple[int, int, int, int]]:
        if self._vision is None:
            return []
        try:
            return list(self._vision.getClassificationChannelDetectionCandidates())
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} raw YOLO bbox fetch failed: {exc}")
            return []

    def _carouselPolygon(self) -> Optional[np.ndarray]:
        if self._vision is None:
            return None
        try:
            polygon = self._vision.getCarouselPolygon()
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} carousel polygon fetch failed: {exc}")
            return None
        if polygon is None or len(polygon) < 3:
            return None
        return np.asarray(polygon, dtype=np.int32)

    @staticmethod
    def _bboxCenter(bbox: tuple[int, int, int, int]) -> tuple[float, float]:
        x1, y1, x2, y2 = bbox
        return ((float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0)

    def bboxesOnChannel(self) -> list[tuple[int, int, int, int]]:
        """Raw detections whose center lies inside the carousel zone polygon."""
        candidates = self._rawCandidates()
        if not candidates:
            return []
        polygon = self._carouselPolygon()
        if polygon is None:
            # No polygon configured — we cannot establish membership, so treat
            # nothing as on-channel rather than acting on bounding-rect clutter.
            self.logger.warning(
                f"{LOG_TAG} no carousel polygon available — ignoring "
                f"{len(candidates)} raw candidate(s)"
            )
            return []
        on_channel: list[tuple[int, int, int, int]] = []
        for bbox in candidates:
            cx, cy = self._bboxCenter(bbox)
            if cv2.pointPolygonTest(polygon, (cx, cy), False) >= 0:
                on_channel.append(bbox)
        return on_channel

    def latestRawFrame(self) -> Optional[np.ndarray]:
        if self._vision is None:
            return None
        capture = getattr(self._vision, "_carousel_capture", None)
        if capture is None:
            return None
        frame = capture.latest_frame
        if frame is None:
            return None
        return frame.raw

    def latestRawFrameSample(self) -> Optional[tuple[np.ndarray, float]]:
        if self._vision is None:
            return None
        capture = getattr(self._vision, "_carousel_capture", None)
        if capture is None:
            return None
        frame = capture.latest_frame
        if frame is None or frame.raw is None:
            return None
        return frame.raw, float(frame.timestamp)

    @staticmethod
    def primaryBbox(
        bboxes: list[tuple[int, int, int, int]]
    ) -> Optional[tuple[int, int, int, int]]:
        if not bboxes:
            return None
        return max(
            bboxes,
            key=lambda bbox: max(0, int(bbox[2]) - int(bbox[0]))
            * max(0, int(bbox[3]) - int(bbox[1])),
        )

    @staticmethod
    def cropBbox(
        frame: np.ndarray,
        bbox: tuple[int, int, int, int],
        padding: int = 0,
    ) -> Optional[np.ndarray]:
        frame_h, frame_w = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        crop_x1 = max(0, min(frame_w, int(x1) - padding))
        crop_y1 = max(0, min(frame_h, int(y1) - padding))
        crop_x2 = max(0, min(frame_w, int(x2) + padding))
        crop_y2 = max(0, min(frame_h, int(y2) + padding))
        if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
            return None
        crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]
        if crop.size == 0:
            return None
        return crop.copy()

    def channelCenter(self) -> Optional[tuple[float, float]]:
        if self._vision is None:
            return None
        try:
            geom = self._vision.getFeederTrackGeometry("carousel")
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} geometry fetch failed: {exc}")
            return None
        if geom is None:
            return None
        return (float(geom["center_x"]), float(geom["center_y"]))

    def bboxAngleDeg(
        self, bbox: tuple[int, int, int, int], center: tuple[float, float]
    ) -> float:
        bx, by = self._bboxCenter(bbox)
        return math.degrees(math.atan2(by - center[1], bx - center[0])) % 360.0

    def bboxInExitZone(
        self,
        bbox: tuple[int, int, int, int],
        center: tuple[float, float],
        drop_angle_deg: float,
        drop_tolerance_deg: float,
    ) -> bool:
        angle = self.bboxAngleDeg(bbox, center)
        drop = float(drop_angle_deg) % 360.0
        diff = abs(((angle - drop + 180.0) % 360.0) - 180.0)
        return diff <= float(drop_tolerance_deg)
