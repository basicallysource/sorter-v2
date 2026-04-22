from __future__ import annotations

from subsystems.channels.base import BaseStation, FeederTickContext
from subsystems.feeder.admission import estimate_piece_count_for_channel


class C1Station(BaseStation):
    def __init__(
        self,
        *,
        gc,
        stepper,
        vision,
        irl_config,
        send_pulse,
        jam_recovery,
        feeder_pause_for_ch1_stall,
        max_ch2_pieces_for_feed: int,
        last_ch2_activity_at_ref,
        ch1_pulses_since_ch2_activity_ref,
        last_ch1_pulse_at_setter,
        ch1_pulses_since_ch2_activity_incrementer,
    ) -> None:
        super().__init__(gc=gc, machine_name="feeder.ch1")
        self._stepper = stepper
        self._vision = vision
        self._irl_config = irl_config
        self._send_pulse = send_pulse
        self._jam_recovery = jam_recovery
        self._pause_for_ch1_stall = feeder_pause_for_ch1_stall
        self._max_ch2_pieces_for_feed = int(max_ch2_pieces_for_feed)
        self._last_ch2_activity_at_ref = last_ch2_activity_at_ref
        self._ch1_pulses_since_ch2_activity_ref = ch1_pulses_since_ch2_activity_ref
        self._last_ch1_pulse_at_setter = last_ch1_pulse_at_setter
        self._ch1_pulses_since_ch2_activity_incrementer = (
            ch1_pulses_since_ch2_activity_incrementer
        )

    def step(self, ctx: FeederTickContext) -> None:
        prof = self.gc.profiler

        try:
            # Whitelist gate: count only tracks that have demonstrated
            # real motion. Otherwise an apparatus ghost on c_channel_2
            # would falsely saturate the channel and pause bulk feed.
            ch2_track_count = sum(
                1
                for track in self._vision.getFeederTracks("c_channel_2")
                if bool(getattr(track, "confirmed_real", False))
            )
        except Exception:
            ch2_track_count = 0
        ch2_piece_count = estimate_piece_count_for_channel(
            ctx.detections,
            channel_id=2,
            track_count=ch2_track_count,
        )
        ch2_saturated = ch2_piece_count >= self._max_ch2_pieces_for_feed
        if not ctx.analysis.ch2_dropzone_occupied and ch2_saturated:
            prof.hit("feeder.skip.ch2_saturated")
            self.gc.runtime_stats.observeBlockedReason(
                "feeder", "ch2_saturated_pause_ch1"
            )
            self.set_state(f"feeding.ch2_saturated_{ch2_piece_count}_pieces")
            return

        if ctx.analysis.ch2_dropzone_occupied:
            prof.hit("feeder.skip.ch1_dropzone_occupied")
            self.gc.runtime_stats.observeBlockedReason("feeder", "ch1_blocked_by_ch2_dropzone")
            self.set_state("feeding.wait_ch2_dropzone_clear")
            return

        prof.hit("feeder.path.ch1")
        fc = self._irl_config.feeder_config
        no_recent_ch2_activity = (
            ctx.now_mono - self._last_ch2_activity_at_ref() >= fc.first_rotor_jam_timeout_s
        )
        ch1_has_been_trying = (
            self._ch1_pulses_since_ch2_activity_ref() >= fc.first_rotor_jam_min_pulses
        )
        recovery_ready = self._jam_recovery.is_ready(ctx.now_mono)
        max_recovery_levels = max(1, int(fc.first_rotor_jam_max_cycles))
        if (
            no_recent_ch2_activity
            and ch1_has_been_trying
            and recovery_ready
            and not ctx.analysis.ch3_dropzone_occupied
        ):
            if self._jam_recovery.exhausted(max_recovery_levels):
                self._pause_for_ch1_stall(max_recovery_levels)
                self.set_state("feeding.stalled_before_ch2_dropzone")
                ctx.abort_tick = True
                return
            ctx.ch1_jam_recovery_triggered = self._jam_recovery.run(
                fc.first_rotor,
                ctx.now_mono,
            )
            ctx.pulse_intent = True
            ctx.pulse_sent = ctx.pulse_sent or ctx.ch1_jam_recovery_triggered
            if ctx.ch1_jam_recovery_triggered:
                self._last_ch1_pulse_at_setter(ctx.now_mono)
                self.set_state(
                    f"feeding.recover_bulk_bucket_to_ch2_{self._jam_recovery.state_name}"
                )
                return
        else:
            ctx.pulse_intent = True
            if self._send_pulse("ch1", self._stepper, fc.first_rotor):
                ctx.pulse_sent = True
                self._ch1_pulses_since_ch2_activity_incrementer()
                self._last_ch1_pulse_at_setter(ctx.now_mono)
                self.gc.logger.info("Feeder: clear, pulsing 1st")

        self.set_state("feeding.pulse_ch1_when_clear")


__all__ = ["C1Station"]
