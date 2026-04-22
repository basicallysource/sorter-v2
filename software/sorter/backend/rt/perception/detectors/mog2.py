"""MOG2 foreground-subtraction detector — port of mog2_channel_detector.

Runs a single cv2 BackgroundSubtractorMOG2 over the zone mask, returns
contour bounding boxes as Detections. Polar zones are not masked yet — a
TODO stub raises NotImplementedError until the polar wiring lands.
"""

from __future__ import annotations

import time

import cv2
import numpy as np

from rt.contracts.detection import Detection, DetectionBatch, Detector
from rt.contracts.feed import FeedFrame, PolarZone, PolygonZone, RectZone, Zone
from rt.contracts.registry import register_detector


_BOOTSTRAP_FRAMES = 24
_BOOTSTRAP_LEARNING_RATE = 0.2


def _zone_mask(zone: Zone, shape: tuple[int, int]) -> np.ndarray:
    """Render a uint8 [0, 255] mask for the zone at `shape` (h, w)."""
    h, w = shape
    mask = np.zeros((h, w), dtype=np.uint8)
    if isinstance(zone, RectZone):
        x1 = max(0, int(zone.x))
        y1 = max(0, int(zone.y))
        x2 = min(w, int(zone.x + zone.w))
        y2 = min(h, int(zone.y + zone.h))
        if x2 > x1 and y2 > y1:
            mask[y1:y2, x1:x2] = 255
        return mask
    if isinstance(zone, PolygonZone):
        poly = np.asarray(zone.vertices, dtype=np.int32)
        cv2.fillPoly(mask, [poly], 255)
        return mask
    if isinstance(zone, PolarZone):
        # TODO(rt-phase-2b): implement polar annulus mask using zone geometry.
        raise NotImplementedError(
            "PolarZone masking is not wired yet in Mog2Detector"
        )
    raise TypeError(f"Unsupported zone type: {type(zone).__name__}")


def _as_gray(frame: FeedFrame) -> np.ndarray:
    if frame.gray is not None:
        return frame.gray
    raw = frame.raw
    if raw.ndim == 2:
        return raw
    if raw.ndim == 3 and raw.shape[2] == 4:
        raw = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
    return cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY)


@register_detector("mog2")
class Mog2Detector:
    """MOG2 foreground-subtraction detector over a single zone mask."""

    key = "mog2"

    def __init__(
        self,
        history: int = 500,
        var_threshold: int = 16,
        detect_shadows: bool = False,
        min_area_px: int = 100,
        max_area_px: int = 0,
        blur_kernel: int = 5,
        morph_kernel: int = 5,
        learning_rate: float = 0.0,
        fg_threshold: int = 0,
        dilate_iterations: int = 0,
    ) -> None:
        self._history = int(history)
        self._var_threshold = int(var_threshold)
        self._detect_shadows = bool(detect_shadows)
        self._min_area = float(min_area_px)
        self._max_area = int(max_area_px)
        self._blur_k = int(blur_kernel) | 1
        self._morph_k = int(morph_kernel) | 1
        self._learning_rate = float(learning_rate)
        self._fg_threshold = int(fg_threshold)
        self._dilate_iterations = int(dilate_iterations)
        self._mog2 = self._make_subtractor()
        self._mask_cache: tuple[int, int] | None = None
        self._mask: np.ndarray | None = None
        self._bootstrap_left = _BOOTSTRAP_FRAMES

    def _make_subtractor(self) -> cv2.BackgroundSubtractorMOG2:
        return cv2.createBackgroundSubtractorMOG2(
            history=self._history,
            varThreshold=self._var_threshold,
            detectShadows=self._detect_shadows,
        )

    def requires(self) -> frozenset[str]:
        return frozenset({"gray"})

    def _ensure_mask(self, zone: Zone, shape: tuple[int, int]) -> np.ndarray:
        if self._mask is not None and self._mask_cache == shape:
            return self._mask
        self._mask = _zone_mask(zone, shape)
        self._mask_cache = shape
        # Shape changed: reset bg model so it learns the new frame dims clean.
        self._mog2 = self._make_subtractor()
        self._bootstrap_left = _BOOTSTRAP_FRAMES
        return self._mask

    def detect(self, frame: FeedFrame, zone: Zone) -> DetectionBatch:
        t0 = time.monotonic()
        gray = _as_gray(frame)
        h, w = gray.shape[:2]
        mask = self._ensure_mask(zone, (h, w))

        blurred = cv2.GaussianBlur(gray, (self._blur_k, self._blur_k), 0)
        bootstrap = self._bootstrap_left > 0
        lr = _BOOTSTRAP_LEARNING_RATE if bootstrap else self._learning_rate
        fg_raw = self._mog2.apply(blurred, learningRate=lr)
        if bootstrap:
            self._bootstrap_left -= 1
            latency_ms = (time.monotonic() - t0) * 1000.0
            return DetectionBatch(
                feed_id=frame.feed_id,
                frame_seq=frame.frame_seq,
                timestamp=frame.timestamp,
                detections=(),
                algorithm=self.key,
                latency_ms=latency_ms,
            )

        fg = cv2.bitwise_and(fg_raw, mask)
        if self._fg_threshold > 0:
            _, fg = cv2.threshold(fg, self._fg_threshold, 255, cv2.THRESH_BINARY)

        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (self._morph_k, self._morph_k)
        )
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel)
        if self._dilate_iterations > 0:
            fg = cv2.dilate(fg, kernel, iterations=self._dilate_iterations)

        contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        detections: list[Detection] = []
        scale = max(self._min_area * 10.0, 1.0)
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < self._min_area:
                continue
            if self._max_area > 0 and area > self._max_area:
                continue
            x, y, bw, bh = cv2.boundingRect(contour)
            score = min(1.0, area / scale)
            detections.append(
                Detection(
                    bbox_xyxy=(int(x), int(y), int(x + bw), int(y + bh)),
                    score=float(score),
                    class_id=None,
                    mask=None,
                    meta={"area_px": area},
                )
            )

        latency_ms = (time.monotonic() - t0) * 1000.0
        return DetectionBatch(
            feed_id=frame.feed_id,
            frame_seq=frame.frame_seq,
            timestamp=frame.timestamp,
            detections=tuple(detections),
            algorithm=self.key,
            latency_ms=latency_ms,
        )

    def reset(self) -> None:
        self._mog2 = self._make_subtractor()
        self._bootstrap_left = _BOOTSTRAP_FRAMES

    def stop(self) -> None:
        return None


__all__ = ["Mog2Detector"]
