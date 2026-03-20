import time
from collections import deque
from typing import Optional, List, Tuple, TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    from global_config import GlobalConfig

PIXEL_THRESH = 4
BLUR_KERNEL = 7
HEAT_GAIN = 12.0
MIN_HOT_PIXELS = 50
TRIGGER_SCORE = 10
BASELINE_FRAMES = 5
CURRENT_FRAMES = 3
CAPTURE_INTERVAL_MS = 50
MIN_CONTOUR_AREA = 70
MIN_HOT_THICKNESS_PIXELS = 12
MAX_CONTOUR_ASPECT_RATIO = 3.0


def _makePlatformMask(corners: List[Tuple[float, float]], shape: Tuple[int, ...]) -> np.ndarray:
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
    def __init__(
        self,
        scale: float = 1.0,
        gc: Optional["GlobalConfig"] = None,
        pixel_thresh: int = PIXEL_THRESH,
        blur_kernel: int = BLUR_KERNEL,
        min_hot_pixels: int = MIN_HOT_PIXELS,
        trigger_score: int = TRIGGER_SCORE,
        min_contour_area: int = MIN_CONTOUR_AREA,
        min_hot_thickness_px: int = MIN_HOT_THICKNESS_PIXELS,
        max_contour_aspect: float = MAX_CONTOUR_ASPECT_RATIO,
        heat_gain: float = HEAT_GAIN,
        current_frames: int = CURRENT_FRAMES,
    ):
        self._gc = gc
        self._pixel_thresh = pixel_thresh
        self._blur_kernel = blur_kernel
        self._min_hot_pixels = min_hot_pixels
        self._trigger_score = trigger_score
        self._min_contour_area = min_contour_area
        self._min_hot_thickness_px = min_hot_thickness_px
        self._max_contour_aspect = max_contour_aspect
        self._heat_gain = heat_gain
        self._current_frames = current_frames
        self._baseline_gray: Optional[np.ndarray] = None
        self._baseline_min: Optional[np.ndarray] = None
        self._baseline_max: Optional[np.ndarray] = None
        self._baseline_mask: Optional[np.ndarray] = None
        self._baseline_corners: Optional[List[Tuple[float, float]]] = None
        self._baseline_timestamp: float = 0.0
        self._gray_ring: deque[np.ndarray] = deque(maxlen=30)
        self._last_ring_time: float = 0.0
        self._scale = scale
        self._full_size: Optional[Tuple[int, int]] = None
        self._cached_result: Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]] = None

    @property
    def has_baseline(self) -> bool:
        return self._baseline_mask is not None and (
            self._baseline_gray is not None or self._baseline_min is not None
        )

    @property
    def baseline_corners(self) -> Optional[List[Tuple[float, float]]]:
        return self._baseline_corners

    def _downscale(self, img: np.ndarray) -> np.ndarray:
        if self._scale >= 1.0:
            return img
        h, w = img.shape[:2]
        self._full_size = (w, h)
        new_w, new_h = int(w * self._scale), int(h * self._scale)
        return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

    def pushFrame(self, gray: np.ndarray) -> None:
        now = time.time()
        if (now - self._last_ring_time) * 1000 >= CAPTURE_INTERVAL_MS:
            self._gray_ring.append(self._downscale(gray))
            self._last_ring_time = now
            self._cached_result = None

    def _getAveraged(self, count: int) -> Optional[np.ndarray]:
        n = min(count, len(self._gray_ring))
        if n == 0:
            return None
        frames = list(self._gray_ring)[-n:]
        return _averageGrays(frames)

    def captureBaseline(self, corners: List[Tuple[float, float]], shape: Tuple[int, ...]) -> bool:
        avg = self._getAveraged(BASELINE_FRAMES)
        if avg is None:
            return False
        if self._scale < 1.0:
            scaled_corners = [(x * self._scale, y * self._scale) for x, y in corners]
            scaled_shape = (int(shape[0] * self._scale), int(shape[1] * self._scale))
            self._full_size = (shape[1], shape[0])
        else:
            scaled_corners = corners
            scaled_shape = shape
        mask = _makePlatformMask(scaled_corners, scaled_shape)
        self._baseline_gray = cv2.bitwise_and(avg, avg, mask=mask)
        self._baseline_min = None
        self._baseline_max = None
        self._baseline_mask = mask
        self._baseline_corners = list(corners)
        self._baseline_timestamp = time.time()
        self._cached_result = None
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
        self._cached_result = None
        return True

    def loadEnvelope(self, baseline_min: np.ndarray, baseline_max: np.ndarray, mask: np.ndarray) -> None:
        if self._scale < 1.0:
            h, w = baseline_min.shape[:2]
            self._full_size = (w, h)
            new_w, new_h = int(w * self._scale), int(h * self._scale)
            baseline_min = cv2.resize(baseline_min, (new_w, new_h), interpolation=cv2.INTER_AREA)
            baseline_max = cv2.resize(baseline_max, (new_w, new_h), interpolation=cv2.INTER_AREA)
            mask = cv2.resize(mask, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
        self._baseline_min = cv2.bitwise_and(baseline_min, baseline_min, mask=mask)
        self._baseline_max = cv2.bitwise_and(baseline_max, baseline_max, mask=mask)
        self._baseline_gray = None
        self._baseline_mask = mask
        self._baseline_corners = None
        self._baseline_timestamp = time.time()
        self._cached_result = None

    def clearBaseline(self) -> None:
        self._baseline_gray = None
        self._baseline_min = None
        self._baseline_max = None
        self._baseline_mask = None
        self._baseline_corners = None
        self._baseline_timestamp = 0.0
        self._gray_ring.clear()
        self._cached_result = None

    def _computeDiffMap(self) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
        if self._cached_result is not None:
            return self._cached_result

        mask = self._baseline_mask
        bl_min = self._baseline_min
        bl_max = self._baseline_max

        if mask is None:
            return None
        avg = self._getAveraged(self._current_frames)
        if avg is None:
            return None

        mask_bool = mask > 0

        if bl_min is not None and bl_max is not None:
            current_masked = cv2.bitwise_and(avg, avg, mask=mask)
            below = np.clip(
                bl_min.astype(np.int16) - current_masked.astype(np.int16),
                0, 255,
            ).astype(np.uint8)
            above = np.clip(
                current_masked.astype(np.int16) - bl_max.astype(np.int16),
                0, 255,
            ).astype(np.uint8)
            diff = np.maximum(below, above)
        elif self._baseline_gray is not None:
            current_masked = cv2.bitwise_and(avg, avg, mask=mask)
            diff = cv2.absdiff(current_masked, self._baseline_gray)
        else:
            return None

        blur_k = self._blur_kernel | 1
        diff = cv2.GaussianBlur(diff, (blur_k, blur_k), 0)

        scaled_thickness = max(1, int(self._min_hot_thickness_px * self._scale))
        scaled_min_area = max(1, int(self._min_contour_area * self._scale * self._scale))

        raw_hot = ((diff > self._pixel_thresh) & mask_bool).astype(np.uint8) * 255
        ek = max(1, scaled_thickness // 2)
        erode_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ek * 2 + 1, ek * 2 + 1))
        eroded = cv2.erode(raw_hot, erode_kernel)
        contours, _ = cv2.findContours(raw_hot, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        hot = np.zeros_like(raw_hot)
        for contour in contours:
            if cv2.contourArea(contour) < scaled_min_area:
                continue
            contour_mask = np.zeros_like(raw_hot)
            cv2.drawContours(contour_mask, [contour], -1, 255, -1)
            if not np.any(eroded & contour_mask):
                continue
            (_, _), (mar_w, mar_h), _ = cv2.minAreaRect(contour)
            mar_short = min(mar_w, mar_h)
            mar_long = max(mar_w, mar_h)
            mar_aspect = mar_long / mar_short if mar_short > 0 else 999.0
            if mar_aspect > self._max_contour_aspect:
                continue
            cv2.drawContours(hot, [contour], -1, 255, -1)

        result = (diff, hot > 0, mask_bool)
        self._cached_result = result
        return result

    def computeDiff(self) -> Tuple[float, int]:
        result = self._computeDiffMap()
        if result is None:
            return 0.0, 0
        diff, hot, _ = result

        hot_count = int(np.count_nonzero(hot))
        score = float(np.mean(diff[hot])) if hot_count >= self._min_hot_pixels else 0.0
        return score, hot_count

    def computeBboxes(self, diff_thresh: float = 0) -> List[Tuple[int, int, int, int]]:
        result = self._computeDiffMap()
        if result is None:
            return []
        diff, hot, _ = result

        if diff_thresh > 0:
            bbox_mask = (hot & (diff > diff_thresh)).astype(np.uint8) * 255
        else:
            bbox_mask = hot.astype(np.uint8) * 255

        contours, _ = cv2.findContours(
            bbox_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        inv = 1.0 / self._scale if self._scale < 1.0 else 1.0
        return [
            (int(x * inv), int(y * inv), int((x + w) * inv), int((y + h) * inv))
            for contour in contours
            for x, y, w, h in [cv2.boundingRect(contour)]
        ]

    def isTriggered(self) -> bool:
        score, _ = self.computeDiff()
        return score >= self._trigger_score

    def annotateFrame(self, annotated: np.ndarray, label: str = "diff", text_y: int = 50) -> np.ndarray:
        result = self._computeDiffMap()
        if result is None:
            return annotated
        diff, hot, mask_bool = result

        hot_count = int(np.count_nonzero(hot))
        score = float(np.mean(diff[hot])) if hot_count >= self._min_hot_pixels else 0.0

        out_h, out_w = annotated.shape[:2]
        diff_h, diff_w = diff.shape[:2]
        if diff_h != out_h or diff_w != out_w:
            diff_up = cv2.resize(diff, (out_w, out_h), interpolation=cv2.INTER_NEAREST)
            hot_up = cv2.resize(hot.astype(np.uint8) * 255, (out_w, out_h), interpolation=cv2.INTER_NEAREST) > 0
            mask_up = cv2.resize(mask_bool.astype(np.uint8) * 255, (out_w, out_h), interpolation=cv2.INTER_NEAREST) > 0
        else:
            diff_up = diff
            hot_up = hot
            mask_up = mask_bool

        display = np.zeros_like(diff_up)
        display[hot_up] = np.clip(
            diff_up[hot_up].astype(np.float32) * self._heat_gain, 0, 255
        ).astype(np.uint8)

        heatmap = cv2.applyColorMap(display, cv2.COLORMAP_JET)

        out = annotated.copy()
        out[mask_up] = (annotated[mask_up] * 0.5).astype(np.uint8)
        show_heat = hot_up & (display > 0)
        out[show_heat] = (
            annotated[show_heat].astype(np.float32) * 0.2
            + heatmap[show_heat].astype(np.float32) * 0.8
        ).clip(0, 255).astype(np.uint8)

        triggered = score >= self._trigger_score
        color = (0, 0, 255) if triggered else (0, 255, 0)
        cv2.putText(out, f"{label}: {score:.1f} px:{hot_count}", (30, text_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

        for x1, y1, x2, y2 in self.computeBboxes():
            cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)

        return out
