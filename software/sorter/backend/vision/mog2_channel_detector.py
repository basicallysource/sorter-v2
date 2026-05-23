import os
from typing import Callable, Dict, List

import cv2
import numpy as np

from defs.channel import PolygonChannel, ChannelDetection
from .mog2_diff_configs import Mog2DiffConfig, DEFAULT_MOG2_DIFF_CONFIG

# Wider input frames get downscaled to this width before MOG2 runs. The
# masks/polygons rebuild at the smaller size automatically via _ensure_shape;
# detection bboxes are scaled back to the original frame's coord space before
# being returned so downstream consumers (overlays, tracker) keep using
# camera-frame coordinates. Sized for the carousel — at 4K (3840w) this is a
# ~28× pixel reduction; 720p inputs are untouched. 0 disables.
MOG2_MAX_INPUT_WIDTH = int(os.environ.get("SORTER_MOG2_MAX_INPUT_WIDTH", "720"))

CHANNEL_ID_MAP = {
    "second_channel": 2,
    "third_channel": 3,
    "classification_channel": 4,
}

CHANNEL_COLORS = {
    "second_channel": (255, 200, 0),
    "third_channel": (0, 200, 255),
    "classification_channel": (40, 160, 255),
}

BOOTSTRAP_FRAMES = 24
BOOTSTRAP_LEARNING_RATE = 0.2


class _ChannelMog2:
    def __init__(self, name: str, polygon_channel: PolygonChannel, mask: np.ndarray, cfg: Mog2DiffConfig):
        self.name = name
        self._channel_id = polygon_channel.channel_id
        self._radius1_angle_image = polygon_channel.radius1_angle_image
        self._dropzone_sections = set(polygon_channel.dropzone_sections)
        self._exit_sections = set(polygon_channel.exit_sections)
        self._source_shape = mask.shape[:2]
        self._source_polygon = polygon_channel.polygon.astype(np.float64).copy()
        self._source_inner_polygon = (
            polygon_channel.inner_polygon.astype(np.float64).copy()
            if polygon_channel.inner_polygon is not None
            else None
        )
        self.polygon_channel = polygon_channel
        self.mask = mask
        self._cfg = cfg
        self._current_shape = mask.shape[:2]
        self._bootstrap_frames_remaining = BOOTSTRAP_FRAMES
        self.mog2 = self._make_subtractor()

    def _make_subtractor(self):
        subtractor = cv2.createBackgroundSubtractorMOG2(
            history=int(self._cfg.history),
            varThreshold=float(self._cfg.var_threshold),
            detectShadows=False,
        )
        subtractor.setNMixtures(int(self._cfg.n_mixtures))
        return subtractor

    def ensure_shape(self, shape: tuple[int, int]) -> bool:
        if shape == self._current_shape:
            return False

        src_h, src_w = self._source_shape
        dst_h, dst_w = shape
        scale_x = dst_w / max(src_w, 1)
        scale_y = dst_h / max(src_h, 1)

        polygon = self._source_polygon.copy()
        polygon[:, 0] *= scale_x
        polygon[:, 1] *= scale_y
        polygon_i32 = np.round(polygon).astype(np.int32)

        inner_i32 = None
        if self._source_inner_polygon is not None:
            inner = self._source_inner_polygon.copy()
            inner[:, 0] *= scale_x
            inner[:, 1] *= scale_y
            inner_i32 = np.round(inner).astype(np.int32)

        mask = np.zeros((dst_h, dst_w), dtype=np.uint8)
        cv2.fillPoly(mask, [polygon_i32], 255)
        if inner_i32 is not None and len(inner_i32) >= 3:
            cv2.fillPoly(mask, [inner_i32], 0)

        center = tuple(np.mean(polygon_i32, axis=0).tolist())
        self.mask = mask
        self.polygon_channel = PolygonChannel(
            channel_id=self._channel_id,
            polygon=polygon_i32,
            center=center,
            radius1_angle_image=self._radius1_angle_image,
            mask=mask,
            dropzone_sections=set(self._dropzone_sections),
            exit_sections=set(self._exit_sections),
            inner_polygon=inner_i32,
        )
        self._current_shape = shape
        self._bootstrap_frames_remaining = BOOTSTRAP_FRAMES
        self.mog2 = self._make_subtractor()
        return True

    def in_bootstrap(self) -> bool:
        return self._bootstrap_frames_remaining > 0

    def mark_bootstrap_frame(self) -> None:
        if self._bootstrap_frames_remaining > 0:
            self._bootstrap_frames_remaining -= 1


class Mog2ChannelDetector:
    def __init__(
        self,
        channel_polygons: Dict[str, np.ndarray],
        channel_masks: Dict[str, np.ndarray],
        channel_angles: Dict[str, float],
        channel_inner_polygons: Dict[str, np.ndarray] | None,
        channel_zone_sections: Dict[str, Dict[str, set[int]]] | None,
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
            angle_key = (
                "second"
                if key == "second_channel"
                else "third"
                    if key == "third_channel"
                    else "classification_channel"
            )
            center = tuple(np.mean(polygon, axis=0).tolist())
            pc = PolygonChannel(
                channel_id=channel_id,
                polygon=polygon,
                center=center,
                radius1_angle_image=channel_angles.get(angle_key, 0.0),
                mask=channel_masks[key],
                dropzone_sections=set((channel_zone_sections or {}).get(angle_key, {}).get("drop", set())),
                exit_sections=set((channel_zone_sections or {}).get(angle_key, {}).get("exit", set())),
                inner_polygon=(channel_inner_polygons or {}).get(key),
            )
            self._channels[key] = _ChannelMog2(key, pc, channel_masks[key], cfg)

    def _ensure_shape(self, shape: tuple[int, int]) -> None:
        changed = False
        for ch in self._channels.values():
            changed = ch.ensure_shape(shape) or changed
        if changed:
            self._combined_mask = None
            self._last_fg = None
            self._last_detections = []

    def _mog2InputFrame(self, frame: np.ndarray) -> np.ndarray:
        mode = str(self._cfg.color_mode).lower()
        if frame.ndim == 2:
            if mode == "gray":
                return frame
            if mode == "lab":
                return cv2.cvtColor(cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR), cv2.COLOR_BGR2LAB)
        if frame.ndim == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        if mode == "lab":
            return cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        if mode == "gray":
            return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        raise ValueError(f"Invalid mog2 color_mode: {self._cfg.color_mode}")

    def detect(self, frame: np.ndarray) -> List[ChannelDetection]:
        mog2_frame = self._mog2InputFrame(frame)
        in_h, in_w = mog2_frame.shape[:2]
        bbox_scale = 1.0
        if MOG2_MAX_INPUT_WIDTH > 0 and in_w > MOG2_MAX_INPUT_WIDTH:
            new_w = MOG2_MAX_INPUT_WIDTH
            new_h = int(round(in_h * new_w / in_w))
            mog2_frame = cv2.resize(mog2_frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
            bbox_scale = in_w / float(new_w)
        self._ensure_shape(mog2_frame.shape[:2])
        blur_k = int(self._cfg.blur_kernel) | 1
        morph_k = int(self._cfg.morph_kernel) | 1
        learning_rate = float(self._cfg.learning_rate)
        min_contour_area = float(self._cfg.min_contour_area)
        max_contour_area = int(self._cfg.max_contour_area)
        fg_threshold = int(self._cfg.fg_threshold)
        dilate_iterations = int(self._cfg.dilate_iterations)
        blurred = cv2.GaussianBlur(mog2_frame, (blur_k, blur_k), 0)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morph_k, morph_k))

        detections: List[ChannelDetection] = []
        fg_combined = np.zeros(mog2_frame.shape[:2], dtype=np.uint8)

        for ch in self._channels.values():
            bootstrap = ch.in_bootstrap()
            lr = BOOTSTRAP_LEARNING_RATE if bootstrap else (learning_rate if self._is_channel_rotating(ch.name) else 0.0)
            fg_raw = ch.mog2.apply(blurred, learningRate=lr)
            if bootstrap:
                ch.mark_bootstrap_frame()
                continue
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
                if bbox_scale != 1.0:
                    x = int(round(x * bbox_scale))
                    y = int(round(y * bbox_scale))
                    w = int(round(w * bbox_scale))
                    h = int(round(h * bbox_scale))
                detections.append(ChannelDetection(
                    bbox=(x, y, x + w, y + h),
                    channel_id=ch.polygon_channel.channel_id,
                    channel=ch.polygon_channel,
                ))

        self._last_fg = fg_combined
        self._last_detections = detections
        return detections

    def annotateFrame(self, frame: np.ndarray) -> np.ndarray:
        # NOTE: do not call _ensure_shape here. detect() may have downscaled
        # the frame to MOG2_MAX_INPUT_WIDTH, leaving masks/last_fg at the
        # smaller shape; the annotate frame comes from the full camera feed.
        # Upsampling cached state for the draw avoids resetting the MOG2
        # model on every overlay call.
        out = frame.copy()
        h, w = frame.shape[:2]

        if self._channels:
            first = next(iter(self._channels.values()))
            expected_shape = first.mask.shape[:2]
            if self._combined_mask is None or self._combined_mask.shape[:2] != expected_shape:
                self._combined_mask = np.zeros(expected_shape, dtype=np.uint8)
                for ch in self._channels.values():
                    self._combined_mask = cv2.bitwise_or(self._combined_mask, ch.mask)

        combined_mask = self._combined_mask
        last_fg = self._last_fg
        if combined_mask is not None and combined_mask.shape[:2] != (h, w):
            combined_mask = cv2.resize(combined_mask, (w, h), interpolation=cv2.INTER_NEAREST)
        if last_fg is not None and last_fg.shape[:2] != (h, w):
            last_fg = cv2.resize(last_fg, (w, h), interpolation=cv2.INTER_NEAREST)

        if combined_mask is not None:
            mask_bool = combined_mask > 0
            out[mask_bool] = (frame[mask_bool] * 0.5).astype(np.uint8)

        if last_fg is not None and combined_mask is not None:
            fg_bool = last_fg > 0
            mask_bool = combined_mask > 0
            hot = fg_bool & mask_bool

            display = np.zeros(last_fg.shape[:2], dtype=np.uint8)
            display[hot] = np.clip(
                last_fg[hot].astype(np.float32) * float(self._cfg.heat_gain), 0, 255
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

        if self._channels:
            first = next(iter(self._channels.values()))
            mh, mw = first.mask.shape[:2]
            poly_sx = w / float(mw) if mw else 1.0
            poly_sy = h / float(mh) if mh else 1.0
        else:
            poly_sx = poly_sy = 1.0
        for ch in self._channels.values():
            ch_color = CHANNEL_COLORS.get(ch.name, (200, 200, 200))
            poly = ch.polygon_channel.polygon
            if poly_sx != 1.0 or poly_sy != 1.0:
                poly = np.round(poly.astype(np.float32) * np.array([poly_sx, poly_sy])).astype(np.int32)
            cv2.polylines(out, [poly], True, ch_color, 2)
            if ch.polygon_channel.inner_polygon is not None and len(ch.polygon_channel.inner_polygon) >= 3:
                inner = ch.polygon_channel.inner_polygon
                if poly_sx != 1.0 or poly_sy != 1.0:
                    inner = np.round(inner.astype(np.float32) * np.array([poly_sx, poly_sy])).astype(np.int32)
                cv2.polylines(out, [inner], True, ch_color, 2)

        return out

    def primaryChannel(self) -> PolygonChannel | None:
        first = next(iter(self._channels.values()), None)
        return first.polygon_channel if first is not None else None
