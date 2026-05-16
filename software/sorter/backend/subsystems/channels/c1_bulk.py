from __future__ import annotations

from subsystems.channels.base import (
    BaseStation,
    FeederTickContext,
    publish_bulk_feeder_stalled_incident,
)


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
            stalled_ms = int(
                max(0.0, ctx.now_mono - self._last_ch2_activity_at_ref()) * 1000.0
            )
            published = publish_bulk_feeder_stalled_incident(
                self.gc,
                stalled_ms=stalled_ms,
                pulses_since_activity=self._ch1_pulses_since_ch2_activity_ref(),
                min_pulses=fc.first_rotor_jam_min_pulses,
                recovery_levels=max_recovery_levels,
            )
            if published:
                prof.hit("feeder.ch1.bulk_feeder_stalled_incident")
                self.gc.runtime_stats.observeBlockedReason(
                    "feeder",
                    "bulk_feeder_stalled_incident",
                )
                self.set_state("feeding.wait_bulk_feeder_stalled_incident")
                ctx.abort_tick = True
                return
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
