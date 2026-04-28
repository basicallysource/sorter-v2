from __future__ import annotations

import math
from typing import Any

from rt.contracts.tracking import Track
from rt.events.topics import RUNTIME_HANDOFF_BURST


class C4HandoffDebug:
    """Record C4 handoff move and burst diagnostics."""

    def __init__(self, runtime: Any) -> None:
        self._rt = runtime

    def record_dropzone_arrival(
        self,
        *,
        track: Track,
        dossier: Any,
        now_mono: float,
        release_upstream: bool,
        recovered: bool,
    ) -> None:
        rt = self._rt
        if not release_upstream:
            return
        anomaly = rt._handoff_diagnostics.record_arrivals(
            now_mono=now_mono,
            arrivals=[
                {
                    "piece_uuid": dossier.piece_uuid,
                    "global_id": dossier.global_id,
                    "track_id": track.track_id,
                    "angle_deg": self.track_angle_deg(track),
                    "release_upstream": bool(release_upstream),
                    "recovered": bool(recovered),
                    "transit_relation": dossier.extras.get("transit_relation"),
                    "transit_source_runtime": dossier.extras.get(
                        "transit_source_runtime"
                    ),
                    "score": float(track.score),
                    "hit_count": int(track.hit_count),
                    "confirmed_real": bool(track.confirmed_real),
                }
            ],
            context={
                "dossier_count": len(rt._pieces),
                "zone_count": rt._zone_manager.zone_count(),
                "raw_detection_count": rt._raw_detection_count,
                "upstream_taken": rt._upstream_slot.taken(),
                "downstream_taken": rt._downstream_slot.taken(),
            },
        )
        if anomaly is not None:
            self.publish_handoff_burst(anomaly, now_mono)

    def record_handoff_move(
        self,
        *,
        now_mono: float,
        source: str,
        step_deg: float | None,
        use_exit_approach: bool | None,
        track_count: int,
        dossier: Any | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rt = self._rt
        front = rt._dossiers_by_exit_distance()[0] if rt._pieces else None
        payload: dict[str, Any] = {
            "source": source,
            "step_deg": step_deg,
            "use_exit_approach": use_exit_approach,
            "track_count": int(track_count),
            "dossier_count": len(rt._pieces),
            "zone_count": rt._zone_manager.zone_count(),
            "upstream_taken": int(rt._upstream_slot.taken()),
            "downstream_taken": int(rt._downstream_slot.taken()),
        }
        if front is not None:
            payload.update(
                {
                    "front_piece_uuid": front.piece_uuid,
                    "front_global_id": front.global_id,
                    "front_exit_distance_deg": rt._dossier_exit_distance(front),
                    "front_has_result": front.result is not None,
                    "front_handoff_requested": bool(front.handoff_requested),
                    "front_distributor_ready": bool(front.distributor_ready),
                    "front_eject_enqueued": bool(front.eject_enqueued),
                    "front_eject_committed": bool(front.eject_committed),
                }
            )
        if dossier is not None:
            payload.update(
                {
                    "piece_uuid": dossier.piece_uuid,
                    "global_id": dossier.global_id,
                    "exit_distance_deg": rt._dossier_exit_distance(dossier),
                    "handoff_requested": dossier.handoff_requested,
                    "distributor_ready": dossier.distributor_ready,
                    "has_result": dossier.result is not None,
                }
            )
        if extra:
            payload.update(extra)
        return rt._handoff_diagnostics.record_move(
            now_mono=now_mono,
            **payload,
        )

    def publish_handoff_burst(
        self,
        anomaly: dict[str, Any],
        now_mono: float,
    ) -> None:
        self._rt._publish(RUNTIME_HANDOFF_BURST, anomaly, now_mono)

    @staticmethod
    def track_angle_deg(track: Track) -> float | None:
        if track.angle_rad is None:
            return None
        return math.degrees(float(track.angle_rad))


__all__ = ["C4HandoffDebug"]
