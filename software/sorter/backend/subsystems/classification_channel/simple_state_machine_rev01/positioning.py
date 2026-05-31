import time
from typing import Optional

from defs.known_object import ClassificationStatus, PieceStage
from subsystems.classification_channel.states import ClassificationChannelState

from .base import Rev01BaseState
from .constants import LOG_TAG


class Positioning(Rev01BaseState):
    """Hand the classified piece to distribution and wait for the chute to be
    aimed at its target bin before discharging.

    rev01 owns its own KnownObject; this is the single point where it is handed
    to the transport so the distribution subsystem can look up the bin and aim
    the chute. We block until distribution has both taken ownership of the piece
    (``stage -> distributing``) AND signalled the chute is positioned
    (``distribution_ready`` True), then release to DISCHARGING. Waiting on both
    conditions is monotonic and avoids trusting a stale gate left True by a
    previous cycle. No hard timeout — like the carousel path we hold the piece
    in the channel through no-bin / servo incidents until distribution is ready.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._placed = False
        self._entered_at = 0.0
        self._last_wait_log_ms = 0.0

    def step(self) -> Optional[ClassificationChannelState]:
        self.setClassificationReady(False, "positioning")
        obj = self.ctx.known_object
        now = time.monotonic()

        if obj is None:
            self.logger.warning(
                f"{LOG_TAG} POSITIONING: no known_object — skipping to DISCHARGING"
            )
            return ClassificationChannelState.REV01_DISCHARGING

        if not self._placed:
            self._entered_at = now
            # Distribution only accepts a piece with a routable status. A piece
            # whose classification never resolved (no captures / timeout /
            # error) is still left pending/classifying — coerce it to
            # ``unknown`` so it routes to MISC/discard rather than wedging the
            # handoff (distribution's Idle gate ignores pending pieces).
            if obj.part_id is None and obj.classification_status in (
                ClassificationStatus.pending,
                ClassificationStatus.classifying,
            ):
                obj.classification_status = ClassificationStatus.unknown
            self.transport.placePieceForDistribution(obj)
            self._placed = True
            self.logger.info(
                f"{LOG_TAG} POSITIONING: handed piece {obj.uuid[:8]} to distribution "
                f"(status={obj.classification_status}, part_id={obj.part_id})"
            )

        distribution_ready = bool(self.shared.distribution_ready)
        taken = obj.stage == PieceStage.distributing
        if taken and distribution_ready:
            waited_ms = (now - self._entered_at) * 1000.0
            self.logger.info(
                f"{LOG_TAG} POSITIONING -> DISCHARGING (chute aimed at "
                f"bin={obj.destination_bin} after {waited_ms:.0f}ms)"
            )
            return ClassificationChannelState.REV01_DISCHARGING

        waited_ms = (now - self._entered_at) * 1000.0
        if waited_ms - self._last_wait_log_ms >= 1000.0:
            self._last_wait_log_ms = waited_ms
            self.logger.info(
                f"{LOG_TAG} POSITIONING: waiting for distribution "
                f"(taken={taken}, ready={distribution_ready}, {waited_ms:.0f}ms)"
            )
        return None

    def cleanup(self) -> None:
        super().cleanup()
        self._placed = False
        self._entered_at = 0.0
        self._last_wait_log_ms = 0.0
