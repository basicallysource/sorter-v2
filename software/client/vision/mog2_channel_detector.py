from typing import Callable, Dict, List

import cv2
import numpy as np

from defs.channel import PolygonChannel, ChannelDetection
from .mog2_diff_configs import Mog2DiffConfig, DEFAULT_MOG2_DIFF_CONFIG

CHANNEL_ID_MAP = {
    "second_channel": 2,
    "third_channel": 3,
}

CHANNEL_COLORS = {
    "second_channel": (255, 200, 0),
    "third_channel": (0, 200, 255),
}


class _ChannelMog2:
    def __init__(self, name: str, polygon_channel: PolygonChannel, mask: np.ndarray, cfg: Mog2DiffConfig):
        self.name = name
        self.polygon_channel = polygon_channel
        self.mask = mask
        self.mog2 = cv2.createBackgroundSubtractorMOG2(
            history=int(cfg.history),
            varThreshold=float(cfg.var_threshold),
            detectShadows=False,
        )
        self.mog2.setNMixtures(int(cfg.n_mixtures))


class Mog2ChannelDetector:
    def __init__(
        self,
        channel_polygons: Dict[str, np.ndarray],
        channel_masks: Dict[str, np.ndarray],
        channel_angles: Dict[str, float],
        is_channel_rotating: Callable[[str], bool],
        cfg: Mog2DiffConfig = DEFAULT_MOG2_DIFF_CONFIG,
    ):
        self._channels: Dict[str, _ChannelMog2] = {}
        self._combined_mask: np.ndarray | None = None
        self._last_fg: np.ndarray | None = None
        self._last_detections: List[ChannelDetection] = []
        self._is_channel_rotating = is_channel_rotating
        self._cfg = cfg

        for key, polygon in channel_polygons.items():
            if len(polygon) < 3:
                continue
            channel_id = CHANNEL_ID_MAP.get(key)
            if channel_id is None:
                continue
            angle_key = key.replace("_channel", "")
            center = tuple(np.mean(polygon, axis=0).tolist())
            pc = PolygonChannel(
                channel_id=channel_id,
                polygon=polygon,
                center=center,
                radius1_angle_image=channel_angles.get(angle_key, 0.0),
                mask=channel_masks[key],
            )
            self._channels[key] = _ChannelMog2(key, pc, channel_masks[key], cfg)

    def detect(self, lab_frame: np.ndarray) -> List[ChannelDetection]:
        blur_k = int(self._cfg.blur_kernel) | 1
        morph_k = int(self._cfg.morph_kernel) | 1
        learning_rate = float(self._cfg.learning_rate)
        min_contour_area = float(self._cfg.min_contour_area)
        max_contour_area = int(self._cfg.max_contour_area)
        fg_threshold = int(self._cfg.fg_threshold)
        dilate_iterations = int(self._cfg.dilate_iterations)
        blurred = cv2.GaussianBlur(lab_frame, (blur_k, blur_k), 0)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morph_k, morph_k))

        detections: List[ChannelDetection] = []
        fg_combined = np.zeros(lab_frame.shape[:2], dtype=np.uint8)

        for ch in self._channels.values():
            lr = learning_rate if self._is_channel_rotating(ch.name) else 0.0
            fg_raw = ch.mog2.apply(blurred, learningRate=lr)
            fg_masked = cv2.bitwise_and(fg_raw, ch.mask)
            if fg_threshold > 0:
                _, fg_masked = cv2.threshold(fg_masked, fg_threshold, 255, cv2.THRESH_BINARY)
            fg_clean = cv2.morphologyEx(fg_masked, cv2.MORPH_OPEN, kernel)
            fg_clean = cv2.morphologyEx(fg_clean, cv2.MORPH_CLOSE, kernel)
            if dilate_iterations > 0:
                fg_clean = cv2.dilate(fg_clean, kernel, iterations=dilate_iterations)
            fg_combined = cv2.bitwise_or(fg_combined, fg_clean)

            contours, _ = cv2.findContours(fg_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < min_contour_area:
                    continue
                if max_contour_area > 0 and area > max_contour_area:
                    continue
                x, y, w, h = cv2.boundingRect(contour)
                detections.append(ChannelDetection(
                    bbox=(x, y, x + w, y + h),
                    channel_id=ch.polygon_channel.channel_id,
                    channel=ch.polygon_channel,
                ))

        self._last_fg = fg_combined
        self._last_detections = detections
        return detections

    def annotateFrame(self, frame: np.ndarray) -> np.ndarray:
        out = frame.copy()

        if self._combined_mask is None and self._channels:
            first = next(iter(self._channels.values()))
            self._combined_mask = np.zeros(first.mask.shape[:2], dtype=np.uint8)
            for ch in self._channels.values():
                self._combined_mask = cv2.bitwise_or(self._combined_mask, ch.mask)

        if self._combined_mask is not None:
            mask_bool = self._combined_mask > 0
            out[mask_bool] = (frame[mask_bool] * 0.5).astype(np.uint8)

        if self._last_fg is not None and self._combined_mask is not None:
            fg_bool = self._last_fg > 0
            mask_bool = self._combined_mask > 0
            hot = fg_bool & mask_bool

            display = np.zeros(self._last_fg.shape[:2], dtype=np.uint8)
            display[hot] = np.clip(
                self._last_fg[hot].astype(np.float32) * float(self._cfg.heat_gain), 0, 255
            ).astype(np.uint8)
            heatmap = cv2.applyColorMap(display, cv2.COLORMAP_JET)
            show = hot & (display > 0)
            out[show] = (
                frame[show].astype(np.float32) * 0.2
                + heatmap[show].astype(np.float32) * 0.8
            ).clip(0, 255).astype(np.uint8)

            hot_count = int(np.count_nonzero(hot))
            color = (0, 0, 255) if hot_count > 0 else (0, 255, 0)
            label = f"feeder fg_px: {hot_count}"
            cv2.putText(out, label, (30, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

        for det in self._last_detections:
            x1, y1, x2, y2 = det.bbox
            cv2.rectangle(out, (x1, y1), (x2, y2), (0, 255, 0), 2)

        for ch in self._channels.values():
            ch_color = CHANNEL_COLORS.get(ch.name, (200, 200, 200))
            cv2.polylines(out, [ch.polygon_channel.polygon], True, ch_color, 2)

        return out
