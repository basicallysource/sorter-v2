from __future__ import annotations

from subsystems.channels.base import (
    BaseStation,
    FeederTickContext,
    EXIT_WIGGLE_OVERLAP_THRESHOLD,
    EXIT_WIGGLE_STALL_MS,
    EXIT_WIGGLE_REVERSE_DEG,
    EXIT_WIGGLE_FORWARD_DEG,
    EXIT_WIGGLE_COOLDOWN_MS,
)
from subsystems.feeder.analysis import ChannelAction


class C3Station(BaseStation):
    def __init__(
        self,
        *,
        gc,
        stepper,
        send_pulse,
        feeder_config,
        irl=None,
        gear_ratio: float = 1.0,
        exit_wiggle_overlap_threshold: float = EXIT_WIGGLE_OVERLAP_THRESHOLD,
        exit_wiggle_stall_ms: int = EXIT_WIGGLE_STALL_MS,
        exit_wiggle_reverse_deg: float = EXIT_WIGGLE_REVERSE_DEG,
        exit_wiggle_forward_deg: float = EXIT_WIGGLE_FORWARD_DEG,
        exit_wiggle_cooldown_ms: int = EXIT_WIGGLE_COOLDOWN_MS,
    ) -> None:
        super().__init__(gc=gc, machine_name="feeder.ch3")
        self._stepper = stepper
        self._send_pulse = send_pulse
        self._feeder_config = feeder_config
        self._irl = irl
        self._gear_ratio = float(gear_ratio)
        self._exit_wiggle_overlap_threshold = float(exit_wiggle_overlap_threshold)
        self._exit_wiggle_stall_ms = int(exit_wiggle_stall_ms)
        self._exit_wiggle_reverse_deg = float(exit_wiggle_reverse_deg)
        self._exit_wiggle_forward_deg = float(exit_wiggle_forward_deg)
        self._exit_wiggle_cooldown_ms = int(exit_wiggle_cooldown_ms)
        self._exit_overlap_since_mono: float | None = None
        self._next_exit_wiggle_at: float = 0.0

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

    def run_exit_wiggle(self, ctx: FeederTickContext) -> None:
        """Jog the C3 rotor a little when a piece is stuck at the exit.

        Fires only when: (a) the analyzer reports that some detection has
        >=exit_wiggle_overlap_threshold of its bbox sections inside C3's
        exit sections, (b) it has been in that state for at least
        exit_wiggle_stall_ms, (c) the downstream gate is closed (ch3_held —
        carousel not ready or classification channel full) so the normal
        pulse would be skipped, and (d) we haven't wiggled within the
        cooldown window.
        """
        prof = self.gc.profiler
        now = ctx.now_mono
        overlap = float(getattr(ctx.analysis, "ch3_exit_overlap_max", 0.0))

        if overlap >= self._exit_wiggle_overlap_threshold:
            if self._exit_overlap_since_mono is None:
                self._exit_overlap_since_mono = now
        else:
            self._exit_overlap_since_mono = None
            return

        if ctx.pulse_sent or ctx.ch3_stepper_busy:
            return
        if not ctx.ch3_held:
            return
        if self._irl is None:
            return
        stall_s = (now - self._exit_overlap_since_mono)
        if stall_s * 1000.0 < self._exit_wiggle_stall_ms:
            return
        if now < self._next_exit_wiggle_at:
            return

        try:
            rev_deg = self._exit_wiggle_reverse_deg * self._gear_ratio
            fwd_deg = self._exit_wiggle_forward_deg * self._gear_ratio
            self._irl.c_channel_3_rotor_stepper.move_degrees(-rev_deg)
            self._irl.c_channel_3_rotor_stepper.move_degrees(fwd_deg)
            prof.hit("feeder.ch3.exit_wiggle")
            self.gc.runtime_stats.observeExitWiggleTriggered("c3")
            self.gc.logger.info(
                f"Feeder: ch3 exit-zone wiggle "
                f"(rev={self._exit_wiggle_reverse_deg:.1f}° out / "
                f"fwd={self._exit_wiggle_forward_deg:.1f}° out, stall={stall_s*1000.0:.0f} ms)"
            )
        except Exception as exc:
            self.gc.logger.warning(f"Feeder: ch3 exit wiggle failed: {exc}")
        self._next_exit_wiggle_at = now + self._exit_wiggle_cooldown_ms / 1000.0


__all__ = ["C3Station"]
