from __future__ import annotations

import logging
from typing import Any

from rt.contracts.events import Event
from rt.contracts.tracking import Track
from rt.events.topics import RUNTIME_HANDOFF_BURST

from ._ring_tracks import track_angle_deg


class HandoffDiagnostics:
    """Small rolling diagnostics buffer for C-channel burst investigations."""

    def __init__(
        self,
        *,
        runtime_id: str,
        feed_id: str | None,
        logger: logging.Logger,
        window_s: float = 1.25,
        threshold: int = 3,
        cooldown_s: float = 3.0,
        max_arrivals: int = 16,
        max_moves: int = 16,
        max_anomalies: int = 8,
    ) -> None:
        self.runtime_id = runtime_id
        self.feed_id = feed_id
        self.logger = logger
        self.window_s = max(0.1, float(window_s))
        self.threshold = max(2, int(threshold))
        self.cooldown_s = max(0.1, float(cooldown_s))
        self.max_arrivals = max(4, int(max_arrivals))
        self.max_moves = max(4, int(max_moves))
        self.max_anomalies = max(1, int(max_anomalies))
        self._recent_arrivals: list[dict[str, Any]] = []
        self._recent_moves: list[dict[str, Any]] = []
        self._anomalies: list[dict[str, Any]] = []
        self._last_anomaly_at: float = -999999.0

    def record_move(self, *, now_mono: float, **payload: Any) -> dict[str, Any]:
        event = {
            "ts_mono": round(float(now_mono), 3),
            "runtime_id": self.runtime_id,
            "feed_id": self.feed_id,
            **_compact_mapping(payload),
        }
        self._recent_moves.append(event)
        del self._recent_moves[:-self.max_moves]
        return event

    def record_arrivals(
        self,
        *,
        now_mono: float,
        arrivals: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not arrivals:
            return None
        ts_mono = float(now_mono)
        for arrival in arrivals:
            self._recent_arrivals.append(
                {
                    "ts_mono": round(ts_mono, 3),
                    "runtime_id": self.runtime_id,
                    "feed_id": self.feed_id,
                    **_compact_mapping(arrival),
                }
            )
        self._prune_arrivals(ts_mono)
        if len(self._recent_arrivals) < self.threshold:
            return None
        if (ts_mono - self._last_anomaly_at) < self.cooldown_s:
            return None
        anomaly = {
            "kind": "dropzone_arrival_burst",
            "ts_mono": round(ts_mono, 3),
            "runtime_id": self.runtime_id,
            "feed_id": self.feed_id,
            "window_s": self.window_s,
            "threshold": self.threshold,
            "arrival_count_window": len(self._recent_arrivals),
            "arrivals": list(self._recent_arrivals),
            "recent_moves": list(self._recent_moves[-8:]),
            "context": _compact_mapping(context or {}),
        }
        self._anomalies.append(anomaly)
        del self._anomalies[:-self.max_anomalies]
        self._last_anomaly_at = ts_mono
        self.logger.warning(
            "%s: dropzone arrival burst detected count=%s window=%.2fs context=%s",
            self.runtime_id.upper(),
            len(self._recent_arrivals),
            self.window_s,
            anomaly["context"],
        )
        return anomaly

    def snapshot(self) -> dict[str, Any]:
        return {
            "window_s": self.window_s,
            "threshold": self.threshold,
            "recent_arrivals": list(self._recent_arrivals),
            "recent_moves": list(self._recent_moves),
            "anomalies": list(self._anomalies),
        }

    def reset(self) -> None:
        self._recent_arrivals.clear()
        self._recent_moves.clear()
        self._anomalies.clear()
        self._last_anomaly_at = -999999.0

    def _prune_arrivals(self, now_mono: float) -> None:
        cutoff = float(now_mono) - self.window_s
        self._recent_arrivals = [
            event
            for event in self._recent_arrivals
            if float(event.get("ts_mono") or 0.0) >= cutoff
        ][-self.max_arrivals :]


def record_ring_handoff_move(
    runtime: Any,
    *,
    now_mono: float,
    source: str,
    mode: str,
    repeat_count: int,
    commit_to_downstream: bool,
    track: Track | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": source,
        "mode": mode,
        "repeat_count": int(repeat_count),
        "commit_to_downstream": bool(commit_to_downstream),
        "piece_count": int(runtime._piece_count),
        "visible_track_count": int(runtime._visible_track_count),
        "pending_downstream_claims": len(runtime._pending_downstream_claims),
        "upstream_taken": int(runtime._upstream_slot.taken()),
        "downstream_taken": int(runtime._downstream_slot.taken()),
    }
    if track is not None:
        payload.update({
            "track_global_id": track.global_id,
            "track_angle_deg": track_angle_deg(track),
        })
    return runtime._handoff_diagnostics.record_move(now_mono=now_mono, **payload)


def record_ring_arrival_burst(
    runtime: Any,
    arrivals: list[dict[str, Any]],
    now_mono: float,
) -> None:
    anomaly = runtime._handoff_diagnostics.record_arrivals(
        now_mono=now_mono,
        arrivals=arrivals,
        context={
            "piece_count": runtime._piece_count,
            "visible_track_count": runtime._visible_track_count,
            "pending_track_count": runtime._pending_track_count,
            "upstream_taken": runtime._upstream_slot.taken(),
            "downstream_taken": runtime._downstream_slot.taken(),
            "pending_downstream_claims": len(runtime._pending_downstream_claims),
        },
    )
    if anomaly is not None:
        publish_ring_handoff_burst(runtime, anomaly, now_mono)


def publish_ring_handoff_burst(
    runtime: Any,
    anomaly: dict[str, Any],
    now_mono: float,
) -> None:
    if runtime._bus is None:
        return
    try:
        runtime._bus.publish(
            Event(
                topic=RUNTIME_HANDOFF_BURST,
                payload=anomaly,
                source=runtime.runtime_id,
                ts_mono=float(now_mono),
            )
        )
    except Exception:
        runtime._logger.exception(
            "Runtime%s: handoff-burst publish failed",
            str(runtime.runtime_id).upper(),
        )


def _compact_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, bool) or value is None or isinstance(value, str):
            compact[key] = value
        elif isinstance(value, int):
            compact[key] = value
        elif isinstance(value, float):
            compact[key] = round(value, 3)
        elif isinstance(value, (list, tuple)):
            compact[key] = [
                _compact_value(item) for item in list(value)[:12]
            ]
        elif isinstance(value, dict):
            compact[key] = _compact_mapping(value)
        else:
            compact[key] = str(value)
    return compact


def _compact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _compact_mapping(value)
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, (bool, int, str)) or value is None:
        return value
    return str(value)


__all__ = [
    "HandoffDiagnostics",
    "publish_ring_handoff_burst",
    "record_ring_arrival_burst",
    "record_ring_handoff_move",
]
