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

# HSV mode: OpenCV 8-bit hue has period 180, so the largest possible circular
# distance between two hues is 90. Scale hue diffs by this to land in the same
# 0-255 range as the saturation diff, so a single pixel_thresh applies to both.
HUE_PERIOD = 180
HUE_MAX_DISTANCE = HUE_PERIOD // 2  # 90
HUE_DIFF_SCALE = 255.0 / HUE_MAX_DISTANCE


def _hueCircularDistance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Shortest distance between two OpenCV 8-bit hue arrays (period 180)."""
    d = np.abs(a - b)
    return np.minimum(d, HUE_PERIOD - d)


def _hueArcDistance(h: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Circular distance from hue `h` to the envelope arc [lo, hi]. Zero inside
    the arc, else the shortest circular distance to the nearer endpoint.

    Assumes the stored envelope arc does NOT wrap the 0/180 boundary (true for
    the current magenta background at H~150-170). The `lo <= h <= hi` inside
    test is only valid under that assumption; if the background hue ever moves
    near 0 (red) or 90, switch to a wrap-aware inside test. The distance itself
    is already wrap-aware via _hueCircularDistance."""
    inside = (h >= lo) & (h <= hi)
    d = np.minimum(_hueCircularDistance(h, lo), _hueCircularDistance(h, hi))
    return np.where(inside, 0, d)


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
        channel_mode: str = "gray",
        low_sat_thresh: int = 60,
    ):
        self._gc = gc
        # "gray" = single-channel luminance envelope (carousel + legacy
        # classification). "hs" = 2-channel hue/saturation envelope with a
        # saturation gate on hue (classification HSV pipeline). Frames pushed
        # and envelopes loaded must match this mode's channel count.
        self._channel_mode = channel_mode
        self._low_sat_thresh = low_sat_thresh
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

    def _envelopeDiffHS(
        self, current: np.ndarray, bl_min: np.ndarray, bl_max: np.ndarray
    ) -> np.ndarray:
        """Saturation-gated hue/saturation(/value) envelope diff -> 0-255 map.

        `current`, `bl_min`, `bl_max` are 2-channel (H, S) or 3-channel (H, S, V)
        uint8 arrays. Hue uses circular arc distance (scaled up to 0-255 from its
        0-90 range); saturation and value use a linear out-of-envelope distance.
        A pixel whose saturation is below `low_sat_thresh` has unreliable hue, so
        hue is dropped there (judged on S, and V if present); otherwise the result
        is the max over all available channel diffs. This catches desaturating
        pieces (S), hue-shifted pieces (H), and pieces that block the backlight
        and read darker than the floor (V) -- the last rescues hue/saturation-
        contaminated pieces against the magenta background. The per-pixel V
        envelope is permissive where the floor varies, so it self-gates."""
        h_cur = current[:, :, 0].astype(np.int16)
        s_cur = current[:, :, 1].astype(np.int16)
        h_min = bl_min[:, :, 0].astype(np.int16)
        h_max = bl_max[:, :, 0].astype(np.int16)
        s_min = bl_min[:, :, 1].astype(np.int16)
        s_max = bl_max[:, :, 1].astype(np.int16)

        h_dist = _hueArcDistance(h_cur, h_min, h_max)
        h_diff = np.clip(h_dist * HUE_DIFF_SCALE, 0, 255)

        s_below = np.clip(s_min - s_cur, 0, 255)
        s_above = np.clip(s_cur - s_max, 0, 255)
        s_diff = np.maximum(s_below, s_above)

        # Non-hue diff (always trustworthy regardless of saturation): S, plus V
        # when a value channel is present.
        non_hue = s_diff
        if current.shape[2] >= 3:
            v_cur = current[:, :, 2].astype(np.int16)
            v_min = bl_min[:, :, 2].astype(np.int16)
            v_max = bl_max[:, :, 2].astype(np.int16)
            v_diff = np.maximum(np.clip(v_min - v_cur, 0, 255), np.clip(v_cur - v_max, 0, 255))
            non_hue = np.maximum(non_hue, v_diff)

        low_sat = s_cur < self._low_sat_thresh
        combined = np.where(low_sat, non_hue, np.maximum(h_diff, non_hue))
        return combined.astype(np.uint8)

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

        if avg.shape[:2] != mask.shape[:2]:
            mask = cv2.resize(mask, (avg.shape[1], avg.shape[0]), interpolation=cv2.INTER_NEAREST)
            if bl_min is not None:
                bl_min = cv2.resize(bl_min, (avg.shape[1], avg.shape[0]), interpolation=cv2.INTER_AREA)
            if bl_max is not None:
                bl_max = cv2.resize(bl_max, (avg.shape[1], avg.shape[0]), interpolation=cv2.INTER_AREA)

        mask_bool = mask > 0

        if bl_min is not None and bl_max is not None:
            current_masked = cv2.bitwise_and(avg, avg, mask=mask)
            if self._channel_mode in ("hs", "hsv"):
                diff = self._envelopeDiffHS(current_masked, bl_min, bl_max)
            else:
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
            bl_gray = self._baseline_gray
            if bl_gray.shape[:2] != avg.shape[:2]:
                bl_gray = cv2.resize(bl_gray, (avg.shape[1], avg.shape[0]), interpolation=cv2.INTER_AREA)
            diff = cv2.absdiff(current_masked, bl_gray)
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
