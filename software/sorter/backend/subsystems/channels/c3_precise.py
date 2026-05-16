from __future__ import annotations

from subsystems.channels.base import (
    BaseStation,
    FeederTickContext,
    EXIT_WIGGLE_OVERLAP_THRESHOLD,
    EXIT_WIGGLE_STALL_MS,
    EXIT_WIGGLE_REVERSE_DEG,
    EXIT_WIGGLE_FORWARD_DEG,
    EXIT_WIGGLE_COOLDOWN_MS,
    publish_channel_exit_stuck_incident,
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
        """Publish a C3 exit-stuck incident instead of silently jogging.

        Fires only when a bbox has been at least four-fifths inside C3's exit
        zone for the configured stall duration while C3 is held by the
        downstream classification channel.
        """
        prof = self.gc.profiler
        now = ctx.now_mono
        overlap = float(getattr(ctx.analysis, "ch3_exit_overlap_max", 0.0))

        if ctx.sample_collection_mode:
            self._exit_overlap_since_mono = None
            return

        downstream_blocked = bool(ctx.ch3_held)
        if not downstream_blocked:
            self._exit_overlap_since_mono = None
            return

        if overlap >= self._exit_wiggle_overlap_threshold:
            if self._exit_overlap_since_mono is None:
                self._exit_overlap_since_mono = now
        else:
            self._exit_overlap_since_mono = None
            return

        if ctx.pulse_sent or ctx.ch3_stepper_busy:
            return
        stall_s = (now - self._exit_overlap_since_mono)
        if stall_s * 1000.0 < self._exit_wiggle_stall_ms:
            return
        if now < self._next_exit_wiggle_at:
            return

        published = publish_channel_exit_stuck_incident(
            self.gc,
            channel="c3",
            role="c_channel_3",
            channel_label="C-Channel 3",
            overlap_ratio=overlap,
            overlap_threshold=self._exit_wiggle_overlap_threshold,
            stall_ms=int(round(stall_s * 1000.0)),
            downstream_blocked=downstream_blocked,
        )
        if published:
            prof.hit("feeder.ch3.exit_incident")
            self.gc.runtime_stats.observeBlockedReason("feeder", "ch3_exit_stuck")
            self.gc.logger.warning(
                f"Feeder: C3 exit incident; bbox overlap={overlap:.2f}, "
                f"stall={stall_s*1000.0:.0f} ms, downstream blocked"
            )
        self._next_exit_wiggle_at = now + self._exit_wiggle_cooldown_ms / 1000.0


__all__ = ["C3Station"]
