"""Build a ``PerceptionRunner`` against the live (legacy) services.

Bridge-imports: this module intentionally reaches into ``backend.vision.*``
(via duck-typed ``camera_service`` + ``vision_manager`` handles passed in
from ``main.py``). That dependency is **temporary** — Phase 3+ will
migrate zone + resolution to an rt-owned config, at which point this
bootstrap goes away in favor of the regular ``build_pipeline_from_config``
path wired from ``SorterConfig``.

The function is designed to never raise back into caller code:

* missing zone / missing camera / missing polygon → returns ``None``
* construction failures in detector/tracker/filters → logged, returns ``None``

Callers (``main.py``) wrap each invocation in a try/except anyway; the
``None`` short-circuit lets a clean startup continue without the shadow
runner for a role that cannot be served yet.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import rt.perception  # noqa: F401 - register detectors/trackers/filters
from rt.config.schema import FilterConfig, PipelineConfig
from rt.contracts.events import Event, EventBus
from rt.contracts.feed import PolygonZone, RectZone, Zone
from rt.events.topics import PERCEPTION_TRACKS, RT_SHADOW_IOU
from rt.perception.detectors.hive_onnx import default_hive_detector_slug
from rt.perception.feeds import CameraFeed
from rt.perception.pipeline import build_pipeline_from_config
from rt.perception.pipeline_runner import PerceptionRunner

from .iou import RollingIouTracker


_LOG = logging.getLogger(__name__)

# Shadow runner cadence. 5 Hz keeps GPU pressure tiny compared to the live
# pipeline while still giving the UI visible updates.
_DEFAULT_PERIOD_MS = 200
_DEFAULT_FPS_TARGET = 5.0

# Map rt-side short role slugs ("c2") to legacy-camera-service role names.
# Keep this single source of truth aligned with `role_aliases.py`.
_ROLE_TO_LEGACY_CAMERA: dict[str, str] = {
    "c1": "feeder",  # single-camera layouts use "feeder" as the C1 source
    "c2": "c_channel_2",
    "c3": "c_channel_3",
    "c4": "carousel",
}

# Which ``FeedPurpose`` literal to tag a shadow feed with. Keep aligned with
# ``rt.contracts.feed.FeedPurpose``.
_ROLE_TO_PURPOSE: dict[str, str] = {
    "c1": "aux",
    "c2": "c2_feed",
    "c3": "c3_feed",
    "c4": "c4_feed",
}


def _resolve_camera_role(role: str) -> str:
    return _ROLE_TO_LEGACY_CAMERA.get(role, role)


def _resolve_purpose(role: str) -> str:
    return _ROLE_TO_PURPOSE.get(role, "aux")


def _load_zone_from_vision_manager(
    role: str, camera_service: Any, vision_manager: Any
) -> Zone | None:
    """Return a :class:`Zone` covering the role's channel polygon.

    Strategy mirrors :meth:`VisionManager._channelInfoForRole`:

    1. Ask the camera service for the latest frame on the role so we know
       the live resolution.
    2. Call ``vision_manager._channelPolygonKeyForRole(legacy_role)`` to
       get the polygon key ("second_channel" etc.).
    3. Call ``vision_manager._loadSavedPolygon(key, w, h)`` to read + scale
       the saved polygon to the live resolution.

    Falls back to a full-frame :class:`RectZone` if the vision manager
    cannot provide a polygon yet. Returns ``None`` if we don't even have
    a frame — the caller treats that as "shadow not ready for this role".
    """
    legacy_role = _resolve_camera_role(role)

    # Need a live frame to learn (w, h). Prefer the capture thread on the
    # camera service (used by vision_manager itself), fall back to the
    # feed's latest get_frame().
    h: int | None = None
    w: int | None = None

    get_capture = getattr(camera_service, "get_capture_thread_for_role", None)
    if callable(get_capture):
        try:
            capture = get_capture(legacy_role)
        except Exception:
            capture = None
        frame = getattr(capture, "latest_frame", None) if capture is not None else None
        raw = getattr(frame, "raw", None)
        if raw is not None and hasattr(raw, "shape"):
            h, w = int(raw.shape[0]), int(raw.shape[1])

    if h is None or w is None:
        get_feed = getattr(camera_service, "get_feed", None)
        if callable(get_feed):
            try:
                feed = get_feed(legacy_role)
            except Exception:
                feed = None
            get_frame = getattr(feed, "get_frame", None) if feed is not None else None
            if callable(get_frame):
                try:
                    cframe = get_frame(annotated=False)
                except TypeError:
                    cframe = get_frame()
                except Exception:
                    cframe = None
                raw = getattr(cframe, "raw", None) if cframe is not None else None
                if raw is not None and hasattr(raw, "shape"):
                    h, w = int(raw.shape[0]), int(raw.shape[1])

    if h is None or w is None:
        _LOG.warning(
            "rt shadow[%s]: no live frame yet on legacy role %r — zone unavailable",
            role,
            legacy_role,
        )
        return None

    polygon_key_fn = getattr(vision_manager, "_channelPolygonKeyForRole", None)
    load_polygon_fn = getattr(vision_manager, "_loadSavedPolygon", None)

    polygon_key: str | None = None
    if callable(polygon_key_fn):
        try:
            polygon_key = polygon_key_fn(legacy_role)
        except Exception:
            polygon_key = None

    polygon = None
    if polygon_key and callable(load_polygon_fn):
        try:
            polygon = load_polygon_fn(polygon_key, w, h)
        except Exception:
            polygon = None

    if polygon is not None and len(polygon) >= 3:
        vertices = tuple((int(p[0]), int(p[1])) for p in polygon)
        return PolygonZone(vertices=vertices)

    _LOG.warning(
        "rt shadow[%s]: no polygon for %r — falling back to full-frame RectZone %dx%d",
        role,
        polygon_key,
        w,
        h,
    )
    return RectZone(x=0, y=0, w=w, h=h)


def _legacy_tracks_for_role(vision_manager: Any, role: str) -> list[Any]:
    legacy_role = _resolve_camera_role(role)
    getter = getattr(vision_manager, "getFeederTracks", None)
    if not callable(getter):
        return []
    try:
        return list(getter(legacy_role))
    except Exception:
        return []


def _wire_iou_subscriber(
    event_bus: EventBus,
    vision_manager: Any,
    role: str,
    iou_tracker: RollingIouTracker,
    source_name: str,
    feed_id: str,
) -> None:
    """Attach the IoU tracker to the perception-tracks topic.

    We can't read the `TrackBatch` directly from the event payload (it only
    carries counts), so we read the latest batch off the runner via the
    closure. For simplicity we re-read legacy tracks from the VisionManager
    here — that is the only bridge-read this component performs beyond the
    zone bootstrap.

    The subscriber filters incoming events by ``feed_id`` so that parallel
    shadow runners (e.g. ``c2`` and ``c3`` on the same EventBus) don't
    cross-pollute each other's IoU samples.
    """

    # The subscriber stores a handle on the perception runner so it can
    # pull the full TrackBatch at dispatch time. We set it after runner
    # construction via ``attach_runner`` below.
    state: dict[str, Any] = {"runner": None}

    def _on_tracks(event: Event) -> None:
        # Only respond to events from *our* feed — otherwise a c3 shadow
        # runner's publish would nudge the c2 tracker and vice versa.
        event_feed_id = event.payload.get("feed_id") if event.payload else None
        if event_feed_id != feed_id:
            return
        runner: PerceptionRunner | None = state.get("runner")
        if runner is None:
            return
        batch = runner.latest_tracks()
        if batch is None:
            return
        new_tracks = list(batch.tracks)
        legacy_tracks = _legacy_tracks_for_role(vision_manager, role)
        iou_tracker.record(new_tracks, legacy_tracks, timestamp=time.monotonic())
        try:
            iou_tracker.publish_event(
                event_bus,
                topic=RT_SHADOW_IOU,
                role=role,
                source=source_name,
            )
        except Exception:
            _LOG.exception("rt shadow[%s]: failed to publish IoU event", role)

    event_bus.subscribe(PERCEPTION_TRACKS, _on_tracks)
    # Expose the state dict so the caller can attach the runner handle.
    iou_tracker._shadow_subscriber_state = state  # type: ignore[attr-defined]


def build_shadow_runner_from_live(
    role: str,
    camera_service: Any,
    vision_manager: Any,
    event_bus: EventBus,
    *,
    detector_slug: str | None = None,
    iou_tracker: RollingIouTracker | None = None,
    period_ms: int = _DEFAULT_PERIOD_MS,
    fps_target: float = _DEFAULT_FPS_TARGET,
) -> PerceptionRunner | None:
    """Construct a :class:`PerceptionRunner` against the legacy services.

    Returns ``None`` when the role is not yet ready to shadow (missing
    camera, missing zone/polygon, missing detector). Never raises.
    """
    zone = _load_zone_from_vision_manager(role, camera_service, vision_manager)
    if zone is None:
        _LOG.warning("rt shadow[%s]: no zone — skipping", role)
        return None

    feed_id = f"shadow_{role}"
    purpose = _resolve_purpose(role)
    camera_id = _resolve_camera_role(role)

    try:
        feed = CameraFeed(
            feed_id=feed_id,
            purpose=purpose,  # type: ignore[arg-type]
            camera_id=camera_id,
            camera_service=camera_service,
            zone=zone,
            fps_target=fps_target,
        )
    except Exception:
        _LOG.exception("rt shadow[%s]: failed to build CameraFeed", role)
        return None

    effective_slug = detector_slug or default_hive_detector_slug()
    pipeline_config = PipelineConfig(
        feed_id=feed_id,
        detector={
            "key": effective_slug,
            "params": {"conf_threshold": 0.25, "iou_threshold": 0.45},
        },
        tracker={"key": "polar", "params": {}},
        filters=[
            FilterConfig(key="size", params={"min_area_px": 400}),
            FilterConfig(key="ghost", params={"confirmed_real_only": True}),
        ],
    )

    try:
        pipeline = build_pipeline_from_config(pipeline_config, feed, zone)
    except Exception:
        _LOG.exception(
            "rt shadow[%s]: pipeline construction failed (detector=%s)",
            role,
            effective_slug,
        )
        return None

    runner_name = f"RtShadowRunner[{role}]"
    runner = PerceptionRunner(
        pipeline=pipeline,
        period_ms=period_ms,
        event_bus=event_bus,
        name=runner_name,
    )

    if iou_tracker is not None:
        try:
            _wire_iou_subscriber(
                event_bus,
                vision_manager,
                role,
                iou_tracker,
                runner_name,
                feed_id,
            )
            # Attach the runner to the subscriber state so it can fetch batches.
            state = getattr(iou_tracker, "_shadow_subscriber_state", None)
            if isinstance(state, dict):
                state["runner"] = runner
        except Exception:
            _LOG.exception("rt shadow[%s]: IoU subscriber wiring failed", role)

    _LOG.info(
        "rt shadow[%s]: runner built feed=%s zone=%s detector=%s",
        role,
        feed_id,
        type(zone).__name__,
        effective_slug,
    )
    return runner


__all__ = ["build_shadow_runner_from_live"]
