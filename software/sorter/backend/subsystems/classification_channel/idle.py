from typing import Optional
import time

from global_config import GlobalConfig
from irl.config import IRLConfig, IRLInterface
from piece_transport import ClassificationChannelTransport
from states.base_state import BaseState
from subsystems.classification_channel.states import ClassificationChannelState
from subsystems.shared_variables import SharedVariables

# Minimum number of pulses fired regardless of detection — the classifier
# polygon doesn't always cover the full exit zone, so a piece parked right
# at the exit can be physically present but optically invisible to the
# dynamic detector. A blind initial burst guarantees any staged piece is
# pushed into the chute before we rely on detection.
PURGE_MIN_PULSES = 3

# Once the detector first reports an empty channel, keep pulsing a small
# blind tail burst before declaring the purge complete. This covers parts
# that have already drifted partially out of the watched polygon / FoV but
# still haven't actually fallen out of the chamber yet.
PURGE_POST_CLEAR_PULSES = 4

# Hard safety cap — under normal conditions even a fully loaded C-channel
# is clean after 5-6 pulses. If we've fired this many and detection still
# shows pieces the channel is probably jammed; give up and hand control
# to DETECTING so the operator can intervene rather than hammering the
# stepper forever.
PURGE_MAX_PULSES = 20

# Purge speed as a multiplier of the configured normal-eject speed
# (``feeder_config.classification_channel_eject.microsteps_per_second``).
# Normal eject already runs at the config speed; for a leftover-piece
# purge the channel can safely rip at 2x that rate because there's no
# piece still being classified to worry about.
PURGE_SPEED_MULTIPLIER = 2.0

# Purge should be assertive enough to actually feed parts into the output
# guide. The runtime C4 motion may intentionally use a gentler acceleration
# for imaging stability, but purge should not inherit that soft profile.
PURGE_ACCELERATION_MICROSTEPS_PER_SECOND_SQ = 6000

# Small settle after each pulse before re-checking detection — lets the
# camera frame refresh past any motion-blur artefact from the stepper
# move so the candidate count reflects actual occupancy.
POST_PULSE_SETTLE_MS = 250


class Idle(BaseState):
    """Startup / purge state.

    On every (re-)start we walk any pieces that may be sitting in the
    C-channel out of the machine into the discard bucket. Distribution
    doors are opened so the piece falls straight through, the stepper
    is briefly switched to a higher purge speed, and we pulse the
    transport one slot at a time. After each pulse the dynamic detector
    is re-queried — as long as it still sees candidates anywhere in the
    classification-channel polygon (hood, wait zone, or exit zone) we
    keep pulsing. A hard safety cap prevents an infinite loop when
    detection is misconfigured or a piece is physically jammed.
    """

    def __init__(
        self,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        shared: SharedVariables,
        transport: ClassificationChannelTransport,
        vision,
    ):
        super().__init__(irl, gc)
        self.irl_config = irl_config
        self.shared = shared
        self.transport = transport
        self.vision = vision
        self._phase: str = "check"
        self._pulses_sent: int = 0
        self._pulse_in_flight: bool = False
        self._pulse_finished_at: Optional[float] = None
        self._clear_confirmation_pulses_sent: int = 0
        self._dynamic_mode = bool(getattr(transport, "dynamic_mode", False))

    def step(self) -> Optional[ClassificationChannelState]:
        if hasattr(self.shared, "set_classification_gate"):
            self.shared.set_classification_gate(False, reason="startup_purge")

        if self._dynamic_mode and self.transport.activePieces():
            return ClassificationChannelState.RUNNING

        if self.transport.getPieceAtClassification() is not None:
            # Transport already tracks a piece — regular flow takes over.
            if self._dynamic_mode:
                return ClassificationChannelState.RUNNING
            return ClassificationChannelState.SNAPPING

        if self._phase == "check":
            purge_speed = self._purgeSpeedUstepsPerSec()
            self.logger.warning(
                "ClassificationChannel: startup purge — opening distribution "
                "doors, firing at least %d pulses at %d µsteps/s (then continuing "
                "until the detector sees an empty channel)"
                % (PURGE_MIN_PULSES, purge_speed)
            )
            self._openAllLayerDoors()
            self._applyPurgeSpeed(purge_speed)
            self._phase = "pulsing"
            return None

        if self._phase == "pulsing":
            # Finish a previously-fired pulse before doing anything else.
            if self._pulse_in_flight:
                if not self.irl.carousel_stepper.stopped:
                    return None
                self._pulse_in_flight = False
                self._pulse_finished_at = time.time()
                self._pulses_sent += 1
                return None

            # Give the camera a moment to refresh past motion blur before
            # trusting the next detection call.
            if self._pulse_finished_at is not None:
                elapsed_ms = (time.time() - self._pulse_finished_at) * 1000
                if elapsed_ms < POST_PULSE_SETTLE_MS:
                    return None
                self._pulse_finished_at = None

            channel_visible = True
            if self._pulses_sent >= PURGE_MIN_PULSES:
                channel_visible = self._piecesVisibleInChannel()
                if channel_visible:
                    self._clear_confirmation_pulses_sent = 0
                elif self._clear_confirmation_pulses_sent >= PURGE_POST_CLEAR_PULSES:
                    self.logger.info(
                        "ClassificationChannel: purge complete — channel clean "
                        "after %d pulse(s) plus %d post-clear pulse(s)"
                        % (self._pulses_sent, PURGE_POST_CLEAR_PULSES)
                    )
                    self._restoreRuntimeSpeed()
                    self._handOffToDetecting()
                    self._phase = "done"
                    if self._dynamic_mode:
                        return ClassificationChannelState.RUNNING
                    return ClassificationChannelState.DETECTING

            if self._pulses_sent >= PURGE_MAX_PULSES:
                self.logger.error(
                    "ClassificationChannel: purge safety cap (%d pulses) reached "
                    "but detector still sees pieces — giving up and handing "
                    "over to DETECTING; please clear the channel manually"
                    % PURGE_MAX_PULSES
                )
                self._restoreRuntimeSpeed()
                self._handOffToDetecting()
                self._phase = "done"
                if self._dynamic_mode:
                    return ClassificationChannelState.RUNNING
                return ClassificationChannelState.DETECTING

            # Still occupied — fire another pulse.
            cfg = self.irl_config.feeder_config.classification_channel_eject
            pulse_degrees = self.irl.carousel_stepper.degrees_for_microsteps(
                cfg.steps_per_pulse
            )
            if not self.irl.carousel_stepper.move_degrees(pulse_degrees):
                return None
            if self._pulses_sent >= PURGE_MIN_PULSES and not channel_visible:
                self._clear_confirmation_pulses_sent += 1
            self._pulse_in_flight = True
            self.logger.info(
                "ClassificationChannel: purge pulse %d (%.1f deg)%s"
                % (
                    self._pulses_sent + 1,
                    pulse_degrees,
                    (
                        " [post-clear %d/%d]"
                        % (
                            self._clear_confirmation_pulses_sent,
                            PURGE_POST_CLEAR_PULSES,
                        )
                    )
                    if self._pulses_sent >= PURGE_MIN_PULSES and not channel_visible
                    else "",
                )
            )
            return None

        if self._dynamic_mode:
            return ClassificationChannelState.RUNNING
        return ClassificationChannelState.DETECTING

    def cleanup(self) -> None:
        super().cleanup()
        # If we leave mid-purge (pause before the channel was clean) the
        # stepper must be returned to runtime speed so Ejecting doesn't
        # inherit the fast purge setting.
        self._restoreRuntimeSpeed()
        # Reset so a subsequent resume re-runs the purge.
        self._phase = "check"
        self._pulses_sent = 0
        self._pulse_in_flight = False
        self._pulse_finished_at = None
        self._clear_confirmation_pulses_sent = 0

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _handOffToDetecting(self) -> None:
        """Reset any state that could spuriously block the normal flow."""
        vision = self.vision
        if vision is None:
            return
        try:
            vision.clearCarouselBaseline()
        except Exception as exc:
            self.logger.warning(
                f"ClassificationChannel: could not clear carousel baseline: {exc}"
            )
        # Note: we do NOT call ``tracker.reset()`` here — the tracker is
        # used concurrently by HTTP camera-stream overlay threads and
        # mutating ``_tracks`` mid-update produces ``KeyError`` crashes.
        # Tracks age out within ~1s naturally (coast_limit=20 ticks); the
        # feeder gate will unblock as soon as the purged piece's track
        # coasts out.

    def _piecesVisibleInChannel(self) -> bool:
        """True while the chamber still has live piece evidence.

        Prefer the live carousel tracker over raw detections: once a real
        piece has been seen moving, the tracker remains authoritative even
        when the detector briefly loses the bbox near the chamber edge.
        Raw detections remain as fallback for fresh pieces that have not yet
        matured into a stable track.
        """
        if self.vision is None:
            return False
        try:
            track_extents = self.vision.getFeederTrackAngularExtents(
                "carousel",
                force_detection=True,
            )
            if track_extents:
                return True
        except Exception as exc:
            self.logger.warning(
                f"ClassificationChannel: purge track-check failed: {exc}"
            )
        try:
            candidates = self.vision.getClassificationChannelDetectionCandidates(
                force=True
            )
        except Exception as exc:
            self.logger.warning(
                f"ClassificationChannel: purge piece-check failed: {exc}"
            )
            return False
        return bool(candidates)

    def _purgeSpeedUstepsPerSec(self) -> int:
        cfg = self.irl_config.feeder_config.classification_channel_eject
        base = int(getattr(cfg, "microsteps_per_second", 0) or 0)
        if base <= 0:
            # Config missing / zero — fall back to the stepper's init limit
            # so we at least don't send an invalid zero speed to the MCU.
            return int(
                getattr(
                    self.irl_config.carousel_stepper,
                    "default_steps_per_second",
                    1000,
                )
            )
        return int(base * PURGE_SPEED_MULTIPLIER)

    def _applyPurgeSpeed(self, speed_usteps_per_sec: int) -> None:
        try:
            self.irl.carousel_stepper.set_speed_limits(16, speed_usteps_per_sec)
        except Exception as exc:
            self.logger.warning(
                f"ClassificationChannel: could not raise stepper speed for purge: {exc}"
            )
        if hasattr(self.irl.carousel_stepper, "set_acceleration"):
            try:
                self.irl.carousel_stepper.set_acceleration(
                    PURGE_ACCELERATION_MICROSTEPS_PER_SECOND_SQ
                )
            except Exception as exc:
                self.logger.warning(
                    f"ClassificationChannel: could not raise stepper acceleration for purge: {exc}"
                )

    def _restoreRuntimeSpeed(self) -> None:
        # Ejecting re-applies its own per-pulse speed, so any value here is
        # just a short-lived fallback. We use the configured normal eject
        # speed so that any non-Ejecting mover (e.g. manual stepper ops)
        # also inherits a sensible speed.
        cfg = self.irl_config.feeder_config.classification_channel_eject
        runtime_speed = int(getattr(cfg, "microsteps_per_second", 0) or 0)
        if runtime_speed <= 0:
            runtime_speed = int(
                getattr(
                    self.irl_config.carousel_stepper,
                    "default_steps_per_second",
                    1000,
                )
            )
        try:
            self.irl.carousel_stepper.set_speed_limits(16, runtime_speed)
        except Exception as exc:
            self.logger.warning(
                f"ClassificationChannel: could not restore stepper speed: {exc}"
            )
        runtime_acceleration = getattr(
            cfg,
            "acceleration_microsteps_per_second_sq",
            None,
        )
        if runtime_acceleration is not None and hasattr(
            self.irl.carousel_stepper,
            "set_acceleration",
        ):
            try:
                self.irl.carousel_stepper.set_acceleration(int(runtime_acceleration))
            except Exception as exc:
                self.logger.warning(
                    f"ClassificationChannel: could not restore stepper acceleration: {exc}"
                )

    def _openAllLayerDoors(self) -> None:
        if self.gc.disable_servos:
            return
        for i, servo in enumerate(self.irl.servos):
            try:
                servo.open()
            except Exception as exc:
                self.logger.warning(
                    f"ClassificationChannel: could not open layer {i} door for purge: {exc}"
                )
