import numpy as np
import cv2

from blob_manager import getChannelPolygons
from defs.consts import CHANNEL_SECTION_COUNT, CHANNEL_SECTION_DEG
from subsystems.feeder.analysis import parseSavedChannelArcZones, zoneSectionsForChannel
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
        self._loadPolygons()

    def _loadPolygons(self) -> None:
        saved = getChannelPolygons()
        if saved is None:
            raise RuntimeError(
                "No handdrawn regions found. Run the polygon editor first:\n"
                "  uv run python scripts/polygon_editor.py"
            )
        polygons = saved.get("polygons", {})
        if not polygons:
            raise RuntimeError(
                "Handdrawn regions are empty. Run the polygon editor first:\n"
                "  uv run python scripts/polygon_editor.py"
            )
        self._polygons = polygons
        self._channel_angles = saved.get("channel_angles", {})
        self._arc_params = saved.get("arc_params", {})
        res = saved.get("resolution", [1920, 1080])
        self._saved_resolution = (int(res[0]), int(res[1]))

    def _channelMask(
        self,
        h: int,
        w: int,
        poly_key: str,
        pts_list: list[list[int]],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, tuple[float, float], float]:
        channel_key = "second" if poly_key == "second_channel" else "third"
        arc = parseSavedChannelArcZones(channel_key, self._channel_angles, self._arc_params)
        if arc is not None and arc.outer_radius > arc.inner_radius > 0:
            segment_count = 96
            outer = np.array([
                [
                    int(round(arc.center[0] + arc.outer_radius * np.cos((2 * np.pi * i) / segment_count))),
                    int(round(arc.center[1] + arc.outer_radius * np.sin((2 * np.pi * i) / segment_count))),
                ]
                for i in range(segment_count)
            ], dtype=np.int32)
            inner = np.array([
                [
                    int(round(arc.center[0] + arc.inner_radius * np.cos((2 * np.pi * i) / segment_count))),
                    int(round(arc.center[1] + arc.inner_radius * np.sin((2 * np.pi * i) / segment_count))),
                ]
                for i in range(segment_count)
            ], dtype=np.int32)
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
            for q in range(CHANNEL_SECTION_COUNT):
                if q in ex_sections:
                    fill = (0, 80, 255)
                elif q in dz_sections:
                    fill = (0, 200, 80)
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
            annotated = cv2.addWeighted(overlay, 0.36, annotated, 0.64, 0)

            # draw all 64 section boundary lines
            dim_color = tuple(int(c * 0.7) for c in color)
            for q in range(CHANNEL_SECTION_COUNT):
                angle_rad = np.radians(r1_angle + q * CHANNEL_SECTION_DEG)
                ex = int(cx + disp_r * np.cos(angle_rad))
                ey = int(cy + disp_r * np.sin(angle_rad))
                cv2.line(annotated, (cx, cy), (ex, ey), dim_color, 1)

            # label each section at 70% radius
            for q in range(CHANNEL_SECTION_COUNT):
                angle_rad = np.radians(r1_angle + q * CHANNEL_SECTION_DEG + CHANNEL_SECTION_DEG / 2.0)
                lx = int(cx + disp_r * 0.7 * np.cos(angle_rad))
                ly = int(cy + disp_r * 0.7 * np.sin(angle_rad))
                cv2.putText(annotated, str(q), (lx - 6, ly + 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 0, 0), 2)
                cv2.putText(annotated, str(q), (lx - 6, ly + 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1)

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

    def _scaleForFrame(self, frame: np.ndarray):
        """Compute scale factors from saved polygon resolution to actual frame size."""
        h, w = frame.shape[:2]
        src_w, src_h = self._saved_resolution
        return w / src_w, h / src_h

    def _scaledChannelMask(self, h, w, poly_key, pts_list, sx, sy):
        """Like _channelMask but scales coordinates from saved resolution to frame size."""
        channel_key = "second" if poly_key == "second_channel" else "third"
        arc = parseSavedChannelArcZones(channel_key, self._channel_angles, self._arc_params)
        if arc is not None and arc.outer_radius > arc.inner_radius > 0:
            cx = arc.center[0] * sx
            cy = arc.center[1] * sy
            r_scale = (sx + sy) / 2.0
            outer_r = arc.outer_radius * r_scale
            inner_r = arc.inner_radius * r_scale
            segment_count = 96
            outer = np.array([
                [int(round(cx + outer_r * np.cos((2 * np.pi * i) / segment_count))),
                 int(round(cy + outer_r * np.sin((2 * np.pi * i) / segment_count)))]
                for i in range(segment_count)
            ], dtype=np.int32)
            inner = np.array([
                [int(round(cx + inner_r * np.cos((2 * np.pi * i) / segment_count))),
                 int(round(cy + inner_r * np.sin((2 * np.pi * i) / segment_count)))]
                for i in range(segment_count)
            ], dtype=np.int32)
            mask = np.zeros((h, w), dtype=np.uint8)
            cv2.fillPoly(mask, [outer], 255)
            cv2.fillPoly(mask, [inner], 0)
            return mask, outer, inner, (cx, cy), outer_r

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

        poly_key: 'second_channel', 'third_channel', or 'carousel'
        """
        sx, sy = self._scaleForFrame(frame)

        if poly_key == "carousel":
            annotated = frame.copy()
            carousel_pts = self._polygons.get("carousel")
            if carousel_pts and len(carousel_pts) >= 3:
                pts = np.array(carousel_pts, dtype=np.float64)
                pts[:, 0] *= sx
                pts[:, 1] *= sy
                pts = pts.astype(np.int32)
                color = CHANNEL_COLORS[RegionName.CAROUSEL_PLATFORM]
                cv2.polylines(annotated, [pts], isClosed=True, color=color, thickness=2)
            return annotated

        region_name = RegionName.CHANNEL_2 if poly_key == "second_channel" else RegionName.CHANNEL_3
        label = "Ch2" if poly_key == "second_channel" else "Ch3"
        angle_key = "second" if poly_key == "second_channel" else "third"
        channel_id = 2 if poly_key == "second_channel" else 3

        pts_list = self._polygons.get(poly_key)
        if not pts_list or len(pts_list) < 3:
            return frame.copy()

        annotated = frame.copy()
        dz_sections, ex_sections = zoneSectionsForChannel(
            channel_id,
            float(self._channel_angles.get(angle_key, 0.0)),
            parseSavedChannelArcZones(angle_key, self._channel_angles, self._arc_params),
        )
        ch_mask, pts, inner_pts, center, disp_r = self._scaledChannelMask(
            annotated.shape[0], annotated.shape[1], poly_key, pts_list, sx, sy,
        )
        color = CHANNEL_COLORS[region_name]
        cv2.polylines(annotated, [pts], isClosed=True, color=color, thickness=2)
        if inner_pts is not None and len(inner_pts) >= 3:
            cv2.polylines(annotated, [inner_pts], isClosed=True, color=color, thickness=2)

        cx, cy = int(center[0]), int(center[1])
        disp_r = int(disp_r)
        r1_angle = self._channel_angles.get(angle_key, 0.0)

        overlay = annotated.copy()
        for q in range(CHANNEL_SECTION_COUNT):
            if q in ex_sections:
                fill = (0, 80, 255)
            elif q in dz_sections:
                fill = (0, 200, 80)
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
        annotated = cv2.addWeighted(overlay, 0.36, annotated, 0.64, 0)

        dim_color = tuple(int(c * 0.7) for c in color)
        for q in range(CHANNEL_SECTION_COUNT):
            angle_rad = np.radians(r1_angle + q * CHANNEL_SECTION_DEG)
            ex = int(cx + disp_r * np.cos(angle_rad))
            ey = int(cy + disp_r * np.sin(angle_rad))
            cv2.line(annotated, (cx, cy), (ex, ey), dim_color, 1)

        for q in range(CHANNEL_SECTION_COUNT):
            angle_rad = np.radians(r1_angle + q * CHANNEL_SECTION_DEG + CHANNEL_SECTION_DEG / 2.0)
            lx = int(cx + disp_r * 0.7 * np.cos(angle_rad))
            ly = int(cy + disp_r * 0.7 * np.sin(angle_rad))
            cv2.putText(annotated, str(q), (lx - 6, ly + 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 0, 0), 2)
            cv2.putText(annotated, str(q), (lx - 6, ly + 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1)

        cv2.putText(annotated, label, (cx - 20, cy - disp_r - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        return annotated
