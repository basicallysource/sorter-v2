from __future__ import annotations

import math
from typing import Any, Callable

from rt.contracts.tracking import Track


SAMPLE_TRANSPORT_TARGET_INTERVAL_S = 0.25
SAMPLE_TRANSPORT_MAX_STEP_DEG = 45.0


class C4TransportController:
    """Own C4 transport, unjam, idle-jog, and sample-transport decisions."""

    def __init__(self, runtime: Any) -> None:
        self._rt = runtime

    def owned_track_angles(self, tracks: list[Track]) -> dict[int, float]:
        rt = self._rt
        angles: dict[int, float] = {}
        for track in tracks:
            if track.angle_rad is None or track.global_id is None:
                continue
            gid = int(track.global_id)
            if rt._piece_uuid_for_track(track) is None:
                continue
            angles[gid] = math.degrees(float(track.angle_rad))
        return angles

    def reset_progress_watch(self) -> None:
        rt = self._rt
        rt._transport_progress_started_at = None
        rt._transport_progress_baseline = {}
        rt._last_transport_progress_deg = None

    def waiting_on_ready_exit(self, tracks: list[Track]) -> bool:
        return self.exit_hold_reason(tracks) is not None

    def exit_hold_reason(self, tracks: list[Track]) -> str | None:
        rt = self._rt
        exit_track = rt._pick_exit_track(tracks)
        if exit_track is None or exit_track.global_id is None:
            exit_track = None
        if exit_track is not None:
            piece_uuid = rt._piece_uuid_for_track(exit_track)
            dossier = rt._pieces.get(piece_uuid) if piece_uuid is not None else None
            if dossier is not None:
                return "exit_piece_not_ready"
        for dossier in rt._dossiers_by_exit_distance():
            if dossier.result is None or not dossier.handoff_requested:
                continue
            if rt._handoff is not None:
                rt._sync_handoff_from_port(dossier)
            if not dossier.distributor_ready:
                return "waiting_distributor"
        hold_deg = max(float(rt._angle_tol_deg), float(rt._exit_approach_angle_deg))
        for dossier in rt._dossiers_by_exit_distance():
            distance = rt._dossier_exit_distance(dossier)
            if distance > hold_deg:
                continue
            if dossier.eject_enqueued:
                return "eject_in_flight"
            if dossier.result is None:
                return "exit_piece_unclassified"
            if rt._handoff is not None:
                rt._sync_handoff_from_port(dossier)
                if not dossier.handoff_requested:
                    return "waiting_distributor_request"
                if not dossier.distributor_ready:
                    return "waiting_distributor"
            return None
        return None

    def maybe_unjam_transport(self, tracks: list[Track], now_mono: float) -> bool:
        rt = self._rt
        state = type(rt._fsm)
        if not rt._unjam_enabled:
            self.reset_progress_watch()
            return False
        if not rt._pieces or not tracks:
            self.reset_progress_watch()
            return False
        if (
            rt._startup_purge_controller.pending()
            or rt._startup_purge_state.mode_active
        ):
            self.reset_progress_watch()
            return False
        if rt._fsm in (
            state.STARTUP_PURGE,
            state.DROP_COMMIT,
            state.EXIT_SHIMMY,
            state.TRANSPORT_UNJAM,
        ):
            return False
        if self.waiting_on_ready_exit(tracks):
            self.reset_progress_watch()
            return False

        angles = self.owned_track_angles(tracks)
        if not angles:
            self.reset_progress_watch()
            return False
        if not rt._transport_progress_baseline:
            rt._transport_progress_baseline = dict(angles)
            rt._transport_progress_started_at = now_mono
            rt._last_transport_progress_deg = 0.0
            return False

        common_ids = set(angles).intersection(rt._transport_progress_baseline)
        if not common_ids:
            rt._transport_progress_baseline = dict(angles)
            rt._transport_progress_started_at = now_mono
            rt._last_transport_progress_deg = 0.0
            return False

        progress = max(
            abs(_wrap_deg(angles[gid] - rt._transport_progress_baseline[gid]))
            for gid in common_ids
        )
        rt._last_transport_progress_deg = progress
        if progress >= rt._unjam_min_progress_deg:
            rt._transport_progress_baseline = dict(angles)
            rt._transport_progress_started_at = now_mono
            return False

        started_at = rt._transport_progress_started_at
        if started_at is None:
            rt._transport_progress_started_at = now_mono
            return False
        if (now_mono - started_at) < rt._unjam_stall_s:
            return False
        if now_mono < rt._next_unjam_at or rt._hw_busy_or_backlogged():
            return False

        reverse_deg = rt._unjam_reverse_deg
        forward_deg = rt._unjam_forward_deg

        def _do_unjam() -> None:
            try:
                rt._unjam_move(-reverse_deg)
                rt._unjam_move(forward_deg)
            except Exception:
                rt._logger.exception("RuntimeC4: transport unjam move raised")

        if rt._hw.enqueue(_do_unjam, label="c4_transport_unjam"):
            rt._next_unjam_at = now_mono + rt._unjam_cooldown_s
            rt._last_unjam_at = now_mono
            rt._unjam_count += 1
            rt._transport_progress_baseline = dict(angles)
            rt._transport_progress_started_at = now_mono
            rt._fsm = state.TRANSPORT_UNJAM
            rt._set_state(rt._fsm.value)
            return True
        return False

    def maybe_advance_transport(
        self,
        tracks: list[Track],
        now_mono: float,
        *,
        move_command: Callable[[float], bool] | None = None,
    ) -> bool:
        rt = self._rt
        state = type(rt._fsm)
        if not rt._pieces or not tracks:
            return False
        if rt._fsm in (
            state.DROP_COMMIT,
            state.EXIT_SHIMMY,
            state.TRANSPORT_UNJAM,
        ):
            return False
        if rt._hw_busy_or_backlogged() or now_mono < rt._next_transport_at:
            return False
        hold_reason = self.exit_hold_reason(tracks)
        if hold_reason is not None:
            rt._set_state("drop_commit", blocked_reason=hold_reason)
            return False

        use_exit_approach = move_command is None and (
            any(self.track_in_exit_approach(track) for track in tracks)
            or self.has_ready_handoff_track(tracks)
        )
        recommended_step = rt._transport_velocity.snapshot.recommended_step_deg
        step = (
            min(rt._transport_step_deg, rt._exit_approach_step_deg)
            if use_exit_approach
            else float(recommended_step or rt._transport_step_deg)
        )
        if not use_exit_approach:
            step = max(rt._transport_step_deg, min(rt._transport_max_step_deg, step))

        scheduled = self.scheduled_transport_step(
            tracks=tracks,
            now_mono=now_mono,
            base_step=step,
            use_exit_approach=use_exit_approach,
        )
        if scheduled is not None:
            step = scheduled
        move = move_command or (
            rt._carousel_move if use_exit_approach else rt._transport_move
        )

        def _do_move() -> None:
            try:
                move(step)
            except Exception:
                rt._logger.exception("RuntimeC4: transport move raised")

        if rt._hw.enqueue(_do_move, label="c4_transport"):
            rt._record_handoff_move(
                now_mono=now_mono,
                source="c4_transport",
                step_deg=step,
                use_exit_approach=use_exit_approach,
                track_count=len(tracks),
            )
            rt._next_transport_at = now_mono + rt._transport_cooldown_s
            return True
        return False

    def scheduled_transport_step(
        self,
        *,
        tracks: list[Track],
        now_mono: float,
        base_step: float,
        use_exit_approach: bool,
    ) -> float | None:
        del tracks, base_step
        rt = self._rt
        port = rt._handoff
        if port is None:
            return None
        candidate = rt._next_handoff_candidate()
        if candidate is None:
            return None
        next_ready_fn = getattr(port, "next_ready_time", None)
        if not callable(next_ready_fn):
            return None
        try:
            t_free = float(next_ready_fn(now_mono))
        except Exception:
            return None
        time_until_ready = max(0.0, t_free - float(now_mono))
        if time_until_ready <= 0.05:
            return None
        zone = rt._zone_manager.zone_for(candidate.piece_uuid)
        if zone is None:
            return None
        exit_distance_deg = abs(_wrap_deg(zone.center_deg - rt._exit_angle_deg))
        if exit_distance_deg <= 0.5:
            return None
        cooldown = max(rt._transport_cooldown_s, 0.001)
        steps_remaining = max(1.0, time_until_ready / cooldown)
        desired_step = exit_distance_deg / steps_remaining
        cap = (
            min(rt._transport_step_deg, rt._exit_approach_step_deg)
            if use_exit_approach
            else rt._transport_max_step_deg
        )
        floor = rt._transport_step_deg
        return max(floor, min(cap, desired_step))

    def dispatch_sample_transport_step(self, now_mono: float) -> bool:
        rt = self._rt
        if rt._hw_busy_or_backlogged():
            rt._set_state("sample_transport", blocked_reason="hw_busy")
            return False
        step = rt._sample_transport_step_deg

        def _do_move() -> None:
            try:
                rt._sample_transport_move(
                    step,
                    rt._sample_transport_max_speed,
                    rt._sample_transport_acceleration,
                )
            except Exception:
                rt._logger.exception("RuntimeC4: sample transport move raised")

        if not rt._hw.enqueue(_do_move, label="c4_sample_transport"):
            rt._set_state("sample_transport", blocked_reason="hw_queue_full")
            return False
        rt._next_transport_at = now_mono + rt._transport_cooldown_s
        rt._set_state("sample_transport")
        return True

    def configure_sample_transport(
        self,
        *,
        target_rpm: float | None,
        direct_max_speed_usteps_per_s: int | None = None,
        direct_acceleration_usteps_per_s2: int | None = None,
    ) -> None:
        rt = self._rt
        rt._sample_transport_max_speed = direct_max_speed_usteps_per_s
        rt._sample_transport_acceleration = direct_acceleration_usteps_per_s2
        if target_rpm is None:
            rt._sample_transport_step_deg = rt._transport_step_deg
            return
        target_degrees_per_second = max(0.0, float(target_rpm)) * 6.0
        step = target_degrees_per_second * SAMPLE_TRANSPORT_TARGET_INTERVAL_S
        rt._sample_transport_step_deg = max(
            rt._transport_step_deg,
            min(SAMPLE_TRANSPORT_MAX_STEP_DEG, step),
        )

    def maybe_idle_jog(self, now_mono: float) -> bool:
        rt = self._rt
        state = type(rt._fsm)
        if not rt._idle_jog_enabled:
            return False
        if rt._pieces:
            return False
        if (
            rt._startup_purge_controller.pending()
            or rt._startup_purge_state.mode_active
        ):
            return False
        if rt._fsm in (
            state.STARTUP_PURGE,
            state.DROP_COMMIT,
            state.EXIT_SHIMMY,
            state.TRANSPORT_UNJAM,
        ):
            return False
        if rt._hw_busy_or_backlogged() or now_mono < rt._next_idle_jog_at:
            return False
        if now_mono < rt._next_accept_at:
            return False

        def _do_idle_jog() -> None:
            try:
                rt._carousel_move(rt._idle_jog_step_deg)
            except Exception:
                rt._logger.exception("RuntimeC4: idle jog move raised")

        if rt._hw.enqueue(_do_idle_jog, label="c4_idle_jog"):
            rt._next_idle_jog_at = now_mono + rt._idle_jog_cooldown_s
            rt._last_idle_jog_at = now_mono
            rt._idle_jog_count += 1
            return True
        return False

    def track_in_exit_approach(self, track: Track) -> bool:
        rt = self._rt
        if track.angle_rad is None or track.global_id is None:
            return False
        if rt._piece_uuid_for_track(track) is None:
            return False
        center_delta = abs(
            _wrap_deg(math.degrees(track.angle_rad) - rt._exit_angle_deg)
        )
        if center_delta <= rt._exit_approach_angle_deg:
            return True
        overlap = self.exit_zone_bbox_overlap_ratio(track)
        return bool(overlap is not None and overlap > 0.0)

    def has_ready_handoff_track(self, tracks: list[Track]) -> bool:
        rt = self._rt
        for track in tracks:
            piece_uuid = rt._piece_uuid_for_track(track)
            if piece_uuid is None:
                continue
            dossier = rt._pieces.get(piece_uuid)
            if (
                dossier is not None
                and dossier.handoff_requested
                and dossier.distributor_ready
                and not dossier.eject_enqueued
            ):
                return True
        return False

    def exit_zone_bbox_overlap_ratio(self, track: Track) -> float | None:
        rt = self._rt
        if track.angle_rad is None:
            return None
        bbox = getattr(track, "bbox_xyxy", None)
        radius = getattr(track, "radius_px", None)
        if bbox is None or radius is None:
            return None
        try:
            x1, y1, x2, y2 = (float(v) for v in bbox)
            radius_f = float(radius)
        except (TypeError, ValueError):
            return None
        if x2 <= x1 or y2 <= y1 or radius_f <= 0.0:
            return None

        center_angle = float(track.angle_rad)
        center_x = (x1 + x2) / 2.0
        center_y = (y1 + y2) / 2.0
        origin_x = center_x - radius_f * math.cos(center_angle)
        origin_y = center_y - radius_f * math.sin(center_angle)
        deltas: list[float] = []
        for x, y in ((x1, y1), (x1, y2), (x2, y1), (x2, y2)):
            corner_angle = math.degrees(math.atan2(y - origin_y, x - origin_x))
            deltas.append(_wrap_deg(corner_angle - math.degrees(center_angle)))
        if not deltas:
            return None

        start = min(deltas)
        end = max(deltas)
        width = max(0.0, end - start)
        exit_delta = _wrap_deg(rt._exit_angle_deg - math.degrees(center_angle))
        window_start = exit_delta - rt._angle_tol_deg
        window_end = exit_delta + rt._angle_tol_deg
        if width <= 1e-6:
            return 1.0 if window_start <= 0.0 <= window_end else 0.0
        overlap = max(0.0, min(end, window_end) - max(start, window_start))
        return max(0.0, min(1.0, overlap / width))


def _wrap_deg(angle: float) -> float:
    return (float(angle) + 180.0) % 360.0 - 180.0


__all__ = ["C4TransportController"]
