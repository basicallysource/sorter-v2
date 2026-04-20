from __future__ import annotations

from subsystems.channels.base import BaseStation, FeederTickContext
from subsystems.feeder.analysis import ChannelAction


class C2Station(BaseStation):
    def __init__(
        self,
        *,
        gc,
        stepper,
        irl,
        send_pulse,
        feeder_config,
        separation_driver,
        gear_ratio: float,
        agitation_enabled: bool,
        agitation_reverse_deg_output: float,
        agitation_forward_deg_output: float,
        agitation_min_interval_s: float,
        agitation_recent_ch1_window_s: float,
    ) -> None:
        super().__init__(gc=gc, machine_name="feeder.ch2")
        self._stepper = stepper
        self._irl = irl
        self._send_pulse = send_pulse
        self._feeder_config = feeder_config
        self._separation_driver = separation_driver
        self._gear_ratio = float(gear_ratio)
        self._agitation_enabled = agitation_enabled
        self._agitation_reverse_deg_output = float(agitation_reverse_deg_output)
        self._agitation_forward_deg_output = float(agitation_forward_deg_output)
        self._agitation_min_interval_s = float(agitation_min_interval_s)
        self._agitation_recent_ch1_window_s = float(agitation_recent_ch1_window_s)
        self._next_agitation_at: float = 0.0
        self._last_ch1_pulse_at_ref = lambda: 0.0

    def bind_last_ch1_pulse_at(self, getter) -> None:
        self._last_ch1_pulse_at_ref = getter

    def step(self, ctx: FeederTickContext) -> None:
        prof = self.gc.profiler

        if not ctx.analysis.ch3_dropzone_occupied:
            if ctx.ch2_action == ChannelAction.PULSE_PRECISE:
                prof.hit("feeder.path.ch2_precise")
                ctx.pulse_intent = True
                if self._send_pulse("ch2_precise", self._stepper, self._feeder_config.second_rotor_precision):
                    ctx.pulse_sent = True
                    self.gc.logger.info("Feeder: ch2 precise, pulsing 2nd (precise)")
                self.set_state("feeding.pulse_ch2_precise")
                return
            if ctx.ch2_action == ChannelAction.PULSE_NORMAL:
                prof.hit("feeder.path.ch2_normal")
                ctx.pulse_intent = True
                if self._send_pulse("ch2_normal", self._stepper, self._feeder_config.second_rotor_normal):
                    ctx.pulse_sent = True
                    self.gc.logger.info("Feeder: ch2 normal, pulsing 2nd")
                self.set_state("feeding.pulse_ch2_normal")
                return
            prof.hit("feeder.path.ch2_idle")
        else:
            prof.hit("feeder.skip.ch2_dropzone_occupied")
            self.gc.runtime_stats.observeBlockedReason("feeder", "ch2_blocked_by_ch3_dropzone")
            self.set_state("feeding.wait_ch3_dropzone_clear")
            return

        if ctx.ch2_action == ChannelAction.IDLE:
            self.set_state("feeding.idle_no_piece_in_ch2")
        else:
            self.set_state("feeding.pulse_ch2_normal")

    def run_idle_strategies(self, ctx: FeederTickContext) -> None:
        prof = self.gc.profiler
        now = ctx.now_mono

        if (
            self._agitation_enabled
            and not ctx.pulse_sent
            and ctx.ch2_action == ChannelAction.IDLE
            and not ctx.ch2_stepper_busy
            and not ctx.analysis.ch2_dropzone_occupied
            and (ctx.ch3_held or ctx.ch3_action != ChannelAction.IDLE or ctx.ch3_stepper_busy)
            and (now - self._last_ch1_pulse_at_ref()) <= self._agitation_recent_ch1_window_s
            and now >= self._next_agitation_at
        ):
            try:
                rev_stepper_deg = self._agitation_reverse_deg_output * self._gear_ratio
                fwd_stepper_deg = self._agitation_forward_deg_output * self._gear_ratio
                self._irl.c_channel_2_rotor_stepper.move_degrees(-rev_stepper_deg)
                self._irl.c_channel_2_rotor_stepper.move_degrees(fwd_stepper_deg)
                prof.hit("feeder.ch2.agitation")
                self.gc.logger.info(
                    f"Feeder: ch2 agitation jog "
                    f"(rev={self._agitation_reverse_deg_output:.0f}° out / "
                    f"fwd={self._agitation_forward_deg_output:.0f}° out)"
                )
            except Exception as exc:
                self.gc.logger.warning(f"Feeder: ch2 agitation failed: {exc}")
            self._next_agitation_at = now + self._agitation_min_interval_s

        separation_allowed = (
            not ctx.pulse_sent
            and not ctx.ch1_jam_recovery_triggered
            and ctx.ch2_action == ChannelAction.PULSE_NORMAL
            and not ctx.analysis.ch2_dropzone_occupied
            and (self._separation_driver.active or not ctx.ch2_stepper_busy)
        )
        self._separation_driver.step(now, separation_allowed)

    def cleanup(self) -> None:
        self._separation_driver.cancel("c2 station cleanup")


__all__ = ["C2Station"]
