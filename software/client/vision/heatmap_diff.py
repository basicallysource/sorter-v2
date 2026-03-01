import time
from collections import deque
from typing import Optional, List, Tuple

import cv2
import numpy as np

PIXEL_THRESH = 8
BLUR_KERNEL = 5
HEAT_GAIN = 12.0
MIN_HOT_PIXELS = 50
TRIGGER_SCORE = 17
BASELINE_FRAMES = 5
CURRENT_FRAMES = 3
CAPTURE_INTERVAL_MS = 50
MIN_CONTOUR_AREA = 100
MIN_HOT_THICKNESS_PIXELS = 12


def _makePlatformMask(corners: List[Tuple[float, float]], shape) -> np.ndarray:
    mask = np.zeros(shape[:2], dtype=np.uint8)
    pts = np.array([[int(x), int(y)] for x, y in corners], dtype=np.int32)
    cv2.fillPoly(mask, [pts], 255)
    return mask


def _averageGrays(frames: List[np.ndarray]) -> np.ndarray:
    acc = frames[0].astype(np.float32)
    for f in frames[1:]:
        acc += f.astype(np.float32)
    return (acc / len(frames)).astype(np.uint8)


class HeatmapDiff:
    def __init__(self):
        self._baseline_gray: Optional[np.ndarray] = None
        self._baseline_min: Optional[np.ndarray] = None
        self._baseline_max: Optional[np.ndarray] = None
        self._baseline_mask: Optional[np.ndarray] = None
        self._baseline_corners: Optional[List[Tuple[float, float]]] = None
        self._baseline_timestamp: float = 0.0
        self._gray_ring: deque = deque(maxlen=30)
        self._last_ring_time: float = 0.0

    @property
    def has_baseline(self) -> bool:
        return self._baseline_mask is not None and (
            self._baseline_gray is not None or self._baseline_min is not None
        )

    @property
    def baseline_corners(self) -> Optional[List[Tuple[float, float]]]:
        return self._baseline_corners

    def pushFrame(self, gray: np.ndarray) -> None:
        now = time.time()
        if (now - self._last_ring_time) * 1000 >= CAPTURE_INTERVAL_MS:
            self._gray_ring.append(gray)
            self._last_ring_time = now

    def _getAveraged(self, count: int) -> Optional[np.ndarray]:
        n = min(count, len(self._gray_ring))
        if n == 0:
            return None
        frames = list(self._gray_ring)[-n:]
        return _averageGrays(frames)

    def captureBaseline(self, corners: List[Tuple[float, float]], shape) -> bool:
        avg = self._getAveraged(BASELINE_FRAMES)
        if avg is None:
            return False
        mask = _makePlatformMask(corners, shape)
        self._baseline_gray = cv2.bitwise_and(avg, avg, mask=mask)
        self._baseline_min = None
        self._baseline_max = None
        self._baseline_mask = mask
        self._baseline_corners = list(corners)
        self._baseline_timestamp = time.time()
        return True

    def setBaselineEnvelope(self, frames: List[np.ndarray], mask: np.ndarray) -> bool:
        if not frames:
            return False
        stack = np.stack(frames, axis=0)
        self._baseline_min = cv2.bitwise_and(
            np.min(stack, axis=0).astype(np.uint8),
            np.min(stack, axis=0).astype(np.uint8),
            mask=mask,
        )
        self._baseline_max = cv2.bitwise_and(
            np.max(stack, axis=0).astype(np.uint8),
            np.max(stack, axis=0).astype(np.uint8),
            mask=mask,
        )
        self._baseline_gray = None
        self._baseline_mask = mask
        self._baseline_corners = None
        self._baseline_timestamp = time.time()
        return True

    def loadEnvelope(self, baseline_min: np.ndarray, baseline_max: np.ndarray, mask: np.ndarray) -> None:
        self._baseline_min = cv2.bitwise_and(baseline_min, baseline_min, mask=mask)
        self._baseline_max = cv2.bitwise_and(baseline_max, baseline_max, mask=mask)
        self._baseline_gray = None
        self._baseline_mask = mask
        self._baseline_corners = None
        self._baseline_timestamp = time.time()

    def clearBaseline(self) -> None:
        self._baseline_gray = None
        self._baseline_min = None
        self._baseline_max = None
        self._baseline_mask = None
        self._baseline_corners = None
        self._baseline_timestamp = 0.0
        self._gray_ring.clear()

    def _computeDiffMap(self) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
        if self._baseline_mask is None:
            return None
        avg = self._getAveraged(CURRENT_FRAMES)
        if avg is None:
            return None

        mask_bool = self._baseline_mask > 0

        if self._baseline_min is not None and self._baseline_max is not None:
            current_masked = cv2.bitwise_and(avg, avg, mask=self._baseline_mask)
            below = np.clip(
                self._baseline_min.astype(np.int16) - current_masked.astype(np.int16),
                0, 255,
            ).astype(np.uint8)
            above = np.clip(
                current_masked.astype(np.int16) - self._baseline_max.astype(np.int16),
                0, 255,
            ).astype(np.uint8)
            diff = np.maximum(below, above)
        elif self._baseline_gray is not None:
            current_masked = cv2.bitwise_and(avg, avg, mask=self._baseline_mask)
            diff = cv2.absdiff(current_masked, self._baseline_gray)
        else:
            return None

        blur_k = BLUR_KERNEL | 1
        diff = cv2.GaussianBlur(diff, (blur_k, blur_k), 0)

        # build hot mask, filtering out thin slivers (including curved arcs)
        # erosion removes anything thinner than MIN_HOT_THICKNESS_PIXELS regardless of shape
        raw_hot = ((diff > PIXEL_THRESH) & mask_bool).astype(np.uint8) * 255
        ek = max(1, MIN_HOT_THICKNESS_PIXELS // 2)
        erode_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ek * 2 + 1, ek * 2 + 1))
        eroded = cv2.erode(raw_hot, erode_kernel)
        contours, _ = cv2.findContours(raw_hot, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        hot = np.zeros_like(raw_hot)
        for contour in contours:
            if cv2.contourArea(contour) < MIN_CONTOUR_AREA:
                continue
            contour_mask = np.zeros_like(raw_hot)
            cv2.drawContours(contour_mask, [contour], -1, 255, -1)
            if not np.any(eroded & contour_mask):
                continue
            cv2.drawContours(hot, [contour], -1, 255, -1)

        return diff, hot > 0, mask_bool

    def computeDiff(self) -> Tuple[float, int]:
        result = self._computeDiffMap()
        if result is None:
            return 0.0, 0
        diff, hot, mask_bool = result

        hot_count = int(np.count_nonzero(hot))
        score = float(np.mean(diff[hot])) if hot_count >= MIN_HOT_PIXELS else 0.0
        return score, hot_count

    def computeBboxes(self) -> List[Tuple[int, int, int, int]]:
        result = self._computeDiffMap()
        if result is None:
            return []
        _, hot, _ = result

        contours, _ = cv2.findContours(
            hot.astype(np.uint8) * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        return [
            (x, y, x + w, y + h)
            for contour in contours
            for x, y, w, h in [cv2.boundingRect(contour)]
        ]

    def isTriggered(self) -> bool:
        score, _ = self.computeDiff()
        return score >= TRIGGER_SCORE

    def annotateFrame(self, annotated: np.ndarray, label: str = "diff", text_y: int = 50) -> np.ndarray:
        result = self._computeDiffMap()
        if result is None:
            return annotated
        diff, hot, mask_bool = result

        hot_count = int(np.count_nonzero(hot))
        score = float(np.mean(diff[hot])) if hot_count >= MIN_HOT_PIXELS else 0.0

        display = np.zeros_like(diff)
        display[hot] = np.clip(
            diff[hot].astype(np.float32) * HEAT_GAIN, 0, 255
        ).astype(np.uint8)

        heatmap = cv2.applyColorMap(display, cv2.COLORMAP_JET)

        out = annotated.copy()
        out[mask_bool] = (annotated[mask_bool] * 0.5).astype(np.uint8)
        show_heat = hot & (display > 0)
        out[show_heat] = (
            annotated[show_heat].astype(np.float32) * 0.2
            + heatmap[show_heat].astype(np.float32) * 0.8
        ).clip(0, 255).astype(np.uint8)

        triggered = score >= TRIGGER_SCORE
        color = (0, 0, 255) if triggered else (0, 255, 0)
        cv2.putText(out, f"{label}: {score:.1f} px:{hot_count}", (30, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

        for x1, y1, x2, y2 in self.computeBboxes():
            cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)

        return out
