"""Dashboard crop geometry for camera calibration/review frames."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from local_state import get_channel_polygons, get_classification_polygons
from server.detection_config.common import public_aux_scope
from server.services.camera_calibration.common import as_number
from utils.polygon_crop import apply_polygons_crop
from utils.polygon_resolution import saved_polygon_resolution


DASHBOARD_CROP_PADDING_FACTOR = 0.14
DASHBOARD_CROP_MIN_PADDING_PX = 48.0
DASHBOARD_QUAD_PADDING_FACTOR = 0.1

_POLYGON_KEY_TO_CHANNEL_KEY: dict[str, str] = {
    "second_channel": "second",
    "third_channel": "third",
    "classification_channel": "classification_channel",
    "carousel": "carousel",
}


def _dashboard_polygon_resolution(
    saved: dict[str, Any] | None,
    channel_key: str | None = None,
) -> tuple[float, float]:
    """Resolve the capture resolution a polygon was saved at."""
    return saved_polygon_resolution(saved, channel_key=channel_key)


def _dashboard_points(raw: Any) -> list[tuple[float, float]]:
    if not isinstance(raw, (list, tuple)):
        return []
    points: list[tuple[float, float]] = []
    for point in raw:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        x = as_number(point[0])
        y = as_number(point[1])
        if x is None or y is None:
            continue
        points.append((float(x), float(y)))
    return points


def _dashboard_quad_points(raw: Any) -> list[tuple[float, float]]:
    if not isinstance(raw, dict):
        return []
    return _dashboard_points(raw.get("corners"))


def _scale_dashboard_points(
    points: list[tuple[float, float]],
    source_resolution: tuple[float, float],
    frame_w: int,
    frame_h: int,
) -> np.ndarray | None:
    if len(points) < 3:
        return None
    src_w, src_h = source_resolution
    if src_w <= 0 or src_h <= 0 or frame_w <= 0 or frame_h <= 0:
        return None
    scaled = np.array(points, dtype=np.float32)
    scaled[:, 0] *= float(frame_w) / float(src_w)
    scaled[:, 1] *= float(frame_h) / float(src_h)
    return scaled


def _dashboard_padded_bbox(
    polygons: list[np.ndarray],
    frame_w: int,
    frame_h: int,
) -> tuple[int, int, int, int] | None:
    if not polygons:
        return None
    merged = np.concatenate(polygons, axis=0)
    min_x = float(np.min(merged[:, 0]))
    min_y = float(np.min(merged[:, 1]))
    max_x = float(np.max(merged[:, 0]))
    max_y = float(np.max(merged[:, 1]))
    width = max(1.0, max_x - min_x)
    height = max(1.0, max_y - min_y)
    pad_x = max(DASHBOARD_CROP_MIN_PADDING_PX, width * DASHBOARD_CROP_PADDING_FACTOR)
    pad_y = max(DASHBOARD_CROP_MIN_PADDING_PX, height * DASHBOARD_CROP_PADDING_FACTOR)
    x1 = max(0, int(np.floor(min_x - pad_x)))
    y1 = max(0, int(np.floor(min_y - pad_y)))
    x2 = min(frame_w, int(np.ceil(max_x + pad_x)))
    y2 = min(frame_h, int(np.ceil(max_y + pad_y)))
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _dashboard_expand_quad(quad: np.ndarray) -> np.ndarray:
    width_top_vec = quad[1] - quad[0]
    width_bottom_vec = quad[2] - quad[3]
    height_right_vec = quad[2] - quad[1]
    height_left_vec = quad[3] - quad[0]

    avg_width_vec = (width_top_vec + width_bottom_vec) / 2.0
    avg_height_vec = (height_right_vec + height_left_vec) / 2.0
    avg_width_len = float(np.linalg.norm(avg_width_vec))
    avg_height_len = float(np.linalg.norm(avg_height_vec))

    if avg_width_len <= 1e-6 or avg_height_len <= 1e-6:
        return quad.astype(np.float32)

    padding = max(
        DASHBOARD_CROP_MIN_PADDING_PX,
        max(avg_width_len, avg_height_len) * DASHBOARD_QUAD_PADDING_FACTOR,
    )

    u = (avg_width_vec / avg_width_len).astype(np.float32)
    v = (avg_height_vec / avg_height_len).astype(np.float32)

    signs = np.array(
        [
            [-1.0, -1.0],
            [+1.0, -1.0],
            [+1.0, +1.0],
            [-1.0, +1.0],
        ],
        dtype=np.float32,
    )

    expanded = quad.astype(np.float32).copy()
    for index in range(4):
        s_u, s_v = signs[index]
        expanded[index] = expanded[index] + (s_u * padding) * u + (s_v * padding) * v
    return expanded


def _dashboard_quad_size(quad: np.ndarray) -> tuple[int, int]:
    width_top = float(np.linalg.norm(quad[1] - quad[0]))
    width_bottom = float(np.linalg.norm(quad[2] - quad[3]))
    height_right = float(np.linalg.norm(quad[2] - quad[1]))
    height_left = float(np.linalg.norm(quad[3] - quad[0]))
    width = max(1, int(round(max(width_top, width_bottom))))
    height = max(1, int(round(max(height_right, height_left))))
    return (width, height)


def dashboard_crop_spec(role: str, frame_w: int, frame_h: int) -> dict[str, Any] | None:
    if role in {"feeder", "c_channel_2", "c_channel_3", "carousel", "classification_channel"}:
        saved = get_channel_polygons() or {}
        polygons_table = saved.get("polygons") if isinstance(saved.get("polygons"), dict) else {}
        quad_table = saved.get("quad_params") if isinstance(saved.get("quad_params"), dict) else {}
        classification_channel_setup = public_aux_scope() == "classification_channel"
        carousel_polygon_key = "classification_channel" if classification_channel_setup else "carousel"

        if role == "carousel" and not classification_channel_setup:
            carousel_resolution = _dashboard_polygon_resolution(saved, "carousel")
            quad_points = _dashboard_quad_points(quad_table.get("carousel"))
            if len(quad_points) != 4:
                quad_points = _dashboard_points(polygons_table.get(carousel_polygon_key))
            scaled_quad = (
                _scale_dashboard_points(quad_points, carousel_resolution, frame_w, frame_h)
                if len(quad_points) == 4
                else None
            )
            if scaled_quad is not None and len(scaled_quad) == 4:
                expanded_quad = _dashboard_expand_quad(scaled_quad)
                target_w, target_h = _dashboard_quad_size(expanded_quad)
                destination = np.array(
                    [
                        [0, 0],
                        [target_w - 1, 0],
                        [target_w - 1, target_h - 1],
                        [0, target_h - 1],
                    ],
                    dtype=np.float32,
                )
                return {
                    "kind": "rectified",
                    "matrix": cv2.getPerspectiveTransform(
                        expanded_quad.astype(np.float32),
                        destination,
                    ),
                    "size": (target_w, target_h),
                }

        polygon_keys = {
            "feeder": ["second_channel", "third_channel", carousel_polygon_key],
            "c_channel_2": ["second_channel"],
            "c_channel_3": ["third_channel"],
            "carousel": [carousel_polygon_key],
            "classification_channel": ["classification_channel"],
        }.get(role, [])
        scaled_polygons = []
        for key in polygon_keys:
            channel_key = _POLYGON_KEY_TO_CHANNEL_KEY.get(key, key)
            per_channel_resolution = _dashboard_polygon_resolution(saved, channel_key)
            scaled = _scale_dashboard_points(
                _dashboard_points(polygons_table.get(key)),
                per_channel_resolution,
                frame_w,
                frame_h,
            )
            if scaled is not None:
                scaled_polygons.append(scaled)
        if not scaled_polygons:
            return None
        return {"kind": "bbox_masked", "polygons": scaled_polygons}

    if role in {"classification_top", "classification_bottom"}:
        saved = get_classification_polygons() or {}
        polygons_table = saved.get("polygons") if isinstance(saved.get("polygons"), dict) else {}
        quad_table = saved.get("quad_params") if isinstance(saved.get("quad_params"), dict) else {}
        quad_key = "class_top" if role == "classification_top" else "class_bottom"
        polygon_key = "top" if role == "classification_top" else "bottom"
        source_resolution = _dashboard_polygon_resolution(saved, quad_key)
        quad_points = _dashboard_quad_points(quad_table.get(quad_key))
        if len(quad_points) != 4:
            quad_points = _dashboard_points(polygons_table.get(polygon_key))
        scaled_quad = (
            _scale_dashboard_points(quad_points, source_resolution, frame_w, frame_h)
            if len(quad_points) == 4
            else None
        )
        if scaled_quad is not None and len(scaled_quad) == 4:
            expanded_quad = _dashboard_expand_quad(scaled_quad)
            target_w, target_h = _dashboard_quad_size(expanded_quad)
            destination = np.array(
                [
                    [0, 0],
                    [target_w - 1, 0],
                    [target_w - 1, target_h - 1],
                    [0, target_h - 1],
                ],
                dtype=np.float32,
            )
            return {
                "kind": "rectified",
                "matrix": cv2.getPerspectiveTransform(
                    expanded_quad.astype(np.float32),
                    destination,
                ),
                "size": (target_w, target_h),
                "square": True,
            }

        scaled_polygon = _scale_dashboard_points(
            _dashboard_points(polygons_table.get(polygon_key)),
            source_resolution,
            frame_w,
            frame_h,
        )
        bbox = (
            _dashboard_padded_bbox([scaled_polygon], frame_w, frame_h)
            if scaled_polygon is not None
            else None
        )
        return {"kind": "bbox", "bbox": bbox, "square": True} if bbox is not None else None

    return None


def _dashboard_pad_square(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    if height <= 0 or width <= 0 or height == width:
        return frame
    target = max(height, width)
    pad_y = target - height
    pad_x = target - width
    top = pad_y // 2
    bottom = pad_y - top
    left = pad_x // 2
    right = pad_x - left
    return cv2.copyMakeBorder(frame, top, bottom, left, right, cv2.BORDER_REPLICATE)


def apply_dashboard_crop(frame: np.ndarray, spec: dict[str, Any] | None) -> np.ndarray:
    if not spec:
        return frame
    kind = spec.get("kind")
    processed = frame
    if kind == "rectified":
        size = spec.get("size")
        matrix = spec.get("matrix")
        if not isinstance(size, tuple) or matrix is None:
            return frame
        processed = cv2.warpPerspective(
            frame,
            matrix,
            size,
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
    elif kind == "bbox_masked":
        polygons = spec.get("polygons")
        if not isinstance(polygons, list) or not polygons:
            return frame
        poly_tuples = [
            [(int(pt[0]), int(pt[1])) for pt in poly]
            for poly in polygons
        ]
        masked, _ = apply_polygons_crop(frame, poly_tuples)
        processed = masked if masked is not None else frame
    else:
        bbox = spec.get("bbox")
        if not isinstance(bbox, tuple) or len(bbox) != 4:
            return frame
        x1, y1, x2, y2 = [int(value) for value in bbox]
        if x2 <= x1 or y2 <= y1:
            return frame
        processed = frame[y1:y2, x1:x2]

    if spec.get("square"):
        processed = _dashboard_pad_square(processed)
    return processed


__all__ = ["apply_dashboard_crop", "dashboard_crop_spec"]
