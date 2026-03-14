from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass
import numpy as np
import cv2

from global_config import GlobalConfig
from irl.config import IRLConfig
from .camera import CaptureThread
from .aruco_tracker import ArucoTracker
from .regions import RegionName, Region

CAROUSEL_FEEDING_PLATFORM_DISTANCE_THRESHOLD_PX = 200
CAROUSEL_FEEDING_PLATFORM_PERIMETER_EXPANSION_PX = 30
CAROUSEL_FEEDING_PLATFORM_MAX_AREA_SQ_PX = 70000
CAROUSEL_FEEDING_PLATFORM_MIN_CORNER_ANGLE_DEG = 70

# dropzone = quadrants 0,1 (relative angle 0-180 from radius1)
# precise = quadrant 3 (relative angle 270-360 from radius1)
DROPZONE_START_DEG = 0.0
DROPZONE_END_DEG = 180.0
PRECISE_START_DEG = 270.0
PRECISE_END_DEG = 360.0


@dataclass
class CircularChannel:
    channel_id: int
    center: Tuple[float, float]
    radius: float
    radius1_angle_image: float
    shape: str = "circle"
    ellipse_axes: Optional[Tuple[float, float]] = None
    ellipse_angle_deg: float = 0.0
    mode: str = ""
    radius_points: Optional[List[Tuple[float, float]]] = None


@dataclass
class ChannelGeometry:
    second_channel: Optional[CircularChannel]
    third_channel: Optional[CircularChannel]


class ArucoRegionProvider:
    def __init__(
        self,
        gc: GlobalConfig,
        feeder_capture: CaptureThread,
        irl_config: IRLConfig,
    ):
        self._gc = gc
        self._irl_config = irl_config
        self._tracker = ArucoTracker(gc, feeder_capture)
        self._cached_regions: dict[RegionName, Region] = {}
        self._cached_tag_key: str = ""
        self._cached_geometry: ChannelGeometry = ChannelGeometry(None, None)
        self._cached_platform_corners: Optional[List[Tuple[float, float]]] = None

    def start(self) -> None:
        self._tracker.start()

    def stop(self) -> None:
        self._tracker.stop()

    def getTags(self) -> Dict[int, Tuple[float, float]]:
        return self._tracker.getTags()

    def getRawTags(self) -> Dict[int, Tuple[float, float]]:
        return self._tracker.getRawTags()

    def setSmoothingTimeSeconds(self, smoothing_time_s: float) -> None:
        self._tracker.setSmoothingTimeSeconds(smoothing_time_s)

    def getRegions(self, frame: np.ndarray) -> dict[RegionName, Region]:
        tags = self._tracker.getTags()
        h, w = frame.shape[:2]
        tag_key = f"{h}x{w}:" + str(sorted(tags.items()))
        if tag_key == self._cached_tag_key and self._cached_regions:
            return self._cached_regions

        aruco_config = self._irl_config.aruco_tags
        geometry = _computeChannelGeometry(tags, aruco_config)
        self._cached_geometry = geometry
        regions: dict[RegionName, Region] = {}

        if geometry.second_channel:
            ch = geometry.second_channel
            ch_mask = _rasterizeChannel(h, w, ch)
            regions[RegionName.CHANNEL_2] = Region(RegionName.CHANNEL_2, ch_mask)
            dz_mask = _rasterizeChannelWedge(h, w, ch, DROPZONE_START_DEG, DROPZONE_END_DEG)
            regions[RegionName.CHANNEL_2_DROPZONE] = Region(RegionName.CHANNEL_2_DROPZONE, dz_mask)
            pr_mask = _rasterizeChannelWedge(h, w, ch, PRECISE_START_DEG, PRECISE_END_DEG)
            regions[RegionName.CHANNEL_2_PRECISE] = Region(RegionName.CHANNEL_2_PRECISE, pr_mask)

        if geometry.third_channel:
            ch = geometry.third_channel
            ch_mask = _rasterizeChannel(h, w, ch)
            regions[RegionName.CHANNEL_3] = Region(RegionName.CHANNEL_3, ch_mask)
            dz_mask = _rasterizeChannelWedge(h, w, ch, DROPZONE_START_DEG, DROPZONE_END_DEG)
            regions[RegionName.CHANNEL_3_DROPZONE] = Region(RegionName.CHANNEL_3_DROPZONE, dz_mask)
            pr_mask = _rasterizeChannelWedge(h, w, ch, PRECISE_START_DEG, PRECISE_END_DEG)
            regions[RegionName.CHANNEL_3_PRECISE] = Region(RegionName.CHANNEL_3_PRECISE, pr_mask)

        platform_corners = self._computeCarouselPlatformCorners(tags)
        self._cached_platform_corners = platform_corners
        if platform_corners:
            plat_mask = np.zeros((h, w), dtype=np.uint8)
            pts = np.array([[int(x), int(y)] for x, y in platform_corners], dtype=np.int32)
            cv2.fillPoly(plat_mask, [pts], 255)
            regions[RegionName.CAROUSEL_PLATFORM] = Region(
                RegionName.CAROUSEL_PLATFORM, plat_mask > 0
            )

        self._cached_regions = regions
        self._cached_tag_key = tag_key
        return regions

    def annotateFrame(self, frame: np.ndarray) -> np.ndarray:
        annotated = frame.copy()
        tags = self._tracker.getTags()

        # draw tag positions and IDs
        for tag_id, (cx, cy) in tags.items():
            center = (int(cx), int(cy))
            cv2.circle(annotated, center, 8, (0, 255, 255), 2)
            cv2.putText(
                annotated,
                str(tag_id),
                (center[0] - 20, center[1] + 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.6,
                (0, 255, 0),
                3,
            )

        annotated = self._annotateChannelGeometry(annotated)
        annotated = self._annotateCarouselPlatform(annotated)
        return annotated

    def _annotateChannelGeometry(self, annotated: np.ndarray) -> np.ndarray:
        geometry = self._cached_geometry

        for ch, color, label in [
            (geometry.third_channel, (255, 0, 255), "Ch3"),
            (geometry.second_channel, (0, 255, 255), "Ch2"),
        ]:
            if ch is None:
                continue
            center = (int(ch.center[0]), int(ch.center[1]))
            radius = int(ch.radius)

            if ch.shape == "ellipse" and ch.ellipse_axes is not None:
                axes = (int(ch.ellipse_axes[0]), int(ch.ellipse_axes[1]))
                cv2.ellipse(
                    annotated, center, axes, ch.ellipse_angle_deg,
                    0, 360, color, 2,
                )
            else:
                cv2.circle(annotated, center, radius, color, 2)

            if ch.radius_points:
                for rp in ch.radius_points:
                    cv2.circle(annotated, (int(rp[0]), int(rp[1])), 4, color, -1)

            dim_color = (color[0] * 7 // 10, color[1] * 7 // 10, color[2] * 7 // 10)
            for q in range(4):
                angle_deg = ch.radius1_angle_image + q * 90.0
                angle_rad = np.radians(angle_deg)
                end_x = int(center[0] + radius * np.cos(angle_rad))
                end_y = int(center[1] + radius * np.sin(angle_rad))
                cv2.line(annotated, center, (end_x, end_y), dim_color, 1)

            for q in range(4):
                angle_deg = ch.radius1_angle_image + q * 90.0 + 45.0
                angle_rad = np.radians(angle_deg)
                label_radius = radius * 0.7
                label_x = int(center[0] + label_radius * np.cos(angle_rad))
                label_y = int(center[1] + label_radius * np.sin(angle_rad))
                cv2.putText(
                    annotated, str(q), (label_x - 10, label_y + 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2,
                )

            cv2.putText(
                annotated,
                f"{label} {ch.mode}",
                (center[0] - 20, center[1] - radius - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2,
            )

        return annotated

    def _annotateCarouselPlatform(self, annotated: np.ndarray) -> np.ndarray:
        corners = self._cached_platform_corners
        if corners is None:
            return annotated

        color = (255, 255, 0)
        points = np.array([[int(x), int(y)] for x, y in corners], dtype=np.int32)
        cv2.polylines(annotated, [points], isClosed=True, color=color, thickness=2)

        center_x = int(np.mean([x for x, _ in corners]))
        center_y = int(np.mean([y for _, y in corners]))
        cv2.putText(
            annotated, "FEED", (center_x - 20, center_y + 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2,
        )
        return annotated

    def _computeCarouselPlatformCorners(
        self, aruco_tags: Dict[int, Tuple[float, float]]
    ) -> Optional[List[Tuple[float, float]]]:
        platforms = self._getCarouselPlatforms(aruco_tags)
        if not platforms:
            return None

        reference_tag_id = self._irl_config.aruco_tags.third_c_channel_radius1_id
        if reference_tag_id not in aruco_tags:
            return None
        reference_pos = np.array(aruco_tags[reference_tag_id])

        for platform in platforms:
            corners = platform["corners"]
            if len(corners) < 3:
                continue
            center_x = float(np.mean([x for x, _ in corners]))
            center_y = float(np.mean([y for _, y in corners]))
            platform_center = np.array([center_x, center_y])

            distance = float(np.linalg.norm(platform_center - reference_pos))
            if distance > CAROUSEL_FEEDING_PLATFORM_DISTANCE_THRESHOLD_PX:
                continue

            expanded = _expandRectanglePerimeter(
                corners, CAROUSEL_FEEDING_PLATFORM_PERIMETER_EXPANSION_PX
            )

            corners_array = np.array(expanded)
            x = corners_array[:, 0]
            y = corners_array[:, 1]
            area = 0.5 * abs(float(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))))
            if area > CAROUSEL_FEEDING_PLATFORM_MAX_AREA_SQ_PX:
                continue

            valid, _ = _validateCornerAngles(
                expanded, CAROUSEL_FEEDING_PLATFORM_MIN_CORNER_ANGLE_DEG
            )
            if not valid:
                continue

            return expanded

        return None

    def _getCarouselPlatforms(
        self, aruco_tags: Dict[int, Tuple[float, float]]
    ) -> List[Dict]:
        platforms: List[Dict] = []

        for i, platform_config in enumerate([
            self._irl_config.aruco_tags.carousel_platform1,
            self._irl_config.aruco_tags.carousel_platform2,
            self._irl_config.aruco_tags.carousel_platform3,
            self._irl_config.aruco_tags.carousel_platform4,
        ]):
            corner_ids = [
                platform_config.corner1_id,
                platform_config.corner2_id,
                platform_config.corner3_id,
                platform_config.corner4_id,
            ]
            detected_corners: Dict[int, Tuple[float, float]] = {}
            for idx, corner_id in enumerate(corner_ids):
                if corner_id in aruco_tags:
                    detected_corners[idx] = aruco_tags[corner_id]

            if len(detected_corners) < 3:
                continue

            corners = list(detected_corners.values())

            if len(detected_corners) == 3:
                p0, p1, p2 = [np.array(c) for c in corners]
                candidates = [p0 + p1 - p2, p0 + p2 - p1, p1 + p2 - p0]
                best_candidate = candidates[0]
                best_score = float("inf")
                for candidate in candidates:
                    quad = [p0, p1, p2, candidate]
                    distances = []
                    for j in range(4):
                        for k in range(j + 1, 4):
                            distances.append(float(np.linalg.norm(quad[j] - quad[k])))
                    score = float(np.std(distances))
                    if score < best_score:
                        best_score = score
                        best_candidate = candidate
                corners.append(tuple(best_candidate))

            if len(corners) >= 3:
                corners_array = np.array(corners)
                centroid = np.mean(corners_array, axis=0)
                angles = [float(np.arctan2(c[1] - centroid[1], c[0] - centroid[0])) for c in corners]
                sorted_indices = np.argsort(angles)
                corners = [corners[int(si)] for si in sorted_indices]

            platforms.append({"platform_id": i, "corners": corners})

        return platforms


# --- Channel geometry computation (moved from analysis.py) ---

def _radius_ids_from_config(aruco_config: object, channel_prefix: str) -> List[int]:
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

    # 5+ radius tags -> ellipse fit
    if len(radius_points) >= 5:
        pts = np.array(radius_points[:5], dtype=np.float32).reshape(-1, 1, 2)
        try:
            fitted = cv2.fitEllipse(pts)
            (cx, cy), (major_len, minor_len), angle_deg = fitted
            fitted_center = (float(cx), float(cy))
            semi_axes = (float(major_len) / 2.0, float(minor_len) / 2.0)
            ref_point = output_guide if output_guide is not None else radius_points[0]
            ref_vec = np.array(ref_point) - np.array(fitted_center)
            ref_angle = float(np.degrees(np.arctan2(ref_vec[1], ref_vec[0])))
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

    # center + radius tags -> circle
    if center is not None and len(radius_points) >= 1:
        dists = [float(np.linalg.norm(np.array(p) - np.array(center))) for p in radius_points]
        radius = float(np.mean(dists)) * radius_multiplier
        ref_point = output_guide if output_guide is not None else radius_points[0]
        v1 = np.array(ref_point) - np.array(center)
        r1_angle_img = float(np.degrees(np.arctan2(v1[1], v1[0])))
        mode = "circle_2plus_radius_center" if len(radius_points) >= 2 else "circle_1_radius_center"
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


def _computeChannelGeometry(
    aruco_tags: Dict[int, Tuple[float, float]],
    aruco_config: object,
) -> ChannelGeometry:
    geometry = ChannelGeometry(second_channel=None, third_channel=None)

    second_center_id = getattr(aruco_config, "second_c_channel_center_id", None)
    second_output_guide_id = getattr(aruco_config, "second_c_channel_output_guide_id", None)
    third_center_id = getattr(aruco_config, "third_c_channel_center_id", None)
    third_output_guide_id = getattr(aruco_config, "third_c_channel_output_guide_id", None)
    second_radius_ids = _radius_ids_from_config(aruco_config, "second_c_channel")
    third_radius_ids = _radius_ids_from_config(aruco_config, "third_c_channel")
    second_multiplier = float(getattr(aruco_config, "second_c_channel_radius_multiplier", 1.0))
    third_multiplier = float(getattr(aruco_config, "third_c_channel_radius_multiplier", 1.0))

    geometry.second_channel = _compute_channel(
        2, second_center_id, second_output_guide_id,
        second_radius_ids, second_multiplier, aruco_tags,
    )
    geometry.third_channel = _compute_channel(
        3, third_center_id, third_output_guide_id,
        third_radius_ids, third_multiplier, aruco_tags,
    )
    return geometry


# --- Mask rasterization ---

def _rasterizeChannel(h: int, w: int, ch: CircularChannel) -> np.ndarray:
    mask = np.zeros((h, w), dtype=np.uint8)
    center = (int(ch.center[0]), int(ch.center[1]))
    if ch.shape == "ellipse" and ch.ellipse_axes is not None:
        axes = (int(ch.ellipse_axes[0]), int(ch.ellipse_axes[1]))
        cv2.ellipse(mask, center, axes, ch.ellipse_angle_deg, 0, 360, 255, -1)
    else:
        cv2.circle(mask, center, int(ch.radius), 255, -1)
    return mask > 0


def _rasterizeChannelWedge(
    h: int, w: int, ch: CircularChannel,
    start_rel_deg: float, end_rel_deg: float,
) -> np.ndarray:
    channel_mask = _rasterizeChannel(h, w, ch)

    # angular mask: compute relative angle of each pixel from radius1
    ys, xs = np.mgrid[0:h, 0:w]
    dx = xs.astype(np.float32) - float(ch.center[0])
    dy = ys.astype(np.float32) - float(ch.center[1])
    pixel_angles = np.degrees(np.arctan2(dy, dx))
    relative_angles = (pixel_angles - ch.radius1_angle_image) % 360.0
    angular_mask = (relative_angles >= start_rel_deg) & (relative_angles < end_rel_deg)

    return channel_mask & angular_mask


# --- Carousel platform helpers ---

def _validateCornerAngles(
    corners: List[Tuple[float, float]], min_angle_deg: float
) -> Tuple[bool, List[float]]:
    corners_array = np.array(corners)
    n = len(corners_array)
    angles: List[float] = []
    for i in range(n):
        prev = corners_array[(i - 1) % n]
        curr = corners_array[i]
        next_pt = corners_array[(i + 1) % n]
        v1 = prev - curr
        v2 = next_pt - curr
        cos_angle = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))
        cos_angle = float(np.clip(cos_angle, -1.0, 1.0))
        angle_deg = float(np.degrees(np.arccos(cos_angle)))
        angles.append(angle_deg)
    valid = all(a >= min_angle_deg for a in angles)
    return valid, angles


def _expandRectanglePerimeter(
    corners: List[Tuple[float, float]], expansion_px: float
) -> List[Tuple[float, float]]:
    corners_array = np.array(corners)
    center = np.mean(corners_array, axis=0)
    if len(corners_array) != 4:
        expanded = []
        for corner in corners_array:
            direction = corner - center
            distance = float(np.linalg.norm(direction))
            if distance > 0:
                direction = direction / distance
                expanded.append(tuple(corner + direction * expansion_px))
            else:
                expanded.append(tuple(corner))
        return expanded

    edge_0 = corners_array[1] - corners_array[0]
    edge_1 = corners_array[2] - corners_array[1]
    edge_2 = corners_array[3] - corners_array[2]
    edge_3 = corners_array[0] - corners_array[3]

    dim_0_len = (float(np.linalg.norm(edge_0)) + float(np.linalg.norm(edge_2))) / 2.0
    dim_1_len = (float(np.linalg.norm(edge_1)) + float(np.linalg.norm(edge_3))) / 2.0

    short_axis = edge_0 if dim_0_len <= dim_1_len else edge_1
    axis_norm = float(np.linalg.norm(short_axis))
    if axis_norm == 0:
        return [tuple(corner) for corner in corners_array]
    short_axis = short_axis / axis_norm

    expanded = []
    for corner in corners_array:
        offset = corner - center
        axis_proj = float(np.dot(offset, short_axis))
        if axis_proj > 0:
            expanded.append(tuple(corner + short_axis * expansion_px))
        elif axis_proj < 0:
            expanded.append(tuple(corner - short_axis * expansion_px))
        else:
            expanded.append(tuple(corner))
    return expanded
