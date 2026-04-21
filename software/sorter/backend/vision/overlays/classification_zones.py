from __future__ import annotations

from typing import Callable

import cv2
import numpy as np

from .scaling import overlay_scale_for_frame, scaled_px


class ClassificationChannelZoneOverlay:
    category = "detections"

    def __init__(self, get_payload: Callable[[], dict[str, object]]):
        self._get_payload = get_payload

    def annotate(self, frame: np.ndarray) -> np.ndarray:
        payload = self._get_payload() or {}
        geometry = payload.get("geometry")
        zones = payload.get("zones")
        if not isinstance(geometry, dict) or not isinstance(zones, list):
            return frame

        try:
            center = (
                int(round(float(geometry["center_x"]))),
                int(round(float(geometry["center_y"]))),
            )
            r_inner = int(round(float(geometry["r_inner"])))
            r_outer = int(round(float(geometry["r_outer"])))
        except Exception:
            return frame

        if r_outer <= r_inner:
            return frame

        annotated = frame.copy()
        scale = overlay_scale_for_frame(frame)
        # The classification pieces travel close to the outer rim. Drawing the
        # reservation wedges across the whole platter makes the overlay look
        # chaotic and much harder to read, so we deliberately compress it into
        # a slim visual lane near the real travel path.
        lane_width = max(48, int(round((r_outer - r_inner) * 0.23)))
        annulus_outer = max(r_inner + lane_width + 8, r_outer - 6)
        annulus_inner = max(0, annulus_outer - lane_width)
        rim_outer = annulus_outer
        rim_inner = max(annulus_inner, rim_outer - max(18, int((annulus_outer - annulus_inner) * 0.18)))

        for zone in zones:
            if not isinstance(zone, dict):
                continue
            try:
                center_deg = float(zone["center_deg"])
                body_half_width_deg = float(zone["body_half_width_deg"])
            except Exception:
                continue

            stale = bool(zone.get("stale"))
            hard_collision = bool(zone.get("hard_collision"))
            status = str(zone.get("classification_status") or "")
            size_class = str(zone.get("size_class") or "?")

            colors = self._colors_for_zone(
                status=status,
                stale=stale,
                hard_collision=hard_collision,
            )
            body_start = center_deg - body_half_width_deg
            body_end = center_deg + body_half_width_deg

            # Per-piece polar markers: only show the body as a thin outline.
            # soft_guard / hard_guard fills+outlines were visually noisy and
            # not actionable at a glance — numbers remain available via the
            # debug endpoint.
            self._draw_sector_outline(
                annotated,
                center=center,
                annulus_inner=annulus_inner,
                annulus_outer=annulus_outer,
                start_deg=body_start,
                end_deg=body_end,
                color=colors["body_line"],
                thickness=scaled_px(1, scale),
            )
            if hard_collision or status in {"pending", "classifying", "unknown", "not_found", "multi_drop_fail"}:
                self._draw_label(
                    annotated,
                    center=center,
                    annulus_inner=annulus_inner,
                    annulus_outer=annulus_outer,
                    angle_deg=center_deg,
                    text=self._zone_label(
                        size_class=size_class,
                        status=status,
                        hard_collision=hard_collision,
                    ),
                    color=colors["body_line"],
                    scale=scale,
                )

        return annotated

    def _zone_label(
        self,
        *,
        size_class: str,
        status: str,
        hard_collision: bool,
    ) -> str:
        if hard_collision:
            return f"{size_class}!"
        if status in {"pending", "classifying"}:
            return f"{size_class}?"
        if status in {"unknown", "not_found", "multi_drop_fail"}:
            return f"{size_class}x"
        return size_class

    def _colors_for_zone(
        self,
        *,
        status: str,
        stale: bool,
        hard_collision: bool,
    ) -> dict[str, tuple[int, int, int]]:
        if hard_collision:
            return {
                "hard_fill": (40, 60, 255),
                "soft_fill": (0, 110, 255),
                "body_fill": (0, 0, 255),
                "hard_line": (40, 60, 255),
                "soft_line": (0, 110, 255),
                "body_line": (0, 0, 255),
            }
        if stale:
            return {
                "hard_fill": (120, 120, 120),
                "soft_fill": (145, 145, 145),
                "body_fill": (170, 170, 170),
                "hard_line": (110, 110, 110),
                "soft_line": (140, 140, 140),
                "body_line": (180, 180, 180),
            }
        if status in {"unknown", "not_found", "multi_drop_fail"}:
            return {
                "hard_fill": (0, 120, 255),
                "soft_fill": (0, 180, 255),
                "body_fill": (0, 210, 255),
                "hard_line": (0, 120, 255),
                "soft_line": (0, 180, 255),
                "body_line": (0, 220, 255),
            }
        return {
            "hard_fill": (0, 70, 255),
            "soft_fill": (0, 200, 255),
            "body_fill": (80, 220, 120),
            "hard_line": (0, 90, 255),
            "soft_line": (0, 210, 255),
            "body_line": (90, 235, 130),
        }

    def _draw_label(
        self,
        frame: np.ndarray,
        *,
        center: tuple[int, int],
        annulus_inner: int,
        annulus_outer: int,
        angle_deg: float,
        text: str,
        color: tuple[int, int, int],
        scale: float,
    ) -> None:
        radius = int(round((annulus_inner + annulus_outer) / 2.0))
        point = self._point_on_circle(center, radius, angle_deg)
        offset = scaled_px(4, scale)
        cv2.putText(
            frame,
            text,
            (point[0] + offset, point[1] - offset),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42 * scale,
            color,
            scaled_px(1, scale),
            cv2.LINE_AA,
        )

    def _blend_annulus_sector(
        self,
        frame: np.ndarray,
        *,
        center: tuple[int, int],
        annulus_inner: int,
        annulus_outer: int,
        start_deg: float,
        end_deg: float,
        color: tuple[int, int, int],
        alpha: float,
    ) -> None:
        polygons = self._annulus_sector_polygons(
            center=center,
            annulus_inner=annulus_inner,
            annulus_outer=annulus_outer,
            start_deg=start_deg,
            end_deg=end_deg,
        )
        if not polygons:
            return
        overlay = frame.copy()
        cv2.fillPoly(overlay, polygons, color)
        cv2.addWeighted(overlay, float(alpha), frame, 1.0 - float(alpha), 0.0, frame)

    def _draw_sector_outline(
        self,
        frame: np.ndarray,
        *,
        center: tuple[int, int],
        annulus_inner: int,
        annulus_outer: int,
        start_deg: float,
        end_deg: float,
        color: tuple[int, int, int],
        thickness: int,
    ) -> None:
        for seg_start, seg_end in self._segments_for_arc(start_deg, end_deg):
            cv2.ellipse(
                frame,
                center,
                (annulus_outer, annulus_outer),
                0.0,
                seg_start,
                seg_end,
                color,
                thickness,
                cv2.LINE_AA,
            )
            cv2.ellipse(
                frame,
                center,
                (annulus_inner, annulus_inner),
                0.0,
                seg_start,
                seg_end,
                color,
                thickness,
                cv2.LINE_AA,
            )

        start_outer = self._point_on_circle(center, annulus_outer, start_deg)
        start_inner = self._point_on_circle(center, annulus_inner, start_deg)
        end_outer = self._point_on_circle(center, annulus_outer, end_deg)
        end_inner = self._point_on_circle(center, annulus_inner, end_deg)
        cv2.line(frame, start_inner, start_outer, color, thickness, cv2.LINE_AA)
        cv2.line(frame, end_inner, end_outer, color, thickness, cv2.LINE_AA)

    def _annulus_sector_polygons(
        self,
        *,
        center: tuple[int, int],
        annulus_inner: int,
        annulus_outer: int,
        start_deg: float,
        end_deg: float,
    ) -> list[np.ndarray]:
        polygons: list[np.ndarray] = []
        for seg_start, seg_end in self._segments_for_arc(start_deg, end_deg):
            delta = max(1, int(round((seg_end - seg_start) / 18.0)))
            outer_arc = cv2.ellipse2Poly(
                center,
                (annulus_outer, annulus_outer),
                0,
                int(round(seg_start)),
                int(round(seg_end)),
                delta,
            )
            inner_arc = cv2.ellipse2Poly(
                center,
                (annulus_inner, annulus_inner),
                0,
                int(round(seg_start)),
                int(round(seg_end)),
                delta,
            )
            if outer_arc.size == 0 or inner_arc.size == 0:
                continue
            polygon = np.concatenate((outer_arc, inner_arc[::-1]), axis=0)
            polygons.append(np.asarray(polygon, dtype=np.int32))
        return polygons

    def _segments_for_arc(self, start_deg: float, end_deg: float) -> list[tuple[float, float]]:
        start = float(start_deg) % 360.0
        end = float(end_deg) % 360.0
        if start <= end:
            return [(start, end)]
        return [(start, 360.0), (0.0, end)]

    def _point_on_circle(
        self,
        center: tuple[int, int],
        radius: int,
        angle_deg: float,
    ) -> tuple[int, int]:
        angle_rad = np.deg2rad(float(angle_deg))
        return (
            int(round(center[0] + radius * np.cos(angle_rad))),
            int(round(center[1] + radius * np.sin(angle_rad))),
        )
