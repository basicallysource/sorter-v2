"""Facade over the in-flight ``RuntimeStatsCollector`` for transport routers.

Routers and the top-level API module must not reach into
``shared_state.gc_ref.runtime_stats`` directly — that is in-flight runtime
state owned by the rt graph. This module is the single named access point:
it resolves the current collector, tolerates the degraded/standby case
(``gc_ref is None`` or collector missing), and exposes the handful of
operations the HTTP surface actually needs.

Keep the surface narrow. New operations belong here when the runtime
objects legitimately own them; anything else is a smell that the data
should live in SQLite or the rt graph instead.
"""

from __future__ import annotations

from typing import Any, Optional

from server import shared_state


def _collector() -> Any | None:
    gc = shared_state.gc_ref
    if gc is None:
        return None
    return getattr(gc, "runtime_stats", None)


def clear_bin_contents(
    *,
    scope: str,
    layer_index: int | None = None,
    section_index: int | None = None,
    bin_index: int | None = None,
) -> None:
    """Clear tracked bin contents at the given scope.

    No-op when the collector is unavailable (standby mode, pre-init).
    """
    collector = _collector()
    if collector is None or not hasattr(collector, "clearBinContents"):
        return
    collector.clearBinContents(
        scope=scope,
        layer_index=layer_index,
        section_index=section_index,
        bin_index=bin_index,
    )


def bin_contents_snapshot() -> Optional[dict[str, Any]]:
    """Return the current in-flight bin-contents snapshot, or ``None`` when unavailable."""
    collector = _collector()
    if collector is None or not hasattr(collector, "binContentsSnapshot"):
        return None
    snapshot = collector.binContentsSnapshot()
    return snapshot if isinstance(snapshot, dict) else None


def servo_bus_offline_since_ts() -> float | None:
    """Return the timestamp when the servo bus went offline, or ``None`` when online/unknown."""
    collector = _collector()
    if collector is None:
        return None
    value = getattr(collector, "servo_bus_offline_since_ts", None)
    return value if isinstance(value, (int, float)) else None


def lookup_known_object(uuid: str) -> dict[str, Any] | None:
    """Resolve a known-object dossier from the in-process LRU, or ``None`` when missing."""
    collector = _collector()
    if collector is None or not hasattr(collector, "lookupKnownObject"):
        return None
    payload = collector.lookupKnownObject(uuid)
    return payload if isinstance(payload, dict) else None


def observe_known_object(obj: dict[str, Any]) -> None:
    """Feed a known-object/dossier update into the live runtime stats collector."""
    collector = _collector()
    if collector is None or not hasattr(collector, "observeKnownObject"):
        return
    collector.observeKnownObject(obj)


def _observe_known_object(
    collector: Any,
    obj: dict[str, Any],
    *,
    count_when_stopped: bool = False,
) -> None:
    observe = getattr(collector, "observeKnownObject", None)
    if not callable(observe):
        return
    try:
        observe(obj, count_when_stopped=count_when_stopped)
    except TypeError:
        observe(obj)


def _sync_recent_piece_dossiers(
    collector: Any,
    *,
    limit: int = 500,
    count_when_stopped: bool = False,
) -> None:
    observe = getattr(collector, "observeKnownObject", None)
    if not callable(observe):
        return
    try:
        from local_state import list_piece_dossiers

        dossiers = list_piece_dossiers(limit=limit, include_stubs=False)
    except Exception:
        return
    for obj in reversed(dossiers):
        if isinstance(obj, dict):
            _observe_known_object(
                collector,
                obj,
                count_when_stopped=count_when_stopped,
            )


def _snapshot_from_piece_dossiers() -> dict[str, Any] | None:
    try:
        from runtime_stats import RuntimeStatsCollector
    except Exception:
        return None
    collector = RuntimeStatsCollector()
    _sync_recent_piece_dossiers(collector, count_when_stopped=True)
    snap = collector.snapshot()
    return snap if isinstance(snap, dict) else None


def snapshot() -> dict[str, Any] | None:
    """Return a fresh live runtime-stats snapshot when the collector is available."""
    collector = _collector()
    if collector is None or not hasattr(collector, "snapshot"):
        return _snapshot_from_piece_dossiers()
    _sync_recent_piece_dossiers(collector, count_when_stopped=True)
    snap = collector.snapshot()
    return snap if isinstance(snap, dict) else None
