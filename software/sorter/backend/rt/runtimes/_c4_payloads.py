from __future__ import annotations

import math
from typing import Any

from rt.contracts.classification import ClassifierResult
from rt.contracts.tracking import Track
from rt.events.topics import PIECE_TRANSIT_LINKED
from rt.perception.track_policy import admission_basis
from rt.pieces.identity import tracklet_payload


class C4Payloads:
    """Build C4 dossier, transit, classification, and handoff payloads."""

    def __init__(self, runtime: Any) -> None:
        self._rt = runtime

    def tracklet_payload_for_gid(self, gid: int) -> dict[str, Any]:
        rt = self._rt
        return tracklet_payload(
            feed_id=rt.feed_id or "c4_feed",
            tracker_key=rt._tracker_key,
            tracker_epoch=rt._tracker_epoch,
            raw_track_id=int(gid),
        )

    def dossier_tracklet_payload(self, dossier: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "feed_id": dossier.feed_id,
            "tracker_key": dossier.tracker_key,
            "tracker_epoch": dossier.tracker_epoch,
            "raw_track_id": dossier.raw_track_id,
        }
        if dossier.tracklet_id:
            payload["tracklet_id"] = dossier.tracklet_id
            payload["current_tracklet_id"] = dossier.tracklet_id
        return payload

    def dossier_event_payload(
        self,
        dossier: Any,
        *,
        zone_state: str | None = None,
        center_deg: float | None = None,
        lost_at: float | None = None,
        include_exit: bool = False,
    ) -> dict[str, Any]:
        rt = self._rt
        payload = {
            "piece_uuid": dossier.piece_uuid,
            "tracked_global_id": dossier.global_id,
            **self.dossier_tracklet_payload(dossier),
        }
        if zone_state is not None:
            payload["classification_channel_zone_state"] = zone_state
        if center_deg is not None:
            payload["classification_channel_zone_center_deg"] = center_deg
        if lost_at is not None:
            payload["classification_channel_lost_at"] = lost_at
        if include_exit:
            payload["classification_channel_exit_deg"] = rt._exit_angle_deg
        return payload

    def dossier_last_angle_deg(self, dossier: Any) -> float:
        value = dossier.extras.get("last_angle_deg")
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
        return float(dossier.angle_at_intake_deg)

    def extras_for_registration(
        self,
        track: Track,
        *,
        recovered: bool,
        transit: Any | None,
    ) -> dict[str, Any]:
        rt = self._rt
        extras: dict[str, Any] = {}
        if transit is not None and isinstance(transit.payload.get("extras"), dict):
            extras.update(transit.payload["extras"])
        extras.update(
            {
                "recovered": recovered,
                "admission_basis": admission_basis(
                    track,
                    min_hits=rt._reconcile_min_hit_count,
                    min_score=rt._reconcile_min_score,
                    min_age_s=rt._reconcile_min_age_s if recovered else 0.0,
                ),
            }
        )
        if transit is not None:
            extras.update(self.transit_payload(transit))
        return extras

    @staticmethod
    def result_from_transit(transit: Any | None) -> ClassifierResult | None:
        if transit is None:
            return None
        result = transit.payload.get("dossier_result")
        return result if isinstance(result, ClassifierResult) else None

    @staticmethod
    def classified_ts_from_transit(transit: Any | None) -> float | None:
        if transit is None:
            return None
        value = transit.payload.get("classified_ts")
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return float(value)
        return None

    @staticmethod
    def reject_reason_from_transit(transit: Any | None) -> str | None:
        if transit is None:
            return None
        value = transit.payload.get("reject_reason")
        return value if isinstance(value, str) and value.strip() else None

    @staticmethod
    def transit_payload(transit: Any | None) -> dict[str, Any]:
        if transit is None:
            return {}
        return {
            "track_stitched": True,
            "transit_id": transit.transit_id,
            "transit_relation": transit.relation,
            "transit_source_runtime": transit.source_runtime,
            "transit_source_feed": transit.source_feed,
            "transit_source_global_id": transit.source_global_id,
            "previous_tracked_global_id": transit.payload.get(
                "previous_tracked_global_id",
                transit.source_global_id,
            ),
            "previous_tracklet_id": transit.payload.get("previous_tracklet_id"),
        }

    @staticmethod
    def classification_payload(
        result: ClassifierResult | None,
    ) -> dict[str, Any]:
        if result is None:
            return {}
        meta = result.meta if isinstance(result.meta, dict) else {}
        return {
            "part_id": result.part_id,
            "part_name": meta.get("name"),
            "color_id": result.color_id,
            "color_name": meta.get("color_name"),
            "part_category": result.category,
            "category": result.category,
            "confidence": result.confidence,
            "algorithm": result.algorithm,
            "latency_ms": result.latency_ms,
            "brickognize_preview_url": meta.get("preview_url") or meta.get("img_url"),
        }

    @staticmethod
    def classification_status(
        result: ClassifierResult | None,
        *,
        missing: str = "pending",
    ) -> str:
        return missing if result is None else ("classified" if result.part_id else "unknown")

    def publish_transit_link(
        self,
        piece_uuid: str,
        tracked_global_id: int,
        transit: Any,
        *,
        now_mono: float,
    ) -> None:
        rt = self._rt
        rt._publish(
            PIECE_TRANSIT_LINKED,
            {
                "piece_uuid": piece_uuid,
                "tracked_global_id": tracked_global_id,
                **self.tracklet_payload_for_gid(tracked_global_id),
                "stage": "registered",
                **self.transit_payload(transit),
            },
            now_mono,
        )

    def handoff_dossier_payload(self, dossier: Any) -> dict[str, Any]:
        rt = self._rt
        result = dossier.result
        return {
            **self.dossier_event_payload(dossier),
            "angle_at_intake_deg": dossier.angle_at_intake_deg,
            "intake_ts_mono": dossier.intake_ts,
            "classified_ts_mono": dossier.classified_ts,
            **self.classification_payload(result),
            "classification_channel_exit_deg": rt._exit_angle_deg,
            "classification_status": self.classification_status(
                result,
                missing="unknown",
            ),
            **dossier.extras,
        }


__all__ = ["C4Payloads"]
