from __future__ import annotations

import time
from typing import Any

from rt.contracts.tracking import Track
from rt.events.topics import PIECE_REGISTERED


TRACKLET_TRANSIT_TTL_S = 1.25
DELIVERED_TRACK_SUPPRESS_S = 15.0


class C4PieceLifecycle:
    """Own C4 piece finalization, loss transit, and delivered suppression."""

    def __init__(self, runtime: Any) -> None:
        self._rt = runtime

    def on_piece_delivered(self, piece_uuid: str, now_mono: float) -> None:
        self.finalize_piece(piece_uuid, now_mono=now_mono, arm_cooldown=True)

    def on_piece_rejected(self, piece_uuid: str, reason: str) -> None:
        rt = self._rt
        rt._logger.info("RuntimeC4: piece %s rejected (reason=%s)", piece_uuid, reason)
        dossier = rt._pieces.get(piece_uuid)
        if dossier is not None:
            dossier.reject_reason = reason
        self.finalize_piece(piece_uuid, now_mono=None, arm_cooldown=False)

    def finalize_piece(
        self,
        piece_uuid: str,
        *,
        now_mono: float | None,
        arm_cooldown: bool,
        abort_handoff: bool = False,
        abort_reason: str = "handoff_aborted",
    ) -> None:
        rt = self._rt
        state = type(rt._fsm)
        dossier = rt._pieces.pop(piece_uuid, None)
        rt._bank_finalize(piece_uuid, ejected=bool(arm_cooldown))
        if dossier is not None and arm_cooldown and now_mono is not None:
            self.remember_delivered_piece(dossier, now_mono)
        if dossier is not None and abort_reason == "track_lost":
            self.park_lost_piece_transit(dossier, now_mono=now_mono)
            self.publish_piece_lost(dossier, now_mono=now_mono)
        if dossier is not None:
            rt._track_to_piece = {
                gid: mapped_piece_uuid
                for gid, mapped_piece_uuid in rt._track_to_piece.items()
                if mapped_piece_uuid != dossier.piece_uuid
            }
        rt._zone_manager.remove_zone(piece_uuid)
        if abort_handoff and dossier is not None and dossier.handoff_requested:
            port = rt._handoff
            if port is not None:
                ts = time.monotonic() if now_mono is None else now_mono
                try:
                    port.handoff_abort(
                        piece_uuid,
                        reason=abort_reason,
                        now_mono=ts,
                    )
                except Exception:
                    rt._logger.exception(
                        "RuntimeC4: distributor handoff_abort raised for piece=%s",
                        piece_uuid,
                    )
        rt._downstream_slot.release()
        if arm_cooldown and now_mono is not None:
            rt._next_accept_at = now_mono + rt._post_commit_cooldown_s
        if rt._fsm is state.DROP_COMMIT:
            rt._fsm = state.RUNNING
            rt._set_state(rt._fsm.value)

    def publish_piece_lost(
        self,
        dossier: Any,
        *,
        now_mono: float | None,
    ) -> None:
        rt = self._rt
        now_wall = time.time()
        last_angle_deg = rt._payloads.dossier_last_angle_deg(dossier)
        zone_payload = rt._payloads.dossier_event_payload(
            dossier,
            zone_state="lost",
            center_deg=last_angle_deg,
            lost_at=now_wall,
        )
        rt._publish(
            PIECE_REGISTERED,
            {
                **zone_payload,
                "stage": "registered",
                "classification_status": rt._payloads.classification_status(
                    dossier.result
                ),
                "updated_at": now_wall,
                "dossier": {
                    **zone_payload,
                    "classification_channel_exit_deg": rt._exit_angle_deg,
                },
            },
            now_mono if now_mono is not None else time.monotonic(),
        )

    def park_lost_piece_transit(
        self,
        dossier: Any,
        *,
        now_mono: float | None,
    ) -> None:
        rt = self._rt
        registry = rt._track_transit
        if registry is None:
            return
        now = time.monotonic() if now_mono is None else float(now_mono)
        zone = rt._zone_manager.zone_for(dossier.piece_uuid)
        source_angle_deg = (
            float(zone.center_deg)
            if zone is not None
            else rt._payloads.dossier_last_angle_deg(dossier)
        )
        registry.begin(
            source_runtime=rt.runtime_id,
            source_feed=rt.feed_id,
            source_global_id=dossier.global_id,
            target_runtime=rt.runtime_id,
            now_mono=now,
            ttl_s=TRACKLET_TRANSIT_TTL_S,
            piece_uuid=dossier.piece_uuid,
            source_angle_deg=source_angle_deg,
            relation="track_split",
            payload={
                "previous_tracked_global_id": dossier.global_id,
                "previous_tracklet_id": dossier.tracklet_id,
                **rt._payloads.dossier_tracklet_payload(dossier),
                "dossier_result": dossier.result,
                "classified_ts": dossier.classified_ts,
                "reject_reason": dossier.reject_reason,
                "extras": dict(dossier.extras),
            },
            source_embedding=dossier.appearance_embedding,
        )

    def remember_delivered_piece(self, dossier: Any, now_mono: float) -> None:
        rt = self._rt
        until = float(now_mono) + DELIVERED_TRACK_SUPPRESS_S
        rt._recently_delivered_piece_until[dossier.piece_uuid] = until
        if dossier.raw_track_id is not None:
            rt._recently_delivered_track_until[int(dossier.raw_track_id)] = until
        elif dossier.global_id is not None:
            rt._recently_delivered_track_until[int(dossier.global_id)] = until

    def is_recently_delivered_track(self, track: Track, now_mono: float) -> bool:
        rt = self._rt
        piece_uuid = track.piece_uuid
        if (
            isinstance(piece_uuid, str)
            and rt._recently_delivered_piece_until.get(piece_uuid, 0.0) > now_mono
        ):
            return True
        if track.global_id is None:
            return False
        try:
            gid = int(track.global_id)
        except (TypeError, ValueError):
            return False
        return rt._recently_delivered_track_until.get(gid, 0.0) > now_mono

    def sweep_recently_delivered(self, now_mono: float) -> None:
        rt = self._rt
        rt._recently_delivered_piece_until = {
            piece_uuid: until
            for piece_uuid, until in rt._recently_delivered_piece_until.items()
            if until > now_mono
        }
        rt._recently_delivered_track_until = {
            global_id: until
            for global_id, until in rt._recently_delivered_track_until.items()
            if until > now_mono
        }


__all__ = ["C4PieceLifecycle"]
