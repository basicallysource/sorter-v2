from typing import Optional

import numpy as np
import cv2

from blob_manager import getChannelPolygons
from defs.consts import CHANNEL_SECTION_COUNT, CHANNEL_SECTION_DEG
from .regions import RegionName, Region

CHANNEL_COLORS: dict[RegionName, tuple[int, int, int]] = {
    RegionName.CHANNEL_2: (0, 200, 255),
    RegionName.CHANNEL_3: (255, 200, 0),
    RegionName.CHANNEL_2_DROPZONE: (0, 180, 0),
    RegionName.CHANNEL_2_PRECISE: (0, 100, 255),
    RegionName.CHANNEL_3_DROPZONE: (255, 180, 0),
    RegionName.CHANNEL_3_PRECISE: (100, 0, 255),
    RegionName.CAROUSEL_PLATFORM: (0, 255, 128),
}

DROPZONE_COLOR = (0, 200, 0)
PRECISE_COLOR = (0, 100, 255)


def parseSavedChannelArcZones(*args, **kwargs):
    from subsystems.feeder.analysis import parseSavedChannelArcZones as _impl

    return _impl(*args, **kwargs)


def channelArcCropPolygon(*args, **kwargs):
    from subsystems.feeder.analysis import channelArcCropPolygon as _impl

    return _impl(*args, **kwargs)


def channelArcInnerPolygon(*args, **kwargs):
    from subsystems.feeder.analysis import channelArcInnerPolygon as _impl

    return _impl(*args, **kwargs)


def zoneSectionsForChannel(*args, **kwargs):
    from subsystems.feeder.analysis import zoneSectionsForChannel as _impl

    return _impl(*args, **kwargs)


def _sectionsToAngularMask(
    h: int, w: int,
    center_x: float, center_y: float,
    section_zero_angle: float,
    sections: range,
) -> np.ndarray:
    ys, xs = np.mgrid[0:h, 0:w]
    dx = xs.astype(np.float32) - center_x
    dy = ys.astype(np.float32) - center_y
    pixel_angles = np.degrees(np.arctan2(dy, dx))
    relative_angles = (pixel_angles - section_zero_angle) % 360.0
    pixel_sections = (relative_angles / CHANNEL_SECTION_DEG).astype(np.int32)

    mask = np.zeros((h, w), dtype=np.bool_)
    for s in sections:
        mask |= pixel_sections == s
    return mask


def _normalizeAngle(angle: float) -> float:
    return (float(angle) % 360.0 + 360.0) % 360.0


def _positiveAngleSpan(start_angle: float, end_angle: float) -> float:
    span = (_normalizeAngle(end_angle) - _normalizeAngle(start_angle) + 360.0) % 360.0
    return span if span > 0.0 else 360.0


def _zoneNumber(raw_zone: object, key: str, fallback: float) -> float:
    if isinstance(raw_zone, dict):
        value = raw_zone.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return float(fallback)


class HanddrawnRegionProvider:
    _cached_regions: dict[RegionName, Region]
    _cached_frame_shape: tuple[int, int]
    _polygons: dict[str, list[list[int]]]
    _channel_angles: dict[str, float]
    _arc_params: dict[str, object]

    def __init__(self) -> None:
        self._cached_regions = {}
        self._cached_frame_shape = (0, 0)
        self._polygons = {}
        self._channel_angles = {}
        self._arc_params = {}
        # Static-sprite cache for annotateFrameForChannel — keyed by
        # (poly_key, h, w, revision). The overlay (polylines, fill arcs, label)
        # doesn't change between frames, so render once and blend onto the
        # frame's bbox slice. Bumped via _revision on reloadPolygons.
        self._channel_sprite_cache: dict = {}
        self._revision: int = 0
        self._loadPolygons()

    def reloadPolygons(self) -> None:
        self._loadPolygons()
        self._cached_regions = {}
        self._cached_frame_shape = (0, 0)
        self._channel_sprite_cache = {}
        self._revision += 1

    def _loadPolygons(self) -> None:
        saved = getChannelPolygons()
        if saved is None:
            raise RuntimeError(
                "No handdrawn regions found. Draw them from the Settings → Zones editor in the UI."
            )
        polygons = saved.get("polygons", {})
        if not polygons:
            raise RuntimeError(
                "Handdrawn regions are empty. Draw them from the Settings → Zones editor in the UI."
            )
        self._polygons = polygons
        self._channel_angles = saved.get("channel_angles", {})
        self._arc_params = saved.get("arc_params", {})
        res = saved.get("resolution", [1920, 1080])
        self._saved_resolution = (int(res[0]), int(res[1]))

    def reloadPolygons(self) -> None:  # noqa: F811 - kept for compatibility
        """Reload polygon data from disk and clear cached regions."""
        self._loadPolygons()
        self._cached_regions = {}
        self._cached_frame_shape = (0, 0)
        self._channel_sprite_cache = {}
        self._revision += 1

    def _channelMask(
        self,
        h: int,
        w: int,
        poly_key: str,
        pts_list: list[list[int]],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, tuple[float, float], float]:
        channel_key = (
            "second"
            if poly_key == "second_channel"
            else "third"
            if poly_key == "third_channel"
            else "classification_channel"
        )
        arc = parseSavedChannelArcZones(channel_key, self._channel_angles, self._arc_params)
        if arc is not None and arc.outer_radius > arc.inner_radius > 0:
            outer = channelArcCropPolygon(arc)
            inner = channelArcInnerPolygon(arc)
            mask = np.zeros((h, w), dtype=np.uint8)
            cv2.fillPoly(mask, [outer], 255)
            cv2.fillPoly(mask, [inner], 0)
            return mask, outer, inner, arc.center, arc.outer_radius

        pts = np.array(pts_list, dtype=np.int32)
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(mask, [pts], 255)
        center = (float(np.mean(pts[:, 0])), float(np.mean(pts[:, 1])))
        radius = float(np.max(np.linalg.norm(pts - np.array(center), axis=1)))
        return mask, pts, None, center, radius

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def getRegions(self, frame: np.ndarray) -> dict[RegionName, Region]:
        h, w = frame.shape[:2]
        if (h, w) == self._cached_frame_shape and self._cached_regions:
            return self._cached_regions

        regions: dict[RegionName, Region] = {}

        second_pts = self._polygons.get("second_channel")
        if second_pts and len(second_pts) >= 3:
            second_angle = self._channel_angles.get("second", 0.0)
            second_drop_sections, second_exit_sections = zoneSectionsForChannel(
                2,
                second_angle,
                parseSavedChannelArcZones("second", self._channel_angles, self._arc_params),
            )
            self._buildChannelRegions(
                h, w, second_pts, second_angle,
                RegionName.CHANNEL_2,
                RegionName.CHANNEL_2_DROPZONE,
                RegionName.CHANNEL_2_PRECISE,
                second_drop_sections,
                second_exit_sections,
                regions,
            )

        third_pts = self._polygons.get("third_channel")
        if third_pts and len(third_pts) >= 3:
            third_angle = self._channel_angles.get("third", 0.0)
            third_drop_sections, third_exit_sections = zoneSectionsForChannel(
                3,
                third_angle,
                parseSavedChannelArcZones("third", self._channel_angles, self._arc_params),
            )
            self._buildChannelRegions(
                h, w, third_pts, third_angle,
                RegionName.CHANNEL_3,
                RegionName.CHANNEL_3_DROPZONE,
                RegionName.CHANNEL_3_PRECISE,
                third_drop_sections,
                third_exit_sections,
                regions,
            )

        carousel_pts = self._polygons.get("carousel")
        if carousel_pts and len(carousel_pts) >= 3:
            mask = np.zeros((h, w), dtype=np.uint8)
            pts = np.array(carousel_pts, dtype=np.int32)
            cv2.fillPoly(mask, [pts], 255)
            regions[RegionName.CAROUSEL_PLATFORM] = Region(
                RegionName.CAROUSEL_PLATFORM, mask > 0
            )

        self._cached_regions = regions
        self._cached_frame_shape = (h, w)
        return regions

    def _buildChannelRegions(
        self,
        h: int, w: int,
        pts_list: list[list[int]],
        section_zero_angle: float,
        channel_name: RegionName,
        dropzone_name: RegionName,
        precise_name: RegionName,
        dropzone_sections: set[int],
        exit_sections: set[int],
        regions: dict[RegionName, Region],
    ) -> None:
        poly_key = "second_channel" if channel_name == RegionName.CHANNEL_2 else "third_channel"
        channel_mask, _outline, _inner_outline, center, _radius = self._channelMask(h, w, poly_key, pts_list)
        channel_bool = channel_mask > 0
        regions[channel_name] = Region(channel_name, channel_bool)

        center_x = center[0]
        center_y = center[1]

        dz_angular = _sectionsToAngularMask(
            h, w, center_x, center_y, section_zero_angle, dropzone_sections,
        )
        regions[dropzone_name] = Region(dropzone_name, channel_bool & dz_angular)

        pr_angular = _sectionsToAngularMask(
            h, w, center_x, center_y, section_zero_angle, exit_sections,
        )
        regions[precise_name] = Region(precise_name, channel_bool & pr_angular)

    def _arcZonePolygon(
        self,
        channel_key: str,
        zone_key: str,
        center: tuple[float, float],
        inner_radius: float,
        outer_radius: float,
        fallback_start_angle: float,
        fallback_end_angle: float,
    ) -> np.ndarray | None:
        raw_arc = self._arc_params.get(channel_key) if isinstance(self._arc_params, dict) else None
        if not isinstance(raw_arc, dict):
            return None
        raw_zone = raw_arc.get(zone_key)
        if not isinstance(raw_zone, dict):
            return None

        start_angle = _zoneNumber(raw_zone, "start_angle", fallback_start_angle)
        end_angle = _zoneNumber(raw_zone, "end_angle", fallback_end_angle)
        start_outer = _zoneNumber(raw_zone, "start_outer_angle", start_angle)
        end_outer = _zoneNumber(raw_zone, "end_outer_angle", end_angle)
        start_inner = _zoneNumber(raw_zone, "start_inner_angle", start_outer)
        end_inner = _zoneNumber(raw_zone, "end_inner_angle", end_outer)

        outer_span = _positiveAngleSpan(start_outer, end_outer)
        inner_span = _positiveAngleSpan(start_inner, end_inner)
        outer_segments = max(8, int(round((outer_span / 360.0) * 64.0)))
        inner_segments = max(8, int(round((inner_span / 360.0) * 64.0)))
        cx, cy = center

        points: list[tuple[int, int]] = []
        for i in range(outer_segments + 1):
            angle = np.deg2rad(start_outer + (outer_span * i) / outer_segments)
            points.append((
                int(round(cx + outer_radius * np.cos(angle))),
                int(round(cy + outer_radius * np.sin(angle))),
            ))
        for i in range(inner_segments, -1, -1):
            angle = np.deg2rad(start_inner + (inner_span * i) / inner_segments)
            points.append((
                int(round(cx + inner_radius * np.cos(angle))),
                int(round(cy + inner_radius * np.sin(angle))),
            ))
        return np.array(points, dtype=np.int32)

    def _fillArcZoneOverlay(
        self,
        overlay: np.ndarray,
        channel_key: str,
        center: tuple[float, float],
        radius_scale: float,
    ) -> bool:
        arc = parseSavedChannelArcZones(channel_key, self._channel_angles, self._arc_params)
        if arc is None or arc.outer_radius <= arc.inner_radius or arc.inner_radius <= 0:
            return False

        inner_radius = float(arc.inner_radius) * radius_scale
        drop_outer_radius = float(arc.outer_radius) * radius_scale
        exit_outer_radius = float(arc.exit_outer_radius) * radius_scale

        drop_poly = self._arcZonePolygon(
            channel_key,
            "drop_zone",
            center,
            inner_radius,
            drop_outer_radius,
            arc.drop_start_angle,
            arc.drop_end_angle,
        )
        exit_poly = self._arcZonePolygon(
            channel_key,
            "exit_zone",
            center,
            inner_radius,
            exit_outer_radius,
            arc.exit_start_angle,
            arc.exit_end_angle,
        )
        if drop_poly is None and exit_poly is None:
            return False
        if drop_poly is not None:
            cv2.fillPoly(overlay, [drop_poly], DROPZONE_COLOR)
        if exit_poly is not None:
            cv2.fillPoly(overlay, [exit_poly], PRECISE_COLOR)
        return True

    def annotateFrame(self, frame: np.ndarray) -> np.ndarray:
        annotated = frame.copy()

        for poly_key, region_name, label in [
            ("second_channel", RegionName.CHANNEL_2, "Ch2"),
            ("third_channel", RegionName.CHANNEL_3, "Ch3"),
        ]:
            pts_list = self._polygons.get(poly_key)
            if not pts_list or len(pts_list) < 3:
                continue
            angle_key = "second" if poly_key == "second_channel" else "third"
            channel_id = 2 if poly_key == "second_channel" else 3
            dz_sections, ex_sections = zoneSectionsForChannel(
                channel_id,
                float(self._channel_angles.get(angle_key, 0.0)),
                parseSavedChannelArcZones(angle_key, self._channel_angles, self._arc_params),
            )
            ch_mask, pts, inner_pts, center, disp_r = self._channelMask(
                annotated.shape[0],
                annotated.shape[1],
                poly_key,
                pts_list,
            )
            color = CHANNEL_COLORS[region_name]
            cv2.polylines(annotated, [pts], isClosed=True, color=color, thickness=2)
            if inner_pts is not None and len(inner_pts) >= 3:
                cv2.polylines(annotated, [inner_pts], isClosed=True, color=color, thickness=2)

            cx, cy = int(center[0]), int(center[1])
            disp_r = int(disp_r)
            r1_angle = self._channel_angles.get(angle_key, 0.0)

            # low-opacity fill for dropzone and precise sections
            overlay = annotated.copy()
            if not self._fillArcZoneOverlay(overlay, angle_key, (float(center[0]), float(center[1])), 1.0):
                for q in range(CHANNEL_SECTION_COUNT):
                    if q in ex_sections:
                        fill = PRECISE_COLOR
                    elif q in dz_sections:
                        fill = DROPZONE_COLOR
                    else:
                        continue
                    arc_pts = [(cx, cy)]
                    for a in np.linspace(
                        r1_angle + q * CHANNEL_SECTION_DEG,
                        r1_angle + (q + 1) * CHANNEL_SECTION_DEG,
                        8,
                    ):
                        arc_pts.append((
                            int(cx + disp_r * np.cos(np.radians(a))),
                            int(cy + disp_r * np.sin(np.radians(a))),
                        ))
                    cv2.fillPoly(overlay, [np.array(arc_pts, dtype=np.int32)], fill)
            overlay[ch_mask == 0] = annotated[ch_mask == 0]
            annotated = cv2.addWeighted(overlay, 0.18, annotated, 0.82, 0)

            cv2.putText(annotated, label, (cx - 20, cy - disp_r - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        # draw carousel polygon (only in unified feeder mode)
        carousel_pts = self._polygons.get("carousel")
        if carousel_pts and len(carousel_pts) >= 3:
            pts = np.array(carousel_pts, dtype=np.int32)
            color = CHANNEL_COLORS[RegionName.CAROUSEL_PLATFORM]
            cv2.polylines(annotated, [pts], isClosed=True, color=color, thickness=2)
            cx = int(np.mean(pts[:, 0]))
            cy = int(np.mean(pts[:, 1]))
            cv2.putText(
                annotated, "Carousel", (cx - 30, cy + 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2,
            )

        return annotated

    def _savedResolutionForPolygonKey(self, poly_key: str) -> tuple[int, int]:
        """Return the editor resolution for a specific channel polygon."""
        channel_key = (
            "second"
            if poly_key == "second_channel"
            else "third"
            if poly_key == "third_channel"
            else "classification_channel"
            if poly_key == "classification_channel"
            else None
        )
        if channel_key is not None:
            raw_arc = self._arc_params.get(channel_key) if isinstance(self._arc_params, dict) else None
            if isinstance(raw_arc, dict):
                resolution = raw_arc.get("resolution")
                if isinstance(resolution, (list, tuple)) and len(resolution) >= 2:
                    width, height = resolution[0], resolution[1]
                    if isinstance(width, (int, float)) and isinstance(height, (int, float)):
                        if width > 0 and height > 0:
                            return int(width), int(height)
        return self._saved_resolution

    def _scaleForFrame(self, frame: np.ndarray, poly_key: str):
        """Compute scale factors from this polygon's editor resolution to frame size."""
        h, w = frame.shape[:2]
        src_w, src_h = self._savedResolutionForPolygonKey(poly_key)
        return w / src_w, h / src_h

    def _scaledChannelMask(self, h, w, poly_key, pts_list, sx, sy):
        """Like _channelMask but scales coordinates from saved resolution to frame size."""
        channel_key = (
            "second"
            if poly_key == "second_channel"
            else "third"
            if poly_key == "third_channel"
            else "classification_channel"
        )
        arc = parseSavedChannelArcZones(channel_key, self._channel_angles, self._arc_params)
        if arc is not None and arc.outer_radius > arc.inner_radius > 0:
            cx = arc.center[0] * sx
            cy = arc.center[1] * sy
            r_scale = (sx + sy) / 2.0
            outer = channelArcCropPolygon(arc, center=(cx, cy), radius_scale=r_scale)
            inner = channelArcInnerPolygon(arc, center=(cx, cy), radius_scale=r_scale)
            mask = np.zeros((h, w), dtype=np.uint8)
            cv2.fillPoly(mask, [outer], 255)
            cv2.fillPoly(mask, [inner], 0)
            return mask, outer, inner, (cx, cy), arc.outer_radius * r_scale

        pts = np.array(pts_list, dtype=np.float64)
        pts[:, 0] *= sx
        pts[:, 1] *= sy
        pts = pts.astype(np.int32)
        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(mask, [pts], 255)
        center = (float(np.mean(pts[:, 0])), float(np.mean(pts[:, 1])))
        radius = float(np.max(np.linalg.norm(pts - np.array(center), axis=1)))
        return mask, pts, None, center, radius

    def annotateFrameForChannel(self, frame: np.ndarray, poly_key: str) -> np.ndarray:
        """Annotate a frame with zone overlays for a single channel.

        poly_key: 'second_channel', 'third_channel', 'classification_channel', or 'carousel'

        The sprite (polylines + arc-zone fills + label) is static for a given
        (poly_key, frame_shape, _revision), so render it once on a small bbox
        canvas and blend onto the frame in-place — avoids the ~25 MB
        full-frame .copy() + cv2.addWeighted that previously dominated 4K
        annotation.
        """
        h, w = frame.shape[:2]
        sx, sy = self._scaleForFrame(frame, poly_key)

        if poly_key == "carousel":
            # The carousel preview just draws a polygon outline — let the
            # sprite cache handle that too so we never copy the frame.
            sprite = self._channelSprite(poly_key, h, w, sx, sy)
            if sprite is None:
                return frame
            self._applyChannelSprite(frame, sprite)
            return frame

        pts_list = self._polygons.get(poly_key)
        if not pts_list or len(pts_list) < 3:
            return frame

        sprite = self._channelSprite(poly_key, h, w, sx, sy)
        if sprite is None:
            return frame
        self._applyChannelSprite(frame, sprite)
        return frame

    def _channelSprite(
        self,
        poly_key: str,
        h: int,
        w: int,
        sx: float,
        sy: float,
    ) -> Optional[dict]:
        cache_key = (poly_key, h, w, self._revision)
        cached = self._channel_sprite_cache.get(cache_key)
        if cached is not None:
            return cached

        if poly_key == "carousel":
            carousel_pts = self._polygons.get("carousel")
            if not carousel_pts or len(carousel_pts) < 3:
                return None
            pts = np.array(carousel_pts, dtype=np.float64)
            pts[:, 0] *= sx
            pts[:, 1] *= sy
            pts = pts.astype(np.int32)
            color = CHANNEL_COLORS[RegionName.CAROUSEL_PLATFORM]
            x1, y1 = pts[:, 0].min(), pts[:, 1].min()
            x2, y2 = pts[:, 0].max(), pts[:, 1].max()
            margin = 3
            x1 = max(0, int(x1) - margin)
            y1 = max(0, int(y1) - margin)
            x2 = min(w, int(x2) + margin)
            y2 = min(h, int(y2) + margin)
            lines_layer = np.zeros((y2 - y1, x2 - x1, 3), dtype=np.uint8)
            lines_mask = np.zeros((y2 - y1, x2 - x1), dtype=np.uint8)
            pts_local = pts.copy()
            pts_local[:, 0] -= x1
            pts_local[:, 1] -= y1
            cv2.polylines(lines_layer, [pts_local], isClosed=True, color=color, thickness=2)
            cv2.polylines(lines_mask, [pts_local], isClosed=True, color=255, thickness=2)
            sprite = {
                "bbox": (y1, y2, x1, x2),
                "fill_layer": None,
                "fill_mask": None,
                "lines_layer": lines_layer,
                "lines_mask": lines_mask,
            }
            self._channel_sprite_cache[cache_key] = sprite
            return sprite

        region_name = (
            RegionName.CHANNEL_2 if poly_key == "second_channel"
            else RegionName.CHANNEL_3 if poly_key == "third_channel"
            else RegionName.CAROUSEL_PLATFORM
        )
        label = (
            "Ch2" if poly_key == "second_channel"
            else "Ch3" if poly_key == "third_channel"
            else "Cls"
        )
        angle_key = (
            "second" if poly_key == "second_channel"
            else "third" if poly_key == "third_channel"
            else "classification_channel"
        )
        channel_id = 2 if poly_key == "second_channel" else 3 if poly_key == "third_channel" else 4

        pts_list = self._polygons.get(poly_key)
        if not pts_list or len(pts_list) < 3:
            return None

        dz_sections, ex_sections = zoneSectionsForChannel(
            channel_id,
            float(self._channel_angles.get(angle_key, 0.0)),
            parseSavedChannelArcZones(angle_key, self._channel_angles, self._arc_params),
        )
        ch_mask, pts, inner_pts, center, disp_r = self._scaledChannelMask(
            h, w, poly_key, pts_list, sx, sy,
        )
        color = CHANNEL_COLORS[region_name]
        cx, cy = int(center[0]), int(center[1])
        disp_r = int(disp_r)
        r1_angle = self._channel_angles.get(angle_key, 0.0)
        r_scale = (sx + sy) / 2.0

        # Bbox covers the polygon, the channel mask, the label position, and
        # any arc-zone fills that may extend slightly beyond. Pad a little.
        ys, xs = np.where(ch_mask > 0)
        if len(xs) == 0:
            return None
        x1 = int(min(xs.min(), pts[:, 0].min()))
        y1 = int(min(ys.min(), pts[:, 1].min(), cy - disp_r - 30))
        x2 = int(max(xs.max(), pts[:, 0].max()))
        y2 = int(max(ys.max(), pts[:, 1].max()))
        if inner_pts is not None and len(inner_pts) >= 3:
            x1 = min(x1, int(inner_pts[:, 0].min()))
            y1 = min(y1, int(inner_pts[:, 1].min()))
            x2 = max(x2, int(inner_pts[:, 0].max()))
            y2 = max(y2, int(inner_pts[:, 1].max()))
        margin = 4
        x1 = max(0, x1 - margin); y1 = max(0, y1 - margin)
        x2 = min(w, x2 + margin); y2 = min(h, y2 + margin)
        bh, bw = y2 - y1, x2 - x1

        ch_mask_local = ch_mask[y1:y2, x1:x2]

        # Fill layer: zero canvas with arc-zone colors drawn on top. Mask
        # restricts the blend to inside ch_mask.
        fill_layer = np.zeros((bh, bw, 3), dtype=np.uint8)
        # Run the existing fill helper at full-frame coords on a full-shape
        # zero canvas, then crop. Easier than translating coord math in two
        # call paths.
        full_fill = np.zeros((h, w, 3), dtype=np.uint8)
        if not self._fillArcZoneOverlay(
            full_fill, angle_key, (float(center[0]), float(center[1])), r_scale
        ):
            for q in range(CHANNEL_SECTION_COUNT):
                if q in ex_sections:
                    fill = PRECISE_COLOR
                elif q in dz_sections:
                    fill = DROPZONE_COLOR
                else:
                    continue
                arc_pts = [(cx, cy)]
                for a in np.linspace(
                    r1_angle + q * CHANNEL_SECTION_DEG,
                    r1_angle + (q + 1) * CHANNEL_SECTION_DEG,
                    8,
                ):
                    arc_pts.append((
                        int(cx + disp_r * np.cos(np.radians(a))),
                        int(cy + disp_r * np.sin(np.radians(a))),
                    ))
                cv2.fillPoly(full_fill, [np.array(arc_pts, dtype=np.int32)], fill)
        fill_layer[:] = full_fill[y1:y2, x1:x2]
        fill_mask = (ch_mask_local > 0).astype(np.uint8) * 255
        # Erase fill outside ch_mask so the blend's no-op pixels stay zero
        # (avoids leaking arc fills outside the channel boundary).
        fill_layer[ch_mask_local == 0] = 0

        # Lines layer: polylines + label drawn opaque, with a coverage mask.
        lines_layer = np.zeros((bh, bw, 3), dtype=np.uint8)
        lines_mask = np.zeros((bh, bw), dtype=np.uint8)
        pts_local = pts.copy(); pts_local[:, 0] -= x1; pts_local[:, 1] -= y1
        cv2.polylines(lines_layer, [pts_local], isClosed=True, color=color, thickness=2)
        cv2.polylines(lines_mask, [pts_local], isClosed=True, color=255, thickness=2)
        if inner_pts is not None and len(inner_pts) >= 3:
            inner_local = inner_pts.copy(); inner_local[:, 0] -= x1; inner_local[:, 1] -= y1
            cv2.polylines(lines_layer, [inner_local], isClosed=True, color=color, thickness=2)
            cv2.polylines(lines_mask, [inner_local], isClosed=True, color=255, thickness=2)
        label_org = (cx - 20 - x1, cy - disp_r - 10 - y1)
        if 0 <= label_org[1] < bh and 0 <= label_org[0] < bw:
            cv2.putText(lines_layer, label, label_org,
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            cv2.putText(lines_mask, label, label_org,
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, 255, 2)

        sprite = {
            "bbox": (y1, y2, x1, x2),
            "fill_layer": fill_layer,
            "fill_mask": fill_mask,
            "lines_layer": lines_layer,
            "lines_mask": lines_mask,
        }
        self._channel_sprite_cache[cache_key] = sprite
        return sprite

    @staticmethod
    def _applyChannelSprite(frame: np.ndarray, sprite: dict) -> None:
        y1, y2, x1, x2 = sprite["bbox"]
        slice_view = frame[y1:y2, x1:x2]
        fill_layer = sprite["fill_layer"]
        fill_mask = sprite["fill_mask"]
        if fill_layer is not None and fill_mask is not None:
            # Inside the channel mask: 0.82*frame + 0.18*fill. Outside: unchanged.
            blended = cv2.addWeighted(slice_view, 0.82, fill_layer, 0.18, 0)
            cv2.copyTo(blended, fill_mask, slice_view)
        lines_layer = sprite["lines_layer"]
        lines_mask = sprite["lines_mask"]
        if lines_layer is not None and lines_mask is not None:
            cv2.copyTo(lines_layer, lines_mask, slice_view)
