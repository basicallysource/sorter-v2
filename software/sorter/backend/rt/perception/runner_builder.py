"""Build perception runners (+ zones) for a given rt role.

One shared code path for two callers:

- ``rt.bootstrap.build_rt_runtime`` builds a runner per role during cold
  boot.
- ``RtRuntimeHandle.rebuild_runner_for_role`` rebuilds a single runner
  after the user changes the detector slug or channel polygon without
  tearing down the whole rt graph.

Both take ``(role, camera_service, event_bus, logger)`` and get back
``(runner, zone, reason)``. Reason is an empty string on success or a
short slug on failure (``"no_camera_config"``, ``"pipeline_build_failed"``,
…) so skipped runners stay observable via ``/api/rt/status``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from rt.config.channels import (
    ROLE_TO_LEGACY_CAMERA,
    channel_polygon_key_for_role,
    configured_resolution_for_role,
    load_arc_tracker_params,
    load_saved_polygon,
)
from rt.config.schema import PipelineConfig
from rt.contracts.feed import PolygonZone, RectZone, Zone
from rt.events.bus import InProcessEventBus
from rt.perception.detectors.hive_onnx import default_hive_detector_slug
from rt.perception.feeds import CameraFeed
from rt.perception.pipeline import build_pipeline_from_config
from rt.perception.pipeline_runner import PerceptionRunner
from rt.contracts.registry import TRACKERS


# Each rt-role (c2/c3/c4) maps onto one of the Svelte settings scopes so
# the user-configured detector slug can be read from the right detection-
# config blob at bootstrap and on rebuild.
_ROLE_TO_UI_SCOPE: dict[str, str] = {
    "c2": "feeder",
    "c3": "feeder",
    "c4": "classification_channel",
}


# Names used by the Svelte feeder dropdown to key into
# ``getFeederDetectionConfig()["algorithm_by_role"]``. The two feeder
# channels and the classification C-channel all share the feeder config.
_ROLE_TO_FEEDER_ROLE_KEY: dict[str, str] = {
    "c2": "c_channel_2",
    "c3": "c_channel_3",
    "c4": "classification_channel",
}


_FIRST_TOUCH_POLYGON_APRON_PX = 48
_PERCEPTION_PERIOD_MS = 100
_DEFAULT_PRIMARY_TRACKER_KEY = "turntable_groundplane"
_DEFAULT_SHADOW_TRACKER_KEY = "polar"


def _disabled_tracker_value(raw: str) -> bool:
    return raw.lower() in {"", "0", "false", "no", "none", "off", "disabled"}


def primary_tracker_key() -> str:
    """Return the tracker key used by the production perception pipeline."""
    raw = os.environ.get("RT_PRIMARY_TRACKER_KEY", _DEFAULT_PRIMARY_TRACKER_KEY)
    key = str(raw or "").strip()
    if _disabled_tracker_value(key):
        return _DEFAULT_PRIMARY_TRACKER_KEY
    return key


def shadow_tracker_key(primary_key: str | None = None) -> str | None:
    """Return the configured shadow tracker key, or ``None`` when disabled."""
    if "RT_SHADOW_TRACKER_KEY" in os.environ:
        raw = os.environ.get("RT_SHADOW_TRACKER_KEY", "")
    elif primary_key and primary_key != _DEFAULT_PRIMARY_TRACKER_KEY:
        raw = _DEFAULT_PRIMARY_TRACKER_KEY
    else:
        raw = _DEFAULT_SHADOW_TRACKER_KEY
    key = str(raw or "").strip()
    if _disabled_tracker_value(key):
        return None
    if primary_key and key == primary_key:
        return None
    return key


def detector_slug_for_role(role: str, logger: logging.Logger) -> str:
    """Return the detector slug the user has configured for ``role``.

    Falls back to the per-scope default (see
    ``default_detector_slug_for_ui_scope``) when no saved preference
    exists, and finally to the global Hive default when even that yields
    ``None``.
    """
    from rt.contracts.registry import (
        DETECTORS,
        default_detector_slug_for_ui_scope,
    )

    ui_scope = _ROLE_TO_UI_SCOPE.get(role, "feeder")
    feeder_role_key = _ROLE_TO_FEEDER_ROLE_KEY.get(role)
    saved_slug: str | None = None
    try:
        if ui_scope == "feeder" or feeder_role_key == "classification_channel":
            from server.detection_config.common import get_feeder_detection_config

            cfg = get_feeder_detection_config()
            if isinstance(cfg, dict):
                by_role = cfg.get("algorithm_by_role")
                if isinstance(by_role, dict) and feeder_role_key:
                    candidate = by_role.get(feeder_role_key)
                    if isinstance(candidate, str) and candidate:
                        saved_slug = candidate
                if not saved_slug:
                    candidate = cfg.get("algorithm")
                    if isinstance(candidate, str) and candidate:
                        saved_slug = candidate
        elif ui_scope == "classification_channel":
            from server.detection_config.common import get_classification_channel_detection_config

            cfg = get_classification_channel_detection_config()
            if isinstance(cfg, dict):
                candidate = cfg.get("algorithm")
                if isinstance(candidate, str) and candidate:
                    saved_slug = candidate
    except Exception:
        logger.debug(
            "runner_builder[%s]: detector slug lookup raised — using default",
            role,
            exc_info=True,
        )
        saved_slug = None

    if saved_slug and saved_slug in DETECTORS.keys():
        return saved_slug

    preferred = default_detector_slug_for_ui_scope(ui_scope)
    if preferred:
        return preferred
    # Final fallback — keeps C2/C3 working even on first boot when the
    # dropdown has never been touched.
    return default_hive_detector_slug()


def load_zone_for_role(
    role: str,
    camera_service: Any,
    logger: logging.Logger,
) -> tuple[Zone | None, str]:
    """Build the perception zone for ``role`` without waiting for a live frame.

    Returns ``(zone, reason)``. ``zone`` is ``None`` on failure; ``reason``
    is an empty string on success or a short slug describing the skip
    cause (``"no_camera_config"``, ``"no_polygon_and_no_resolution"``, …).

    The polygon lookup uses the saved ``resolution`` metadata from the
    channel_polygons blob, and the target frame resolution is read from
    the camera device config. Both are available at bootstrap time
    independent of frame delivery, so C4 and every other channel load
    their zones as soon as the camera_service is built — no boot-race.
    """
    legacy_role = ROLE_TO_LEGACY_CAMERA.get(role, role)

    # Target frame resolution — pulled from the camera device config, no frame.
    target_res = configured_resolution_for_role(camera_service, legacy_role)
    target_w, target_h = target_res if target_res is not None else (None, None)

    polygon_key = channel_polygon_key_for_role(legacy_role)
    polygon = None
    if polygon_key and target_w is not None and target_h is not None:
        try:
            polygon = load_saved_polygon(polygon_key, target_w, target_h)
        except Exception:
            polygon = None

    if polygon is not None and len(polygon) >= 3:
        vertices = tuple((int(p[0]), int(p[1])) for p in polygon)
        return PolygonZone(vertices=vertices), ""

    if target_w is None or target_h is None:
        logger.warning(
            "runner_builder[%s]: no camera config resolution for %r — cannot build zone",
            role, legacy_role,
        )
        return None, "no_camera_config"

    logger.warning(
        "runner_builder[%s]: no saved polygon for %r — using full-frame %dx%d",
        role, polygon_key, target_w, target_h,
    )
    return RectZone(x=0, y=0, w=target_w, h=target_h), ""


def build_perception_runner_for_role(
    role: str,
    *,
    camera_service: Any,
    event_bus: InProcessEventBus,
    logger: logging.Logger,
) -> tuple[PerceptionRunner | None, Zone | None, str]:
    """Build the perception runner (+ zone) for ``role``.

    Returns ``(runner, zone, reason)``. ``runner`` is ``None`` on failure;
    ``reason`` is an empty string on success or a slug-style label when
    the runner could not be built. The returned runner has NOT been
    started.
    """
    zone, reason = load_zone_for_role(role, camera_service, logger)
    if zone is None:
        return None, None, reason or "no_zone"

    feed_id = f"{role}_feed"
    camera_id = ROLE_TO_LEGACY_CAMERA.get(role, role)
    purpose = {"c2": "c2_feed", "c3": "c3_feed", "c4": "c4_feed"}.get(role)
    if purpose is None:
        logger.error(
            "runner_builder[%s]: unknown role — cannot build perception", role
        )
        return None, zone, "unknown_role"
    try:
        feed = CameraFeed(
            feed_id=feed_id,
            purpose=purpose,  # type: ignore[arg-type]
            camera_id=camera_id,
            camera_service=camera_service,
            zone=zone,
            fps_target=10.0 if role != "c4" else 8.0,
        )
    except Exception:
        logger.exception("runner_builder[%s]: CameraFeed build failed", role)
        return None, zone, "camera_feed_build_failed"

    detector_slug = detector_slug_for_role(role, logger)
    tracker_params: dict[str, Any] = {}
    target_res = configured_resolution_for_role(camera_service, camera_id)
    if target_res is not None:
        tracker_params = load_arc_tracker_params(
            role,
            target_w=int(target_res[0]),
            target_h=int(target_res[1]),
        )
    tracker_key = primary_tracker_key()
    pipeline_config = PipelineConfig(
        feed_id=feed_id,
        detector={
            "key": detector_slug,
            "params": {
                "conf_threshold": 0.25,
                "iou_threshold": 0.45,
                "polygon_apron_px": _FIRST_TOUCH_POLYGON_APRON_PX,
            },
        },
        tracker={"key": tracker_key, "params": tracker_params},
        filters=[{"key": "ghost", "params": {}}],
    )
    try:
        pipeline = build_pipeline_from_config(pipeline_config, feed, zone)
    except Exception:
        logger.exception(
            "runner_builder[%s]: pipeline build failed (detector=%s, tracker=%s)",
            role,
            detector_slug,
            tracker_key,
        )
        return None, zone, "pipeline_build_failed"
    shadow_key = shadow_tracker_key(tracker_key)
    shadow_tracker = None
    if shadow_key is not None:
        try:
            shadow_tracker = TRACKERS.create(shadow_key, **dict(tracker_params))
        except Exception:
            logger.exception(
                "runner_builder[%s]: shadow tracker build failed (tracker=%s)",
                role,
                shadow_key,
            )
            shadow_key = None
    runner = PerceptionRunner(
        pipeline=pipeline,
        period_ms=_PERCEPTION_PERIOD_MS,
        event_bus=event_bus,
        name=f"RtPerception[{role}]",
        shadow_tracker=shadow_tracker,
        shadow_tracker_key=shadow_key,
    )
    logger.info(
        "runner_builder[%s]: perception runner ready "
        "(feed=%s, detector=%s, tracker=%s, shadow=%s)",
        role,
        feed_id,
        detector_slug,
        tracker_key,
        shadow_key or "disabled",
    )
    return runner, zone, ""


__all__ = [
    "build_perception_runner_for_role",
    "detector_slug_for_role",
    "load_zone_for_role",
    "primary_tracker_key",
    "shadow_tracker_key",
]
