import time
from enum import Enum

from defs.known_object import (
    ClassificationStatus,
    KnownObject,
    PieceStage,
    RecognitionImage,
)

from .simple_state_machine_rev01.base import Rev01BaseState
from .simple_state_machine_rev01.constants import C4_TRAVEL_SIGN
from .simple_state_machine_rev01.context import SimpleStateMachineRev01Context

LOG_TAG = "[C4-2PIECE]"

# How far the LEADING piece's gap-to-exit must JUMP UP to conclude the front piece
# has LEFT (dropped) and the waiting piece is now leading. Pieces can't pass each
# other on a rigid one-way platter, so the leading gap only jumps up when the old
# leading piece is gone.
_FRONT_LEFT_JUMP_DEG = 15.0
# Safety: give up a discharge that never resolves (piece stuck at the fall-off).
_DISCHARGE_TIMEOUT_S = 15.0
_DROP_ZONE_CODE = 1  # perception.arcs._region_lookup: 1 = drop


class _Phase(Enum):
    STAGE = "stage"          # rotate the front piece's COM forward into precise
    PROCESS = "process"      # apply result + aim chute; wait for the back piece
    DISCHARGE = "discharge"  # push the front into the fall-off; it drops


class TwoPieceClassificationChannel(Rev01BaseState):
    """Hold up to two pieces on the classification channel: one staged in precise
    being processed, one captured in the drop zone. Platter only ever turns
    CLOCKWISE (forward); no move is reversed. Single-piece SIMPLE_STATE_MACHINE_REV01
    is untouched."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._deps = args[:7]
        self._phase = _Phase.STAGE
        self._placed = False
        self._result_applied = False
        self._front_exit_gap = None
        self._discharge_started_at = 0.0
        self._incoming = Rev01BaseState(*self._deps, SimpleStateMachineRev01Context())
        self.ctx.reset()
        self.ctx.known_object = None

    # ------------------------------------------------------------------ main

    def step(self) -> None:
        perception_service = getattr(self.gc, "perception_service", None)
        if perception_service is None:
            return
        state = perception_service.read_state(4)
        stepper = getattr(self.irl, "carousel_stepper", None)
        stopped = bool(getattr(stepper, "stopped", True))

        self.setClassificationReady(
            (not state.in_drop) and stopped, "drop clear + stopped (two-piece)"
        )

        # Concurrently photograph + classify whatever is waiting in the DROP zone,
        # whenever the platter is stopped.
        if stopped:
            self._captureIncoming(perception_service, state)

        # No front piece staged? Promote the captured incoming piece (if any).
        if self.ctx.known_object is None:
            self._promoteIfReady()
            if self.ctx.known_object is None:
                return

        if self._phase == _Phase.STAGE:
            self._stage(state, stopped)
        elif self._phase == _Phase.PROCESS:
            self._process(state)
        elif self._phase == _Phase.DISCHARGE:
            self._discharge(state, stopped)

    # ------------------------------------------------- incoming (drop) capture

    def _captureIncoming(self, perception_service, state) -> None:
        inc = self._incoming.ctx
        if inc.classify_started_at != 0.0:
            return  # already captured + classifying
        drop_bbox = self._zoneBbox(state, _DROP_ZONE_CODE)
        if drop_bbox is None:
            return
        raw = perception_service.read_bboxes_and_frame(4)
        if raw is None:
            return
        _bboxes, perc_frame = raw
        now = time.monotonic()
        if inc.capturing_started_at == 0.0:
            inc.capturing_started_at = now
            inc.known_object = KnownObject(
                stage=PieceStage.created,
                classification_status=ClassificationStatus.pending,
                first_carousel_seen_ts=time.time(),
            )
            self._incoming.emitKnownObject()
            self.logger.info(f"{LOG_TAG} capturing incoming drop-zone piece (concurrent)")
        self._cropBurstFrame(self._incoming, drop_bbox, perc_frame)
        n = len(inc.captured_crops)
        done, reason = self._incoming.burstCaptureComplete(inc, now)
        if done:
            inc.classify_started_at = now
            caps = list(inc.captured_crops)
            if caps:
                self._incoming.spawnClassifyThread(caps)
            else:
                inc.classification_error = "no_captures"
            best_sharp = max(inc.captured_crop_sharpness, default=0.0)
            self.logger.info(
                f"{LOG_TAG} incoming piece classifying off-thread "
                f"({n} crops, stop={reason}, best_sharp={best_sharp:.0f}, "
                f"floor={inc.config.min_sharpness_laplacian_var:.0f})"
            )

    def _promoteIfReady(self) -> None:
        inc = self._incoming.ctx
        if inc.known_object is None:
            return
        # Never promote (and therefore never STAGE the piece out of the drop zone)
        # until its at-rest burst capture has COMPLETED. classify_started_at is set
        # the instant the burst finishes, so it doubles as the capture-done flag.
        if inc.classify_started_at == 0.0:
            return
        # Hand the incoming context over to the front. Its classify thread keeps a
        # reference to inc, so it keeps writing to this same context — now the
        # front's. Spin up a FRESH worker for the next incoming piece.
        self.ctx = inc
        self._incoming = Rev01BaseState(*self._deps, SimpleStateMachineRev01Context())
        self._placed = False
        self._result_applied = False
        self._front_exit_gap = None
        self._discharge_started_at = 0.0
        self._phase = _Phase.STAGE
        self.logger.info(f"{LOG_TAG} promoted incoming piece to FRONT (already classifying)")

    # --------------------------------------------------------- front lifecycle

    def _stage(self, state, stopped: bool) -> None:
        # Advance the front piece's COM FORWARD into the precise zone. FORWARD ONLY.
        gap = state.exit_com_forward_to_precise_deg
        if gap is None:
            return
        if gap <= self.ctx.config.precise_center_tolerance_deg:
            if stopped:
                self._phase = _Phase.PROCESS
                self.logger.info(f"{LOG_TAG} STAGE -> PROCESS (front at/past precise, gap={gap:.0f})")
            return
        if stopped:
            move = min(gap, self.ctx.config.discharge_max_move_output_deg)
            self.startOutputMove(
                C4_TRAVEL_SIGN * move,
                self.ctx.config.precise_converge_speed_usteps_per_s,
            )
            self.logger.info(f"{LOG_TAG} STAGE move {move:.0f}deg (gap_to_precise={gap:.0f})")

    def _process(self, state) -> None:
        obj = self.ctx.known_object
        if obj is None:
            self._phase = _Phase.DISCHARGE
            return
        now = time.monotonic()
        if not self._result_applied:
            with self.ctx.classify_lock:
                result = self.ctx.classification_result
                error = self.ctx.classification_error
            if result is not None or error is not None:
                self.updateKnownObjectWithResult(result, error)
                self._result_applied = True
            elif (now - self.ctx.classify_started_at) > self.ctx.config.classify_timeout_s:
                self.logger.error(f"{LOG_TAG} classify timed out — routing unknown")
                self.updateKnownObjectWithResult(None, "timeout")
                self._result_applied = True
            else:
                return  # classification still running; piece is safe in precise
        if not self._placed:
            if obj.part_id is None and obj.classification_status in (
                ClassificationStatus.pending,
                ClassificationStatus.classifying,
            ):
                obj.classification_status = ClassificationStatus.unknown
            self.transport.placePieceForDistribution(obj)
            self._placed = True
            self.logger.info(
                f"{LOG_TAG} PROCESS handed piece {obj.uuid[:8]} to distribution "
                f"(status={obj.classification_status})"
            )
        chute_aimed = bool(self.shared.distribution_ready) and obj.stage == PieceStage.distributing
        back_present = bool(state.in_drop)
        if chute_aimed and back_present:
            self._front_exit_gap = None
            self._discharge_started_at = now
            self._phase = _Phase.DISCHARGE
            self.logger.info(
                f"{LOG_TAG} PROCESS -> DISCHARGE (chute aimed + back in drop, "
                f"bin={obj.destination_bin})"
            )

    def _discharge(self, state, stopped: bool) -> None:
        # Eject ONLY the front (leading) piece. It has LEFT once it's no longer the
        # leading piece — the channel empties OR the leading gap JUMPS UP to the
        # waiting piece. STOP the instant that happens so the waiting piece is never
        # carried into the fall-off.
        pieces = getattr(state, "pieces", ())
        front_gap = pieces[0].com_forward_to_exit_deg if pieces else None
        front_left = front_gap is None or (
            self._front_exit_gap is not None
            and front_gap > self._front_exit_gap + _FRONT_LEFT_JUMP_DEG
        )
        timed_out = (
            self._discharge_started_at > 0.0
            and (time.monotonic() - self._discharge_started_at) > _DISCHARGE_TIMEOUT_S
        )
        if front_left or timed_out:
            if timed_out and not front_left:
                self.logger.warning(
                    f"{LOG_TAG} DISCHARGE timed out (front never left) — giving up"
                )
            prev_gap = self._front_exit_gap
            self.transport.advanceTransport()  # commit the front to distribution
            self.ctx.known_object = None  # front gone; next promote() stages the back
            self._placed = False
            self._result_applied = False
            self._front_exit_gap = None
            self._discharge_started_at = 0.0
            self._phase = _Phase.STAGE
            self.logger.info(
                f"{LOG_TAG} DISCHARGE done (front left; prev_lead_gap="
                f"{None if prev_gap is None else round(prev_gap, 1)}, new_lead_gap="
                f"{None if front_gap is None else round(front_gap, 1)})"
            )
            return
        self._front_exit_gap = front_gap
        gap_to_center = state.exit_com_forward_to_center_deg
        if (
            stopped
            and gap_to_center is not None
            and gap_to_center > self.ctx.config.discharge_center_tolerance_deg
        ):
            move = max(0.0, min(self.ctx.config.discharge_max_move_output_deg, gap_to_center))
            self.startOutputMove(
                C4_TRAVEL_SIGN * move, self.ctx.config.discharge_speed_usteps_per_s
            )
            self.logger.info(f"{LOG_TAG} DISCHARGE move {move:.0f}deg (gap_to_center={gap_to_center:.0f})")

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _zoneBbox(state, zone_code: int):
        for p in getattr(state, "pieces", ()):
            if p.zone_code == zone_code:
                b = p.bbox
                if b and b[2] > b[0] and b[3] > b[1]:
                    return b
        return None

    def _cropBurstFrame(self, worker, bbox, perc_frame) -> None:
        ctx = worker.ctx
        if perc_frame.bgr is None or bbox is None:
            return
        frame_ts = float(perc_frame.timestamp)
        if frame_ts <= ctx.last_capture_frame_ts:
            return
        crop = self.cv.cropBbox(perc_frame.bgr, bbox, ctx.config.crop_padding_px)
        if crop is None:
            return
        sharp = self.sharpness(crop)
        ctx.captured_crops.append(crop)
        ctx.captured_crop_sharpness.append(sharp)
        ctx.last_capture_frame_ts = frame_ts
        obj = ctx.known_object
        if obj is not None:
            encoded = self.encodeFrame(crop)
            if encoded is not None:
                obj.latest_captured_crop = encoded
                obj.latest_captured_crop_ts = frame_ts
                obj.recognition_image_set.append(
                    RecognitionImage(
                        image=encoded,
                        source="c4_burst",
                        used=False,
                        ts=frame_ts,
                        channel=4,
                        created_at=frame_ts,
                        sharpness=sharp,
                    )
                )
            worker.emitKnownObject()

    def cleanup(self) -> None:
        self.abandonInFlightObject("two-piece classification channel teardown")
        try:
            self._incoming.abandonInFlightObject("two-piece teardown")
        except Exception:
            pass
        self.ctx.reset()
        self.ctx.known_object = None
        self._incoming = Rev01BaseState(*self._deps, SimpleStateMachineRev01Context())
        self._phase = _Phase.STAGE
        self._placed = False
        self._result_applied = False
        self._front_exit_gap = None
        self._discharge_started_at = 0.0
