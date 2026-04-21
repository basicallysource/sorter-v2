from __future__ import annotations

import math

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


# Minimum angular gap (in channel-relative degrees) between two neighbouring
# C2 bbox-center angles for them to count as a "cluster". Picked small so only
# genuinely touching/overlapping pieces trigger the agitation jog; loose
# pieces spread around the channel should be left alone.
C2_CLUSTER_ANGULAR_GAP_DEG: float = 12.0


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
        exit_wiggle_overlap_threshold: float = EXIT_WIGGLE_OVERLAP_THRESHOLD,
        exit_wiggle_stall_ms: int = EXIT_WIGGLE_STALL_MS,
        exit_wiggle_reverse_deg: float = EXIT_WIGGLE_REVERSE_DEG,
        exit_wiggle_forward_deg: float = EXIT_WIGGLE_FORWARD_DEG,
        exit_wiggle_cooldown_ms: int = EXIT_WIGGLE_COOLDOWN_MS,
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
        # Exit-zone wiggle state.
        self._exit_wiggle_overlap_threshold = float(exit_wiggle_overlap_threshold)
        self._exit_wiggle_stall_ms = int(exit_wiggle_stall_ms)
        self._exit_wiggle_reverse_deg = float(exit_wiggle_reverse_deg)
        self._exit_wiggle_forward_deg = float(exit_wiggle_forward_deg)
        self._exit_wiggle_cooldown_ms = int(exit_wiggle_cooldown_ms)
        self._exit_overlap_since_mono: float | None = None
        self._next_exit_wiggle_at: float = 0.0

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

    def _c2HasCluster(self, ctx: FeederTickContext) -> bool:
        """Return True when >=2 C2 detections sit within a tight angular gap.

        Uses each C2 detection's bbox-center polar angle (expressed in the
        channel's own rotational frame, matching how ``getBboxSections`` bins
        detections). If any two consecutive sorted angles differ by less than
        ``C2_CLUSTER_ANGULAR_GAP_DEG``, we consider the pieces clustered.
        Avoids reaching into ``PolarFeederTracker`` internals — the per-tick
        detections already carry the channel geometry we need.
        """
        angles: list[float] = []
        for det in ctx.detections:
            if getattr(det, "channel_id", None) != 2:
                continue
            channel = getattr(det, "channel", None)
            if channel is None:
                continue
            x1, y1, x2, y2 = det.bbox
            cx = (x1 + x2) / 2.0 - channel.center[0]
            cy = (y1 + y2) / 2.0 - channel.center[1]
            angle = math.degrees(math.atan2(cy, cx))
            relative = (angle - channel.radius1_angle_image) % 360.0
            angles.append(relative)

        if len(angles) < 2:
            return False

        angles.sort()
        for a, b in zip(angles, angles[1:]):
            if (b - a) < C2_CLUSTER_ANGULAR_GAP_DEG:
                return True
        # Wrap-around: gap between last and first (+360).
        if (angles[0] + 360.0 - angles[-1]) < C2_CLUSTER_ANGULAR_GAP_DEG:
            return True
        return False

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
            if not self._c2HasCluster(ctx):
                # No genuine piece-cluster on C2 — the spread jog would just
                # waste motion (and wear). Skip and record in stats.
                self.gc.runtime_stats.observeC2IdleSkippedNoCluster()
                prof.hit("feeder.ch2.agitation_skipped_no_cluster")
            else:
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

    def run_exit_wiggle(self, ctx: FeederTickContext) -> None:
        """Jog the C2 rotor a little when a piece is stuck at the exit.

        Fires only when: (a) the analyzer reports that some detection has
        >=exit_wiggle_overlap_threshold of its bbox sections inside C2's
        exit sections, (b) it has been in that state for at least
        exit_wiggle_stall_ms, (c) the downstream gate (ch3 dropzone
        occupied) is closed so a normal pulse would be rejected anyway,
        and (d) we haven't wiggled within the cooldown window. Runs after
        stations have already passed; if pulse was sent we skip.
        """
        prof = self.gc.profiler
        now = ctx.now_mono
        overlap = float(getattr(ctx.analysis, "ch2_exit_overlap_max", 0.0))

        if overlap >= self._exit_wiggle_overlap_threshold:
            if self._exit_overlap_since_mono is None:
                self._exit_overlap_since_mono = now
        else:
            self._exit_overlap_since_mono = None
            return

        if ctx.pulse_sent or ctx.ch2_stepper_busy:
            return
        # Only run wiggle when the normal pulse path is blocked downstream.
        if not ctx.analysis.ch3_dropzone_occupied:
            return
        stall_s = (now - self._exit_overlap_since_mono)
        if stall_s * 1000.0 < self._exit_wiggle_stall_ms:
            return
        if now < self._next_exit_wiggle_at:
            return

        try:
            rev_deg = self._exit_wiggle_reverse_deg * self._gear_ratio
            fwd_deg = self._exit_wiggle_forward_deg * self._gear_ratio
            self._irl.c_channel_2_rotor_stepper.move_degrees(-rev_deg)
            self._irl.c_channel_2_rotor_stepper.move_degrees(fwd_deg)
            prof.hit("feeder.ch2.exit_wiggle")
            self.gc.runtime_stats.observeExitWiggleTriggered("c2")
            self.gc.logger.info(
                f"Feeder: ch2 exit-zone wiggle "
                f"(rev={self._exit_wiggle_reverse_deg:.1f}° out / "
                f"fwd={self._exit_wiggle_forward_deg:.1f}° out, stall={stall_s*1000.0:.0f} ms)"
            )
        except Exception as exc:
            self.gc.logger.warning(f"Feeder: ch2 exit wiggle failed: {exc}")
        self._next_exit_wiggle_at = now + self._exit_wiggle_cooldown_ms / 1000.0

    def cleanup(self) -> None:
        self._separation_driver.cancel("c2 station cleanup")


__all__ = ["C2Station"]
