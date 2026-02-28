from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple, TYPE_CHECKING
import numpy as np
import cv2
from vision.types import VisionResult

if TYPE_CHECKING:
    from irl.config import ArucoTagConfig

OBJECT_DETECTION_CONFIDENCE_THRESHOLD = 0.4


class FeederAnalysisState(Enum):
    OBJECT_IN_3_DROPZONE_PRECISE = "object_in_3_dropzone_precise"
    OBJECT_IN_3_DROPZONE = "object_in_3_dropzone"
    OBJECT_IN_2_DROPZONE_PRECISE = "object_in_2_dropzone_precise"
    OBJECT_IN_2_DROPZONE = "object_in_2_dropzone"
    CLEAR = "clear"


@dataclass
class CircularChannel:
    channel_id: int
    center: Tuple[float, float]
    radius: float
    radius1_angle_image: float  # angle to radius1 tag in image space
    shape: str = "circle"  # "circle" or "ellipse"
    ellipse_axes: Optional[Tuple[float, float]] = None  # (a, b) semi-axes for ellipse
    ellipse_angle_deg: float = 0.0
    mode: str = ""
    radius_points: Optional[List[Tuple[float, float]]] = None


@dataclass
class ChannelGeometry:
    second_channel: Optional[CircularChannel]
    third_channel: Optional[CircularChannel]


def _radius_ids_from_config(aruco_config: "ArucoTagConfig", channel_prefix: str) -> List[int]:
    list_attr = f"{channel_prefix}_radius_ids"
    if hasattr(aruco_config, list_attr):
        ids = getattr(aruco_config, list_attr)
        if ids:
            return [int(i) for i in ids if i is not None]

    fallback = []
    for role in ["radius1", "radius2", "radius3", "radius4", "radius5"]:
        attr = f"{channel_prefix}_{role}_id"
        if hasattr(aruco_config, attr):
            value = getattr(aruco_config, attr)
            if value is not None:
                fallback.append(int(value))
    return fallback


def _fit_centered_ellipse(
    center: Tuple[float, float],
    points: List[Tuple[float, float]],
) -> Optional[Tuple[Tuple[float, float], float]]:
    if len(points) < 3:
        return None

    cx, cy = center
    rows = []
    for px, py in points:
        x = px - cx
        y = py - cy
        rows.append([x * x, x * y, y * y])

    m = np.array(rows, dtype=np.float64)
    ones = np.ones((m.shape[0],), dtype=np.float64)

    try:
        coeffs, *_ = np.linalg.lstsq(m, ones, rcond=None)
    except np.linalg.LinAlgError:
        return None

    a, b, c = coeffs
    q = np.array([[a, b / 2.0], [b / 2.0, c]], dtype=np.float64)

    try:
        evals, evecs = np.linalg.eigh(q)
    except np.linalg.LinAlgError:
        return None

    if np.any(evals <= 1e-9):
        return None

    semi_axes = 1.0 / np.sqrt(evals)
    order = np.argsort(semi_axes)[::-1]
    semi_axes = semi_axes[order]
    evecs = evecs[:, order]

    major_vec = evecs[:, 0]
    angle_deg = float(np.degrees(np.arctan2(major_vec[1], major_vec[0])))
    return (float(semi_axes[0]), float(semi_axes[1])), angle_deg


def _point_in_ellipse(
    point: Tuple[float, float],
    center: Tuple[float, float],
    axes: Tuple[float, float],
    angle_deg: float,
) -> bool:
    px = point[0] - center[0]
    py = point[1] - center[1]
    theta = np.radians(-angle_deg)
    ct = np.cos(theta)
    st = np.sin(theta)
    x_local = px * ct - py * st
    y_local = px * st + py * ct
    a, b = axes
    if a <= 0 or b <= 0:
        return False
    value = (x_local / a) ** 2 + (y_local / b) ** 2
    return value <= 1.0


def _ellipse_normalized_angle(
    point: Tuple[float, float],
    center: Tuple[float, float],
    axes: Tuple[float, float],
    angle_deg: float,
) -> float:
    px = point[0] - center[0]
    py = point[1] - center[1]
    theta = np.radians(-angle_deg)
    ct = np.cos(theta)
    st = np.sin(theta)
    x_local = px * ct - py * st
    y_local = px * st + py * ct
    a, b = axes
    if a <= 0 or b <= 0:
        return 0.0
    return float(np.degrees(np.arctan2(y_local / b, x_local / a)))


def _compute_channel(
    channel_id: int,
    center_id: Optional[int],
    output_guide_id: Optional[int],
    radius_ids: List[int],
    radius_multiplier: float,
    aruco_tags: Dict[int, Tuple[float, float]],
) -> Optional[CircularChannel]:
    center = aruco_tags.get(center_id) if center_id is not None else None
    output_guide = aruco_tags.get(output_guide_id) if output_guide_id is not None else None
    radius_points = [aruco_tags[rid] for rid in radius_ids if rid in aruco_tags][:5]

    if not radius_points:
        return None

    # Preference 1: 5 radius tags -> ellipse (center optional)
    if len(radius_points) >= 5:
        pts = np.array(radius_points[:5], dtype=np.float32).reshape(-1, 1, 2)
        try:
            fitted = cv2.fitEllipse(pts)
            (cx, cy), (major_len, minor_len), angle_deg = fitted
            fitted_center = (float(cx), float(cy))
            semi_axes = (float(major_len) / 2.0, float(minor_len) / 2.0)
            if output_guide is not None:
                ref_angle = _ellipse_normalized_angle(
                    output_guide, fitted_center, semi_axes, float(angle_deg)
                )
            else:
                ref_angle = _ellipse_normalized_angle(
                    radius_points[0], fitted_center, semi_axes, float(angle_deg)
                )
            scaled_axes = (
                semi_axes[0] * radius_multiplier,
                semi_axes[1] * radius_multiplier,
            )
            mean_radius = float(np.mean(scaled_axes))
            return CircularChannel(
                channel_id=channel_id,
                center=fitted_center,
                radius=mean_radius,
                radius1_angle_image=ref_angle,
                shape="ellipse",
                ellipse_axes=scaled_axes,
                ellipse_angle_deg=float(angle_deg),
                mode="ellipse_5_radius",
                radius_points=radius_points,
            )
        except cv2.error:
            pass

    # Preference 3/4: circle from center + 2 radius tags OR center + 1 radius tag
    if center is not None and len(radius_points) >= 1:
        sample = radius_points
        dists = [float(np.linalg.norm(np.array(p) - np.array(center))) for p in sample]
        radius = float(np.mean(dists)) * radius_multiplier
        ref_point = output_guide if output_guide is not None else sample[0]
        v1 = np.array(ref_point) - np.array(center)
        r1_angle_img = float(np.degrees(np.arctan2(v1[1], v1[0])))
        if len(sample) >= 2:
            mode = "circle_2plus_radius_center"
        else:
            mode = "circle_1_radius_center"
        return CircularChannel(
            channel_id=channel_id,
            center=center,
            radius=radius,
            radius1_angle_image=r1_angle_img,
            shape="circle",
            ellipse_axes=None,
            ellipse_angle_deg=0.0,
            mode=mode,
            radius_points=radius_points,
        )

    return None


def computeChannelGeometry(
    aruco_tags: Dict[int, Tuple[float, float]],
    aruco_config: "ArucoTagConfig",
) -> ChannelGeometry:
    geometry = ChannelGeometry(second_channel=None, third_channel=None)

    second_center_id = getattr(aruco_config, "second_c_channel_center_id", None)
    second_output_guide_id = getattr(aruco_config, "second_c_channel_output_guide_id", None)
    third_center_id = getattr(aruco_config, "third_c_channel_center_id", None)
    third_output_guide_id = getattr(aruco_config, "third_c_channel_output_guide_id", None)
    second_radius_ids = _radius_ids_from_config(aruco_config, "second_c_channel")
    third_radius_ids = _radius_ids_from_config(aruco_config, "third_c_channel")
    second_multiplier = float(
        getattr(aruco_config, "second_c_channel_radius_multiplier", 1.0)
    )
    third_multiplier = float(
        getattr(aruco_config, "third_c_channel_radius_multiplier", 1.0)
    )

    geometry.second_channel = _compute_channel(
        2,
        second_center_id,
        second_output_guide_id,
        second_radius_ids,
        second_multiplier,
        aruco_tags,
    )
    geometry.third_channel = _compute_channel(
        3,
        third_center_id,
        third_output_guide_id,
        third_radius_ids,
        third_multiplier,
        aruco_tags,
    )

    return geometry


def isPointInCircle(
    point: Tuple[float, float],
    center: Tuple[float, float],
    radius: float,
) -> bool:
    distance = np.linalg.norm(np.array(point) - np.array(center))
    return distance <= radius


def determineObjectChannelAndQuadrant(
    obj_center_image: Tuple[float, float],
    geometry: ChannelGeometry,
) -> Optional[Tuple[int, int]]:
    # check channel 3 first (innermost)
    if geometry.third_channel:
        in_channel = False
        if (
            geometry.third_channel.shape == "ellipse"
            and geometry.third_channel.ellipse_axes is not None
        ):
            in_channel = _point_in_ellipse(
                obj_center_image,
                geometry.third_channel.center,
                geometry.third_channel.ellipse_axes,
                geometry.third_channel.ellipse_angle_deg,
            )
            obj_angle = _ellipse_normalized_angle(
                obj_center_image,
                geometry.third_channel.center,
                geometry.third_channel.ellipse_axes,
                geometry.third_channel.ellipse_angle_deg,
            )
        else:
            in_channel = isPointInCircle(
                obj_center_image,
                geometry.third_channel.center,
                geometry.third_channel.radius,
            )
            dx = obj_center_image[0] - geometry.third_channel.center[0]
            dy = obj_center_image[1] - geometry.third_channel.center[1]
            obj_angle = np.degrees(np.arctan2(dy, dx))

        if in_channel:
            # relative angle from radius1
            relative_angle = obj_angle - geometry.third_channel.radius1_angle_image
            while relative_angle < 0:
                relative_angle += 360
            while relative_angle >= 360:
                relative_angle -= 360

            quadrant = int(relative_angle / 90.0)
            return (3, quadrant)

    # check channel 2
    if geometry.second_channel:
        in_channel = False
        if (
            geometry.second_channel.shape == "ellipse"
            and geometry.second_channel.ellipse_axes is not None
        ):
            in_channel = _point_in_ellipse(
                obj_center_image,
                geometry.second_channel.center,
                geometry.second_channel.ellipse_axes,
                geometry.second_channel.ellipse_angle_deg,
            )
            obj_angle = _ellipse_normalized_angle(
                obj_center_image,
                geometry.second_channel.center,
                geometry.second_channel.ellipse_axes,
                geometry.second_channel.ellipse_angle_deg,
            )
        else:
            in_channel = isPointInCircle(
                obj_center_image,
                geometry.second_channel.center,
                geometry.second_channel.radius,
            )
            dx = obj_center_image[0] - geometry.second_channel.center[0]
            dy = obj_center_image[1] - geometry.second_channel.center[1]
            obj_angle = np.degrees(np.arctan2(dy, dx))

        if in_channel:
            # relative angle from radius1
            relative_angle = obj_angle - geometry.second_channel.radius1_angle_image
            while relative_angle < 0:
                relative_angle += 360
            while relative_angle >= 360:
                relative_angle -= 360

            quadrant = int(relative_angle / 90.0)
            return (2, quadrant)

    return None


def analyzeFeederState(
    object_detections: List[VisionResult],
    geometry: ChannelGeometry,
) -> FeederAnalysisState:
    if not object_detections:
        return FeederAnalysisState.CLEAR

    # filter objects by confidence threshold
    high_confidence_objects = [
        detection
        for detection in object_detections
        if detection.confidence >= OBJECT_DETECTION_CONFIDENCE_THRESHOLD
    ]

    if not high_confidence_objects:
        return FeederAnalysisState.CLEAR

    has_object_in_3_dropzone_precise = False
    has_object_in_3_dropzone = False
    has_object_in_2_dropzone_precise = False
    has_object_in_2_dropzone = False

    for detection in high_confidence_objects:
        if detection.bbox is None:
            continue
        x1, y1, x2, y2 = detection.bbox
        center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

        result = determineObjectChannelAndQuadrant(center, geometry)
        if result is None:
            continue

        channel_id, quadrant = result

        # check for precise mode (quadrant 3) and normal dropzone (quadrants 0, 1)
        if channel_id == 3:
            if quadrant == 3:
                has_object_in_3_dropzone_precise = True
            elif quadrant in [0, 1]:
                has_object_in_3_dropzone = True

        if channel_id == 2:
            if quadrant == 3:
                has_object_in_2_dropzone_precise = True
            elif quadrant in [0, 1]:
                has_object_in_2_dropzone = True

    # return in priority order
    if has_object_in_3_dropzone_precise:
        return FeederAnalysisState.OBJECT_IN_3_DROPZONE_PRECISE
    if has_object_in_3_dropzone:
        return FeederAnalysisState.OBJECT_IN_3_DROPZONE
    if has_object_in_2_dropzone_precise:
        return FeederAnalysisState.OBJECT_IN_2_DROPZONE_PRECISE
    if has_object_in_2_dropzone:
        return FeederAnalysisState.OBJECT_IN_2_DROPZONE

    return FeederAnalysisState.CLEAR
