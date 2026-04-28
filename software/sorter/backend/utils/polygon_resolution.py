from __future__ import annotations

from typing import Any


_DEFAULT_FALLBACK_RESOLUTION: tuple[float, float] = (1920.0, 1080.0)


def _coerce_resolution(raw: Any) -> tuple[float, float] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None
    try:
        width = float(raw[0])
        height = float(raw[1])
    except (TypeError, ValueError):
        return None
    if width <= 0.0 or height <= 0.0:
        return None
    return (width, height)


def saved_polygon_resolution(
    saved: Any,
    *,
    channel_key: str | None = None,
    fallback: tuple[float, float] = _DEFAULT_FALLBACK_RESOLUTION,
) -> tuple[float, float]:
    """Resolve the source resolution for a saved polygon blob.

    The zone editor stores per-channel resolutions next to the geometry in
    ``arc_params[...]`` / ``quad_params[...]``. Older payloads may carry only a
    top-level ``resolution`` field; some historical shapes also used a
    ``channels[...]`` table. Prefer geometry-local metadata first so
    heterogeneous camera resolutions do not contaminate each other.
    """

    if not isinstance(saved, dict):
        return fallback

    if channel_key:
        for group in ("arc_params", "quad_params", "channels"):
            entries = saved.get(group)
            if not isinstance(entries, dict):
                continue
            entry = entries.get(channel_key)
            if not isinstance(entry, dict):
                continue
            coerced = _coerce_resolution(entry.get("resolution"))
            if coerced is not None:
                return coerced

    coerced = _coerce_resolution(saved.get("resolution"))
    if coerced is not None:
        return coerced
    return fallback


__all__ = ["saved_polygon_resolution"]
