import time
from typing import Optional

from subsystems.classification_channel.states import ClassificationChannelState

from .base import Rev01BaseState
from .constants import LOG_TAG


class Idle(Rev01BaseState):
    """Part of the SIMPLE_STATE_MACHINE_REV01 path — the classification half of the
    GO_TO_ANGLE_REV01 + SIMPLE_STATE_MACHINE_REV01 Rev04 pair.

    The other (legacy) classification paths do not use this file or package.
    When adding C4 exit jitter unstick later, this is the file + the rev01_config
    jitter_* fields to focus on (symmetric to GoToAngleFeeding).
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._presence_streak = 0
        self._clear_streak = 0
        self.logger.info(f"{LOG_TAG} IDLE state constructed")

    def step(self) -> Optional[ClassificationChannelState]:
        perception_service = getattr(self.gc, "perception_service", None)
        if perception_service is not None:
            return self._step_perception(perception_service)
        return self._step_legacy()

    # ---- Rev04 perception path ----

    def _step_perception(self, perception_service) -> Optional[ClassificationChannelState]:
        """Read the C4 perception slot and drive the simple state machine.

        Cascade rule for C4 (from the rev04 doc):
        - Channel empty (``n_pieces == 0``)        → classification_ready=True, stay Idle.
        - Anything on the channel                  → classification_ready=False.
        - After ``presence_streak_to_start`` consecutive ticks with a
          piece somewhere on the channel BUT NOT confined to the exit
          zone, transition to ROTATING_AND_CAPTURING.

        No stuck-piece timeout. No exit-zone-only branch escalation —
        if a piece is parked in the exit zone, perception reports
        ``in_exit=True, in_drop=False, n_pieces≥1`` and the SSM holds
        Idle reporting "not ready."
        """
        t0 = time.perf_counter()
        state = perception_service.read_state(4)
        self.gc.runtime_stats.observePerfMs(
            "classification.rev01.idle.perception_read_ms",
            (time.perf_counter() - t0) * 1000.0,
        )
        # How stale is the perception result at the instant we gate a decision
        # on it: wall-clock now minus the frame's capture timestamp (state.ts).
        # This is the dashboard's "age of inference data we decide on" metric.
        if state.ts:
            self.gc.runtime_stats.observePerfMs(
                "classification.decision_frame_age_ms",
                max(0.0, (time.time() - state.ts) * 1000.0),
            )
        self.gc.profiler.observeValue(
            "classification.rev01.idle.n_pieces", float(state.n_pieces)
        )

        if state.n_pieces == 0:
            self._presence_streak = 0
            self._clear_streak += 1
            # Asymmetry guard: we require presence_streak_to_start confirmed
            # reads to BELIEVE a piece arrived, but a single zero-read used to
            # flip ready=True instantly. The detector blinks to 0 for a frame or
            # two with a piece still on the channel; a premature ready=True lets
            # C3 push a second piece in while the first is merely undetected →
            # double feed. Require a confirmed clear streak too.
            if self._clear_streak >= self.ctx.config.idle_clear_confirm_reads:
                self.setClassificationReady(True, "channel clear")
            else:
                self.setClassificationReady(
                    False,
                    f"confirming clear ({self._clear_streak}/"
                    f"{self.ctx.config.idle_clear_confirm_reads})",
                )
            return None

        self._clear_streak = 0
        # Channel is occupied. Always not-ready.
        self.setClassificationReady(False, f"{state.n_pieces} piece(s) on channel")

        # Only an "actionable" piece (outside the exit zone) advances the
        # presence streak that triggers the capture sweep. A piece parked
        # in the exit zone holds Idle indefinitely. Jitter unstick (using
        # ctx.config.jitter_* fields + dwell tracking + carousel_stepper.jitter)
        # can be wired here symmetrically to GoToAngleFeeding when a C4 exit
        # piece exceeds jitter_exit_dwell_ms.
        if state.in_drop or (state.n_pieces > 0 and not state.in_exit):
            self._presence_streak += 1
        else:
            self._presence_streak = 0

        self.gc.profiler.observeValue(
            "classification.rev01.idle.presence_streak",
            float(self._presence_streak),
        )
        if self._presence_streak >= self.ctx.config.presence_streak_to_start:
            self._presence_streak = 0
            self.ctx.reset()
            self.logger.info(
                f"{LOG_TAG} IDLE -> ROTATING_AND_CAPTURING "
                f"(perception confirmed piece on channel, n_pieces={state.n_pieces})"
            )
            return ClassificationChannelState.REV01_ROTATING_AND_CAPTURING
        return None

    # ---- Legacy (non-perception) path, unchanged ----

    def _step_legacy(self) -> Optional[ClassificationChannelState]:
        bboxes_started = time.perf_counter()
        bboxes = self.cv.bboxesOnChannel()
        self.gc.runtime_stats.observePerfMs(
            "classification.rev01.idle.bboxes_on_channel_ms",
            (time.perf_counter() - bboxes_started) * 1000.0,
        )
        self.gc.profiler.observeValue(
            "classification.rev01.idle.bbox_count",
            float(len(bboxes)),
        )
        if not bboxes:
            self._presence_streak = 0
            self._clear_streak += 1
            if self._clear_streak >= self.ctx.config.idle_clear_confirm_reads:
                self.setClassificationReady(True, "channel clear")
            else:
                self.setClassificationReady(
                    False,
                    f"confirming clear ({self._clear_streak}/"
                    f"{self.ctx.config.idle_clear_confirm_reads})",
                )
            return None
        self._clear_streak = 0

        actionable_started = time.perf_counter()
        actionable = self.bboxesOutsideExitZone(bboxes)
        self.gc.runtime_stats.observePerfMs(
            "classification.rev01.idle.bboxes_outside_exit_ms",
            (time.perf_counter() - actionable_started) * 1000.0,
        )
        self.gc.profiler.observeValue(
            "classification.rev01.idle.actionable_bbox_count",
            float(len(actionable)),
        )
        if not actionable:
            self._presence_streak = 0
            self.setClassificationReady(False, f"{len(bboxes)} piece(s) in exit zone")
            # TODO: wire jitter unstick using self.ctx.config.jitter_* when
            # exit-only dwell exceeds threshold (see GoToAngleFeeding for pattern).
            return None

        self._presence_streak += 1
        self.gc.profiler.observeValue(
            "classification.rev01.idle.presence_streak",
            float(self._presence_streak),
        )
        self.setClassificationReady(False, f"{len(actionable)} bbox(es) on channel")
        if self._presence_streak >= self.ctx.config.presence_streak_to_start:
            self._presence_streak = 0
            self.ctx.reset()
            self.logger.info(
                f"{LOG_TAG} IDLE -> ROTATING_AND_CAPTURING "
                f"(piece confirmed on channel, count={len(actionable)})"
            )
            return ClassificationChannelState.REV01_ROTATING_AND_CAPTURING
        return None

    def cleanup(self) -> None:
        super().cleanup()
        self._presence_streak = 0
        self._clear_streak = 0
