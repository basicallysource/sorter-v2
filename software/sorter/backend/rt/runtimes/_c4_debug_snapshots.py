from __future__ import annotations

import math
import time
from typing import Any


class C4DebugSnapshots:
    """Build read-only C4 operator/debug snapshots."""

    def __init__(self, runtime: Any) -> None:
        self._rt = runtime

    def dossier_debug_payload(
        self,
        dossier: Any,
        *,
        detail_ts_mono: float | None = None,
    ) -> dict[str, Any]:
        rt = self._rt
        zone = rt._zone_manager.zone_for(dossier.piece_uuid)
        angle = float(zone.center_deg) if zone is not None else None
        payload: dict[str, Any] = {
            "piece_uuid": dossier.piece_uuid,
            "global_id": dossier.global_id,
            "tracklet_id": dossier.tracklet_id,
            "tracker_key": dossier.tracker_key,
            "tracker_epoch": dossier.tracker_epoch,
            "angle_deg": angle,
            "classify_delta_deg": (
                _wrap_deg(angle - rt._classify_angle_deg)
                if angle is not None
                else None
            ),
            "exit_delta_deg": (
                _wrap_deg(angle - rt._exit_angle_deg) if angle is not None else None
            ),
            "handoff_requested": bool(dossier.handoff_requested),
            "distributor_ready": bool(dossier.distributor_ready),
            "eject_enqueued": bool(dossier.eject_enqueued),
            "eject_committed": bool(dossier.eject_committed),
        }
        if detail_ts_mono is None:
            payload.update(
                {
                    "has_result": dossier.result is not None,
                    "future_pending": dossier.classify_future is not None,
                    "recovered": bool(dossier.extras.get("recovered")),
                }
            )
            return payload

        ts = float(detail_ts_mono)
        result = dossier.result
        payload.update(
            {
                "raw_track_id": dossier.raw_track_id,
                "intake_age_s": ts - dossier.intake_ts,
                "angle_at_intake_deg": dossier.angle_at_intake_deg,
                "last_seen_age_s": ts - dossier.last_seen_mono,
                "classified_age_s": (
                    ts - dossier.classified_ts
                    if dossier.classified_ts is not None
                    else None
                ),
                "classify_future_pending": dossier.classify_future is not None,
                "result_part_id": getattr(result, "part_id", None) if result else None,
                "result_category": (
                    getattr(result, "category", None) if result else None
                ),
                "reject_reason": dossier.reject_reason,
                "last_handoff_attempt_age_s": (
                    ts - dossier.last_handoff_attempt_at
                    if dossier.last_handoff_attempt_at
                    else None
                ),
                "extras": dict(dossier.extras),
            }
        )
        return payload

    def debug_snapshot(self) -> dict[str, Any]:
        rt = self._rt
        frame_raw = getattr(rt._latest_frame, "raw", None)
        frame_shape = list(frame_raw.shape[:2]) if hasattr(frame_raw, "shape") else None
        dossier_preview = [
            self.dossier_debug_payload(dossier)
            for dossier in list(rt._pieces.values())[:5]
        ]
        admission_state = rt._admission_state_snapshot()
        admission_decision = rt._admission.can_admit(
            inbound_piece_hint={},
            runtime_state=admission_state,
        )
        return {
            "fsm_state": rt._fsm.value,
            "startup_purge_armed": bool(rt._startup_purge_state.armed),
            "startup_purge_prime_moves": int(rt._startup_purge_state.prime_moves),
            "startup_purge_commit_piece_uuid": rt._startup_purge_state.commit_piece_uuid,
            "raw_detection_count": int(rt._raw_detection_count),
            "transit_link_count": int(rt._transit_link_count),
            "tracker_identity": {
                "feed_id": rt.feed_id,
                "tracker_key": rt._tracker_key,
                "tracker_epoch": rt._tracker_epoch,
            },
            "transit_candidates": (
                rt._track_transit.snapshot(time.monotonic())
                if rt._track_transit is not None
                else []
            ),
            "dossier_count": len(rt._pieces),
            "track_to_piece_count": len(rt._track_to_piece),
            "zone_count": rt._zone_manager.zone_count(),
            "recently_delivered_suppressed": {
                "pieces": len(rt._recently_delivered_piece_until),
                "tracks": len(rt._recently_delivered_track_until),
            },
            "admission_debug": {
                "allowed": bool(admission_decision.allowed),
                "reason": admission_decision.reason,
                "state": admission_state,
            },
            "hw_busy": bool(rt._hw.busy()),
            "hw_pending": int(rt._hw.pending()),
            "hw_worker": rt._hw_status_snapshot(),
            "angles": {
                "intake_deg": rt._zone_manager.intake_angle_deg,
                "classify_deg": rt._classify_angle_deg,
                "classify_pretrigger_exit_lead_deg": (
                    rt._classify_pretrigger_exit_lead_deg
                ),
                "handoff_request_horizon_deg": rt._handoff_request_horizon_deg,
                "exit_deg": rt._exit_angle_deg,
                "exit_approach_angle_deg": rt._exit_approach_angle_deg,
                "drop_deg": rt._zone_manager.drop_angle_deg,
                "tolerance_deg": rt._angle_tol_deg,
            },
            "latest_frame": {
                "present": rt._latest_frame is not None,
                "raw_shape_hw": frame_shape,
                "frame_seq": getattr(rt._latest_frame, "frame_seq", None),
            },
            "classify_debug": {
                "counts": dict(sorted(rt._classify_debug_counts.items())),
                "last_skip": rt._last_classify_skip,
            },
            "handoff_debug": {
                "port_wired": rt._handoff is not None,
                "counts": dict(sorted(rt._handoff_debug_counts.items())),
                "last_skip": rt._last_handoff_skip,
            },
            "idle_jog": {
                "enabled": bool(rt._idle_jog_enabled),
                "step_deg": float(rt._idle_jog_step_deg),
                "cooldown_s": float(rt._idle_jog_cooldown_s),
                "next_at_mono": float(rt._next_idle_jog_at),
                "last_at_mono": rt._last_idle_jog_at,
                "count": int(rt._idle_jog_count),
            },
            "transport_velocity": rt._transport_velocity.snapshot.as_dict(),
            "handoff_burst_diagnostics": rt._handoff_diagnostics.snapshot(),
            "transport_unjam": {
                "enabled": bool(rt._unjam_enabled),
                "stall_s": float(rt._unjam_stall_s),
                "min_progress_deg": float(rt._unjam_min_progress_deg),
                "cooldown_s": float(rt._unjam_cooldown_s),
                "reverse_deg": float(rt._unjam_reverse_deg),
                "forward_deg": float(rt._unjam_forward_deg),
                "watch_started_at_mono": rt._transport_progress_started_at,
                "last_progress_deg": rt._last_transport_progress_deg,
                "next_at_mono": float(rt._next_unjam_at),
                "last_at_mono": rt._last_unjam_at,
                "count": int(rt._unjam_count),
            },
            "dossier_preview": dossier_preview,
        }

    def inspect_snapshot(self, *, now_mono: float | None = None) -> dict[str, Any]:
        rt = self._rt
        ts = time.monotonic() if now_mono is None else float(now_mono)
        dossiers = [
            self.dossier_debug_payload(dossier, detail_ts_mono=ts)
            for dossier in rt._pieces.values()
        ]
        dossiers.sort(
            key=lambda d: (
                d.get("exit_delta_deg") is None,
                abs(d.get("exit_delta_deg") or 1e9),
            )
        )
        bank_view: list[dict[str, Any]] = []
        for tr in rt._bank.tracks():
            bank_view.append(
                {
                    "piece_uuid": tr.piece_uuid,
                    "lifecycle_state": tr.lifecycle_state.value,
                    "motion_mode": tr.motion_mode.value,
                    "angle_deg": tr.angle_deg,
                    "angle_sigma_deg": tr.angle_sigma_deg,
                    "class_label": tr.class_label,
                    "class_confidence": tr.class_confidence,
                    "raw_track_aliases": sorted(tr.raw_track_aliases),
                    "detection_observations": tr.detection_observations,
                    "confirmed_real_observations": tr.confirmed_real_observations,
                    "last_observed_age_s": ts - tr.last_observed_t,
                    "handoff_requested": bool(tr.handoff_requested),
                    "distributor_ready": bool(tr.distributor_ready),
                    "eject_enqueued": bool(tr.eject_enqueued),
                    "eject_committed": bool(tr.eject_committed),
                    "reject_reason": tr.reject_reason,
                    "extent_deg": math.degrees(float(tr.extent_rad)),
                }
            )
        pending_landings_view: list[dict[str, Any]] = []
        for pending in rt._bank.pending_landings():
            pending_landings_view.append(
                {
                    "lease_id": pending.lease_id,
                    "predicted_arrival_in_s": max(
                        0.0, pending.predicted_arrival_t - ts
                    ),
                    "predicted_landing_deg": math.degrees(
                        pending.predicted_landing_a
                    ),
                    "expires_in_s": max(0.0, pending.expires_at - ts),
                    "requested_by": pending.requested_by,
                }
            )
        return {
            "fsm_state": rt._fsm.value,
            "dossier_count": len(rt._pieces),
            "dossiers": dossiers,
            "bank_track_count": len(rt._bank),
            "bank_tracks": bank_view,
            "bank_pending_landings": pending_landings_view,
            "carousel_angle_deg": math.degrees(rt._carousel_angle_rad),
            "track_to_piece": dict(rt._track_to_piece),
            "next_accept_in_s": max(0.0, rt._next_accept_at - ts),
            "angles": {
                "intake_deg": rt._zone_manager.intake_angle_deg,
                "classify_deg": rt._classify_angle_deg,
                "exit_deg": rt._exit_angle_deg,
                "exit_approach_angle_deg": rt._exit_approach_angle_deg,
                "drop_deg": rt._zone_manager.drop_angle_deg,
            },
        }


def _wrap_deg(angle: float) -> float:
    return (float(angle) + 180.0) % 360.0 - 180.0


__all__ = ["C4DebugSnapshots"]
