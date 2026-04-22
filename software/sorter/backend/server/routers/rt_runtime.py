"""rt-runtime status + lifecycle endpoints.

Exposes `/api/rt/status` which surfaces the RtRuntimeHandle's perception
runner roster, per-runner metadata, and any roles that were skipped at
bootstrap (e.g. because a camera config was missing). Used by the UI +
operators to verify that `/api/{scope}/detect/current` will actually hit
a live runner before clicking "Test Current Frame".
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from fastapi import APIRouter

from server import shared_state


router = APIRouter()


def _runner_entry(runner: Any) -> Dict[str, Any]:
    """Describe a single PerceptionRunner for the status payload."""
    pipeline = getattr(runner, "_pipeline", None)
    feed = getattr(pipeline, "feed", None) if pipeline is not None else None
    zone = getattr(pipeline, "zone", None) if pipeline is not None else None
    detector = getattr(pipeline, "detector", None) if pipeline is not None else None
    feed_id = getattr(feed, "feed_id", None)

    # Zone kind — keep it to a short tag so the UI doesn't need to import
    # the contract types.
    zone_kind: str | None = None
    if zone is not None:
        zone_kind = type(zone).__name__.replace("Zone", "").lower() or None

    # Latency since last frame — best-effort. CameraFeed doesn't expose a
    # direct "age" but the feed lock is cheap; avoid grabbing it if the
    # feed has no latest() helper.
    last_frame_age_ms: float | None = None
    latest_fn = getattr(feed, "latest", None) if feed is not None else None
    if callable(latest_fn):
        try:
            frame = latest_fn()
        except Exception:
            frame = None
        if frame is not None:
            monotonic_ts = getattr(frame, "monotonic_ts", None)
            if isinstance(monotonic_ts, (int, float)):
                last_frame_age_ms = max(0.0, (time.monotonic() - float(monotonic_ts)) * 1000.0)

    return {
        "feed_id": feed_id,
        "detector_slug": getattr(detector, "key", None),
        "zone_kind": zone_kind,
        "running": bool(getattr(runner, "_running", False)),
        "last_frame_age_ms": last_frame_age_ms,
    }


@router.get("/api/rt/status")
def get_rt_status() -> Dict[str, Any]:
    """Describe the currently-active rt runtime handle.

    Returned shape::

        {
          "rt_handle_ready": bool,
          "runners": [ {feed_id, detector_slug, zone_kind, running,
                         last_frame_age_ms}, ... ],
          "skipped_roles": [ {role, reason}, ... ]
        }

    Never 500s — missing state simply produces an empty rosters.
    """
    handle = shared_state.rt_handle
    if handle is None:
        return {
            "rt_handle_ready": False,
            "runners": [],
            "skipped_roles": [],
        }
    runners_out: List[Dict[str, Any]] = []
    for runner in getattr(handle, "perception_runners", []) or []:
        try:
            runners_out.append(_runner_entry(runner))
        except Exception:
            # One broken runner must not tank the endpoint.
            runners_out.append({
                "feed_id": None,
                "detector_slug": None,
                "zone_kind": None,
                "running": False,
                "last_frame_age_ms": None,
            })
    skipped = getattr(handle, "skipped_roles", []) or []
    return {
        "rt_handle_ready": True,
        "started": bool(getattr(handle, "started", False)),
        "paused": bool(getattr(handle, "paused", False)),
        "runners": runners_out,
        "skipped_roles": list(skipped),
    }


__all__ = ["router"]
