"""Zone factory: ZoneConfig -> concrete Zone instance."""

from __future__ import annotations

from typing import Any

from rt.config.schema import ZoneConfig
from rt.contracts.feed import PolarZone, PolygonZone, RectZone, Zone


def _build_rect(params: dict[str, Any]) -> RectZone:
    return RectZone(
        x=int(params["x"]),
        y=int(params["y"]),
        w=int(params["w"]),
        h=int(params["h"]),
    )


def _build_polygon(params: dict[str, Any]) -> PolygonZone:
    raw = params.get("vertices")
    if raw is None:
        raise ValueError("polygon zone requires 'vertices' list of (x, y) pairs")
    vertices = tuple((int(p[0]), int(p[1])) for p in raw)
    if len(vertices) < 3:
        raise ValueError(f"polygon zone needs at least 3 vertices, got {len(vertices)}")
    return PolygonZone(vertices=vertices)


def _build_polar(params: dict[str, Any]) -> PolarZone:
    center = params["center_xy"]
    return PolarZone(
        center_xy=(float(center[0]), float(center[1])),
        r_inner=float(params["r_inner"]),
        r_outer=float(params["r_outer"]),
        theta_start_rad=float(params["theta_start_rad"]),
        theta_end_rad=float(params["theta_end_rad"]),
    )


_BUILDERS = {
    "rect": _build_rect,
    "polygon": _build_polygon,
    "polar": _build_polar,
}


def build_zone(cfg: ZoneConfig) -> Zone:
    """Dispatch ZoneConfig.kind to the matching concrete Zone constructor."""
    try:
        builder = _BUILDERS[cfg.kind]
    except KeyError:
        raise ValueError(f"Unknown zone kind: {cfg.kind!r}") from None
    return builder(cfg.params)


__all__ = ["build_zone"]
