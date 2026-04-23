from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import cv2
import numpy as np

from blob_manager import getChannelPolygons
from defs.events import CameraName
from rt.contracts.feed import PolarZone, PolygonZone, RectZone, Zone
from server import shared_state
from vision.overlays.scaling import overlay_scale_for_frame, scaled_px
from vision.overlays.tracker import (
    COLOR_ACTIVE,
    COLOR_LABEL_BG,
    COLOR_UNCONFIRMED,
    format_track_label,
)


_CAMERA_TO_RT_FEED_ID: dict[str, str] = {
    CameraName.c_channel_2.value: "c2_feed",
    CameraName.c_channel_3.value: "c3_feed",
    CameraName.carousel.value: "c4_feed",
    CameraName.classification_channel.value: "c4_feed",
}

_ZONE_FILL_COLOR = (120, 220, 255)
_ZONE_LINE_COLOR = (90, 220, 255)
_DROP_FILL_COLOR = (94, 197, 34)
_WAIT_FILL_COLOR = (11, 158, 245)
_EXIT_FILL_COLOR = (68, 68, 239)
_CHANNEL_LINE_COLORS: dict[str, tuple[int, int, int]] = {
    "c_channel_2": (0, 200, 255),
    "c_channel_3": (255, 200, 0),
    "classification_channel": (42, 138, 255),
    "carousel": (42, 138, 255),
}
_ROLE_TO_CHANNEL_KEY: dict[str, str] = {
    "c_channel_2": "second",
    "c_channel_3": "third",
    "classification_channel": "classification_channel",
    "carousel": "classification_channel",
}


class FrameOverlay(Protocol):
    category: str

    def annotate(self, frame: np.ndarray) -> np.ndarray: ...


class CameraAnnotationProvider(Protocol):
    def overlays_for_role(self, role: str) -> Sequence[FrameOverlay]: ...


def _annotation_snapshot_for_feed(feed_id: str) -> Any | None:
    handle = getattr(shared_state, "rt_handle", None)
    if handle is None:
        return None
    snapshot_for_feed = getattr(handle, "annotation_snapshot", None)
    if not callable(snapshot_for_feed):
        return None
    try:
        return snapshot_for_feed(feed_id)
    except Exception:
        return None


def _channel_polygons_snapshot() -> dict[str, Any]:
    data = getChannelPolygons()
    return data if isinstance(data, dict) else {}


def _arc_config_for_role(role: str) -> dict[str, Any] | None:
    channel_key = _ROLE_TO_CHANNEL_KEY.get(role)
    if channel_key is None:
        return None
    data = _channel_polygons_snapshot()
    arc_params = data.get("arc_params")
    if not isinstance(arc_params, dict):
        return None
    raw = arc_params.get(channel_key)
    return raw if isinstance(raw, dict) else None


def _zone_polygons(zone: Zone | None) -> list[np.ndarray]:
    if isinstance(zone, RectZone):
        return [
            np.array(
                [
                    [int(zone.x), int(zone.y)],
                    [int(zone.x + zone.w), int(zone.y)],
                    [int(zone.x + zone.w), int(zone.y + zone.h)],
                    [int(zone.x), int(zone.y + zone.h)],
                ],
                dtype=np.int32,
            )
        ]
    if isinstance(zone, PolygonZone):
        if len(zone.vertices) < 3:
            return []
        return [np.array(zone.vertices, dtype=np.int32)]
    if isinstance(zone, PolarZone):
        center_x = float(zone.center_xy[0])
        center_y = float(zone.center_xy[1])
        start_deg = np.degrees(float(zone.theta_start_rad))
        end_deg = np.degrees(float(zone.theta_end_rad))
        span_deg = (end_deg - start_deg) % 360.0
        if span_deg <= 0.0:
            span_deg = 360.0
        segments = max(24, int(round(span_deg / 8.0)))
        outer: list[list[int]] = []
        inner: list[list[int]] = []
        for step in range(segments + 1):
            angle_deg = start_deg + (span_deg * step / segments)
            angle_rad = np.radians(angle_deg)
            outer.append(
                [
                    int(round(center_x + np.cos(angle_rad) * float(zone.r_outer))),
                    int(round(center_y + np.sin(angle_rad) * float(zone.r_outer))),
                ]
            )
        for step in range(segments, -1, -1):
            angle_deg = start_deg + (span_deg * step / segments)
            angle_rad = np.radians(angle_deg)
            inner.append(
                [
                    int(round(center_x + np.cos(angle_rad) * float(zone.r_inner))),
                    int(round(center_y + np.sin(angle_rad) * float(zone.r_inner))),
                ]
            )
        return [np.array(outer + inner, dtype=np.int32)]
    return []


class RuntimeZoneOverlay:
    category = "regions"

    def __init__(self, get_zone: Callable[[], Zone | None]) -> None:
        self._get_zone = get_zone

    def annotate(self, frame: np.ndarray) -> np.ndarray:
        polygons = _zone_polygons(self._get_zone())
        if not polygons:
            return frame
        annotated = frame.copy()
        overlay = annotated.copy()
        scale = overlay_scale_for_frame(frame)
        thickness = scaled_px(2, scale)
        cv2.fillPoly(overlay, polygons, _ZONE_FILL_COLOR)
        cv2.addWeighted(overlay, 0.14, annotated, 0.86, 0.0, annotated)
        cv2.polylines(
            annotated,
            polygons,
            isClosed=True,
            color=_ZONE_LINE_COLOR,
            thickness=thickness,
            lineType=cv2.LINE_AA,
        )
        return annotated


def _coerce_pair(raw: Any) -> tuple[float, float] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None
    try:
        return float(raw[0]), float(raw[1])
    except Exception:
        return None


def _coerce_angle_range(raw: Any) -> tuple[float, float] | None:
    if not isinstance(raw, dict):
        return None
    try:
        return float(raw["start_angle"]), float(raw["end_angle"])
    except Exception:
        return None


def _scale_point(
    point: tuple[float, float],
    *,
    sx: float,
    sy: float,
) -> tuple[int, int]:
    return int(round(point[0] * sx)), int(round(point[1] * sy))


def _zone_polygon(
    center: tuple[float, float],
    inner_radius: float,
    outer_radius: float,
    start_deg: float,
    end_deg: float,
    *,
    sx: float,
    sy: float,
    segments: int = 64,
) -> np.ndarray:
    span_deg = (float(end_deg) - float(start_deg)) % 360.0
    if span_deg <= 0.0:
        span_deg = 360.0
    outer: list[tuple[int, int]] = []
    inner: list[tuple[int, int]] = []
    for step in range(segments + 1):
        angle_deg = float(start_deg) + (span_deg * step / segments)
        angle_rad = np.radians(angle_deg)
        outer.append(
            _scale_point(
                (
                    center[0] + np.cos(angle_rad) * float(outer_radius),
                    center[1] + np.sin(angle_rad) * float(outer_radius),
                ),
                sx=sx,
                sy=sy,
            )
        )
    for step in range(segments, -1, -1):
        angle_deg = float(start_deg) + (span_deg * step / segments)
        angle_rad = np.radians(angle_deg)
        inner.append(
            _scale_point(
                (
                    center[0] + np.cos(angle_rad) * float(inner_radius),
                    center[1] + np.sin(angle_rad) * float(inner_radius),
                ),
                sx=sx,
                sy=sy,
            )
        )
    return np.array(list(outer) + list(inner), dtype=np.int32)


def _circle_polyline(
    center: tuple[float, float],
    radius: float,
    *,
    sx: float,
    sy: float,
    segments: int = 96,
) -> np.ndarray:
    points: list[tuple[int, int]] = []
    for step in range(segments):
        angle_rad = np.radians((360.0 * step) / segments)
        points.append(
            _scale_point(
                (
                    center[0] + np.cos(angle_rad) * float(radius),
                    center[1] + np.sin(angle_rad) * float(radius),
                ),
                sx=sx,
                sy=sy,
            )
        )
    return np.array(points, dtype=np.int32)


class ChannelArcOverlay:
    category = "regions"

    def __init__(self, role: str, get_config: Callable[[], dict[str, Any] | None]) -> None:
        self._role = role
        self._get_config = get_config

    def annotate(self, frame: np.ndarray) -> np.ndarray:
        config = self._get_config()
        if not isinstance(config, dict):
            return frame
        center = _coerce_pair(config.get("center"))
        if center is None:
            return frame
        try:
            inner_radius = float(config["inner_radius"])
            outer_radius = float(config["outer_radius"])
        except Exception:
            return frame
        if outer_radius <= inner_radius:
            return frame

        resolution = _coerce_pair(config.get("resolution")) or (
            float(frame.shape[1]),
            float(frame.shape[0]),
        )
        sx = float(frame.shape[1]) / max(1.0, float(resolution[0]))
        sy = float(frame.shape[0]) / max(1.0, float(resolution[1]))

        line_color = _CHANNEL_LINE_COLORS.get(self._role, _ZONE_LINE_COLOR)
        annotated = frame.copy()
        overlay = annotated.copy()

        for raw_zone, color, alpha in (
            (config.get("drop_zone"), _DROP_FILL_COLOR, 0.22),
            (config.get("wait_zone"), _WAIT_FILL_COLOR, 0.22),
            (config.get("exit_zone"), _EXIT_FILL_COLOR, 0.22),
        ):
            angles = _coerce_angle_range(raw_zone)
            if angles is None:
                continue
            polygon = _zone_polygon(
                center,
                inner_radius,
                outer_radius,
                angles[0],
                angles[1],
                sx=sx,
                sy=sy,
            )
            cv2.fillPoly(overlay, [polygon], color)
            cv2.addWeighted(overlay, alpha, annotated, 1.0 - alpha, 0.0, annotated)
            overlay[:] = annotated

        scale = overlay_scale_for_frame(frame)
        thickness = scaled_px(2, scale)
        outer = _circle_polyline(center, outer_radius, sx=sx, sy=sy)
        inner = _circle_polyline(center, inner_radius, sx=sx, sy=sy)
        cv2.polylines(annotated, [outer], True, line_color, thickness, cv2.LINE_AA)
        cv2.polylines(annotated, [inner], True, line_color, thickness, cv2.LINE_AA)
        return annotated


class RuntimeTrackOverlay:
    category = "detections"

    def __init__(self, get_tracks: Callable[[], list[Any]]) -> None:
        self._get_tracks = get_tracks

    def annotate(self, frame: np.ndarray) -> np.ndarray:
        tracks = self._get_tracks() or []
        if not tracks:
            return frame
        annotated = frame.copy()
        scale = overlay_scale_for_frame(frame)
        box_thickness = scaled_px(2, scale)
        font_scale = 0.55 * scale
        font_thickness = scaled_px(1, scale)
        pad = scaled_px(3, scale)
        margin = scaled_px(2, scale)

        for track in tracks:
            bbox = getattr(track, "bbox_xyxy", None)
            if not isinstance(bbox, tuple) or len(bbox) != 4:
                continue
            x1, y1, x2, y2 = [int(round(float(v))) for v in bbox]
            if x2 <= x1 or y2 <= y1:
                continue

            confirmed = bool(getattr(track, "confirmed_real", False))
            color = COLOR_ACTIVE if confirmed else COLOR_UNCONFIRMED
            cv2.rectangle(
                annotated,
                (x1, y1),
                (x2, y2),
                color,
                box_thickness,
                cv2.LINE_AA,
            )

            if not confirmed:
                continue
            global_id = getattr(track, "global_id", None)
            if global_id is None:
                global_id = getattr(track, "track_id", None)
            if global_id is None:
                continue
            label = f"#{format_track_label(int(global_id))}"
            (tw, th), _baseline = cv2.getTextSize(
                label,
                cv2.FONT_HERSHEY_SIMPLEX,
                font_scale,
                font_thickness,
            )
            pill_x1 = x1
            pill_y1 = max(0, y1 - th - pad * 2 - margin)
            pill_x2 = pill_x1 + tw + pad * 2
            pill_y2 = pill_y1 + th + pad * 2
            cv2.rectangle(
                annotated,
                (pill_x1, pill_y1),
                (pill_x2, pill_y2),
                COLOR_LABEL_BG,
                -1,
            )
            cv2.putText(
                annotated,
                label,
                (pill_x1 + pad, pill_y2 - pad),
                cv2.FONT_HERSHEY_SIMPLEX,
                font_scale,
                color,
                font_thickness,
                cv2.LINE_AA,
            )

        return annotated


@dataclass(frozen=True)
class RuntimeAnnotationProvider:
    camera_to_feed_id: dict[str, str]

    def overlays_for_role(self, role: str) -> Sequence[FrameOverlay]:
        feed_id = self.camera_to_feed_id.get(role)
        if feed_id is None:
            return ()
        return (
            RuntimeTrackOverlay(
                lambda feed_id=feed_id: list(
                    getattr(_annotation_snapshot_for_feed(feed_id), "tracks", ()) or ()
                )
            ),
        )


@dataclass(frozen=True)
class ChannelZoneAnnotationProvider:
    def overlays_for_role(self, role: str) -> Sequence[FrameOverlay]:
        if role not in _ROLE_TO_CHANNEL_KEY:
            return ()
        return (ChannelArcOverlay(role, lambda role=role: _arc_config_for_role(role)),)


def _apply_overlays(feed: Any, overlays: Sequence[FrameOverlay]) -> None:
    set_overlays = getattr(feed, "set_overlays", None)
    if callable(set_overlays):
        set_overlays(list(overlays))
        return
    clear_overlays = getattr(feed, "clear_overlays", None)
    if callable(clear_overlays):
        clear_overlays()
    add_overlay = getattr(feed, "add_overlay", None)
    if callable(add_overlay):
        for overlay in overlays:
            add_overlay(overlay)


def attach_camera_annotations(
    camera_service: Any,
    *,
    providers: Sequence[CameraAnnotationProvider] | None = None,
) -> None:
    active_cameras = list(getattr(camera_service, "active_cameras", []) or [])
    configured_providers = tuple(
        providers
        or (
            ChannelZoneAnnotationProvider(),
            RuntimeAnnotationProvider(_CAMERA_TO_RT_FEED_ID),
        )
    )
    seen_feeds: set[int] = set()
    for camera_name in active_cameras:
        role = getattr(camera_name, "value", str(camera_name))
        feed = camera_service.get_feed(role)
        if feed is None:
            continue
        feed_marker = id(feed)
        if feed_marker in seen_feeds:
            continue
        seen_feeds.add(feed_marker)
        overlays: list[FrameOverlay] = []
        for provider in configured_providers:
            overlays.extend(provider.overlays_for_role(role))
        _apply_overlays(feed, overlays)
