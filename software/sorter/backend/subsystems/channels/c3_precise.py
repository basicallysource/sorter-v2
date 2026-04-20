from __future__ import annotations

from subsystems.channels.base import BaseStation, FeederTickContext
from subsystems.feeder.analysis import ChannelAction


class C3Station(BaseStation):
    def __init__(self, *, gc, stepper, send_pulse, feeder_config) -> None:
        super().__init__(gc=gc, machine_name="feeder.ch3")
        self._stepper = stepper
        self._send_pulse = send_pulse
        self._feeder_config = feeder_config

    def step(self, ctx: FeederTickContext) -> None:
        prof = self.gc.profiler

        if ctx.ch3_held:
            if ctx.classification_channel_block:
                prof.hit("feeder.skip.classification_channel_occupied")
                self.gc.runtime_stats.observeBlockedReason(
                    "feeder", "classification_channel_occupied"
                )
                self.set_state(
                    f"feeding.wait_classification_channel_clear_{ctx.classification_channel_piece_count}_pieces"
                )
            else:
                prof.hit("feeder.skip.ch3_held_for_carousel")
                self.gc.runtime_stats.observeBlockedReason(
                    "feeder", "ch3_held_for_carousel"
                )
                self.set_state("feeding.wait_classification_ready_for_ch3_precise")
            return

        if ctx.ch3_action == ChannelAction.PULSE_PRECISE:
            prof.hit("feeder.path.ch3_precise")
            if self._send_pulse("ch3_precise", self._stepper, self._feeder_config.third_rotor_precision):
                self.gc.logger.info("Feeder: ch3 precise, pulsing 3rd (precise)")
            self.set_state("feeding.pulse_ch3_precise")
            return

        if ctx.ch3_action == ChannelAction.PULSE_NORMAL:
            prof.hit("feeder.path.ch3_normal")
            if self._send_pulse("ch3_normal", self._stepper, self._feeder_config.third_rotor_normal):
                self.gc.logger.info("Feeder: ch3 normal, pulsing 3rd")
            self.set_state("feeding.pulse_ch3_normal")
            return

        prof.hit("feeder.path.ch3_idle")
        self.set_state("feeding.idle_no_piece_in_ch3")


__all__ = ["C3Station"]
