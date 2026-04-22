"""Shadow-mode: run the new rt/ perception pipeline side-by-side with the
legacy VisionManager against the same camera, for parity verification.

Entry points:

* :func:`parse_shadow_feeds_env` — ``RT_SHADOW_FEEDS`` env-var parser.
* :func:`build_shadow_runner_from_live` — factory that wires a
  :class:`~rt.perception.pipeline_runner.PerceptionRunner` against the
  live ``camera_service`` / ``vision_manager`` bridges.
* :class:`RollingIouTracker` — per-role IoU metric with a rolling window.
* :data:`router` — FastAPI router for the ``/api/rt/shadow`` endpoints.

Bridge-imports (into ``backend.vision`` + ``backend.server.shared_state``)
are intentional and live only on the boundaries; everything inside
``rt.shadow`` talks in rt contracts.
"""

from __future__ import annotations

from .api import router
from .bootstrap import build_shadow_runner_from_live
from .config import SHADOW_ROLE_ALLOWLIST, parse_shadow_feeds_env
from .iou import IouSample, RollingIouTracker, bbox_iou, compute_frame_iou


__all__ = [
    "IouSample",
    "RollingIouTracker",
    "SHADOW_ROLE_ALLOWLIST",
    "bbox_iou",
    "build_shadow_runner_from_live",
    "compute_frame_iou",
    "parse_shadow_feeds_env",
    "router",
]
