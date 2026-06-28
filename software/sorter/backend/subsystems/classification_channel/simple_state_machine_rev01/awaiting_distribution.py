import time
from typing import Optional

from defs.known_object import ClassificationStatus, PieceStage
from subsystems.classification_channel.states import ClassificationChannelState

from .base import Rev01BaseState
from .constants import LOG_TAG


class AwaitingDistribution(Rev01BaseState):
    """Piece is parked in the precise zone. Collect the Brickognize result (it
    ran concurrently with the move here), hand the piece to distribution, and
    wait for the chute to be aimed at its target bin before discharging.

    rev01 owns its own KnownObject; this is the single point where it is handed
    to the transport. We block until distribution has both taken ownership
    (``stage -> distributing``) AND signalled the chute is positioned
    (``distribution_ready`` True). No hard timeout on distribution — like the
    carousel path we hold the piece in the precise band through no-bin / servo
    incidents until distribution is ready; the piece cannot drop from there.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._result_applied = False
        self._placed = False
        self._entered_at = 0.0
        self._last_wait_log_ms = 0.0

    def step(self) -> Optional[ClassificationChannelState]:
        self.setClassificationReady(False, "awaiting_distribution")
        obj = self.ctx.known_object
        now = time.monotonic()

        if obj is None:
            self.logger.warning(
                f"{LOG_TAG} AWAITING_DISTRIBUTION: no known_object — skipping to DISCHARGING"
            )
            return ClassificationChannelState.REV01_DISCHARGING

        if self._entered_at == 0.0:
            self._entered_at = now

        # 1) Apply the classification result. The request was spawned at the end
        #    of CAPTURING and most likely finished during MOVING_TO_PRECISE; if
        #    not, wait here (the piece is safe in the precise band).
        if not self._result_applied:
            with self.ctx.classify_lock:
                result = self.ctx.classification_result
                error = self.ctx.classification_error
            timed_out = (now - self.ctx.classify_started_at) > self.ctx.config.classify_timeout_s
            if result is not None or error is not None:
                elapsed = now - self.ctx.classify_started_at
                if error is not None:
                    self.logger.error(
                        f"{LOG_TAG} Brickognize failed after {elapsed:.2f}s: {error}"
                    )
                else:
                    items = result.get("items", []) if isinstance(result, dict) else []
                    self.logger.info(
                        f"{LOG_TAG} Brickognize returned {len(items)} item(s) in "
                        f"{elapsed:.2f}s; top={items[0] if items else None}"
                    )
                self.updateKnownObjectWithResult(result, error)
                self.dumpBurstCaptureArtifacts(
                    all_captures=list(self.ctx.captured_crops),
                    selected_captures=list(self.ctx.selected_captures),
                    result=result,
                    error=error,
                )
                self._result_applied = True
            elif timed_out:
                self.logger.error(
                    f"{LOG_TAG} Brickognize timed out after "
                    f"{self.ctx.config.classify_timeout_s}s — routing unknown"
                )
                self.updateKnownObjectWithResult(None, "timeout")
                self.dumpBurstCaptureArtifacts(
                    all_captures=list(self.ctx.captured_crops),
                    selected_captures=list(self.ctx.selected_captures),
                    result=None,
                    error="timeout",
                )
                self._result_applied = True
            else:
                waited_ms = (now - self._entered_at) * 1000.0
                if waited_ms - self._last_wait_log_ms >= 1000.0:
                    self._last_wait_log_ms = waited_ms
                    self.logger.info(
                        f"{LOG_TAG} AWAITING_DISTRIBUTION: waiting on classification "
                        f"({waited_ms:.0f}ms)"
                    )
                return None

        # 2) Hand the piece to distribution exactly once.
        if not self._placed:
            if self.ctx.multi_feed_detected:
                obj.part_id = None
                obj.part_name = None
                obj.classification_status = ClassificationStatus.multi_drop_fail
            elif obj.part_id is None and obj.classification_status in (
                ClassificationStatus.pending,
                ClassificationStatus.classifying,
            ):
                obj.classification_status = ClassificationStatus.unknown
            self.transport.placePieceForDistribution(obj)
            self._placed = True
            self._last_wait_log_ms = (now - self._entered_at) * 1000.0
            self.logger.info(
                f"{LOG_TAG} AWAITING_DISTRIBUTION: handed piece {obj.uuid[:8]} to distribution "
                f"(status={obj.classification_status}, part_id={obj.part_id})"
            )

        # 3) Wait for distribution to take ownership AND aim the chute.
        distribution_ready = bool(self.shared.distribution_ready)
        taken = obj.stage == PieceStage.distributing
        if taken and distribution_ready:
            waited_ms = (now - self._entered_at) * 1000.0
            self.logger.info(
                f"{LOG_TAG} AWAITING_DISTRIBUTION -> DISCHARGING (chute aimed at "
                f"bin={obj.destination_bin} after {waited_ms:.0f}ms)"
            )
            return ClassificationChannelState.REV01_DISCHARGING

        waited_ms = (now - self._entered_at) * 1000.0
        if waited_ms - self._last_wait_log_ms >= 1000.0:
            self._last_wait_log_ms = waited_ms
            self.logger.info(
                f"{LOG_TAG} AWAITING_DISTRIBUTION: waiting for distribution "
                f"(taken={taken}, ready={distribution_ready}, {waited_ms:.0f}ms)"
            )
        return None

    def cleanup(self) -> None:
        super().cleanup()
        self._result_applied = False
        self._placed = False
        self._entered_at = 0.0
        self._last_wait_log_ms = 0.0
