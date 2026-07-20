import base64
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from classification.brickognize import MAX_QUERY_IMAGES, _classifyImages
from classification.providers import (
    COLOR_PROVIDER_BRICKOGNIZE,
    COLOR_PROVIDER_HIVE_BASICALLY,
    MOLD_PROVIDER_BRICKOGNIZE,
)
from defs.known_object import (
    ClassificationAttempt,
    ClassificationAttemptStrategy,
    ClassificationStatus,
    PieceStage,
    RecognitionImage,
)
from global_config import GlobalConfig
from irl.config import IRLConfig, IRLInterface
from piece_transport import ClassificationChannelTransport
from states.base_state import BaseState
from subsystems.classification_channel.five_sector_platter import C4FiveSectorPlatter
from subsystems.shared_variables import SharedVariables
from utils.event import knownObjectToEvent

from .constants import HOSTED_COLOR_JOIN_BUDGET_S, LOG_TAG
from .context import SimpleStateMachineRev01Context
from .vision import Rev01Vision


@dataclass
class _SendImage:
    # One image eligible to be sent to Brickognize, paired with the
    # RecognitionImage that represents it on the KnownObject so a retry strategy
    # can both drop the BGR from the request AND flag the corresponding entry.
    bgr: np.ndarray
    rec: RecognitionImage


@dataclass
class _ClassifyRequest:
    # One Brickognize call: a labelled subset of the sendable images. All requests
    # for a piece are submitted in PARALLEL (redundant, not sequential retries)
    # and the highest-confidence one that comes back wins.
    strategy: ClassificationAttemptStrategy
    label: str
    images: list[_SendImage]


class Rev01BaseState(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        shared: SharedVariables,
        transport: ClassificationChannelTransport,
        vision,
        event_queue,
        context: SimpleStateMachineRev01Context,
    ):
        super().__init__(irl, gc)
        self.irl_config = irl_config
        self.shared = shared
        self.transport = transport
        self.event_queue = event_queue
        self.ctx = context
        self.cc_config = irl_config.classification_channel_config
        self.cv = Rev01Vision(vision, gc)

    def setClassificationReady(self, ready: bool, reason: str) -> None:
        setter = getattr(self.shared, "set_classification_gate", None)
        getter = getattr(self.shared, "get_classification_ready", None)
        prev = bool(getter()) if callable(getter) else None
        if callable(setter):
            setter(ready, reason=reason)
        else:
            self.shared.classification_ready = ready
        # Log only on transition. This fires every tick; logging it
        # unconditionally was a main-thread log-flood source.
        if prev is None or prev != bool(ready):
            self.logger.info(f"{LOG_TAG} classification_ready -> {ready} ({reason})")

    def stopStepper(self) -> None:
        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is None or not hasattr(stepper, "move_at_speed"):
            return
        try:
            if bool(getattr(stepper, "stopped", False)):
                return
            stepper.move_at_speed(0)
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} stepper stop failed: {exc}")

    def startRotation(self, speed_usteps_per_s: int) -> bool:
        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is None:
            self.logger.error(f"{LOG_TAG} carousel_stepper missing — cannot rotate")
            return False
        try:
            stepper.set_speed_limits(16, max(16, speed_usteps_per_s))
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} set_speed_limits failed: {exc}")
        try:
            ok = bool(stepper.move_at_speed(int(speed_usteps_per_s)))
        except Exception as exc:
            self.logger.error(f"{LOG_TAG} move_at_speed failed: {exc}")
            return False
        if not ok:
            self.logger.error(f"{LOG_TAG} move_at_speed not acknowledged")
        return ok

    def startOutputMove(self, output_degrees: float, speed_usteps_per_s: int) -> bool:
        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is None:
            self.logger.error(f"{LOG_TAG} carousel_stepper missing — cannot move")
            return False
        try:
            stepper.set_speed_limits(16, max(16, speed_usteps_per_s))
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} set_speed_limits failed: {exc}")
        try:
            platter = C4FiveSectorPlatter.from_irl_config(self.irl_config)
            move_steps = platter.output_degrees_to_motor_microsteps(output_degrees)
            ok = bool(stepper.move_steps(int(move_steps)))
        except Exception as exc:
            self.logger.error(f"{LOG_TAG} sweep move failed: {exc}")
            return False
        if not ok:
            self.logger.error(f"{LOG_TAG} move not acknowledged")
        return ok

    def startCaptureSweepMove(self, output_degrees: float, speed_usteps_per_s: int) -> bool:
        return self.startOutputMove(output_degrees, speed_usteps_per_s)

    def emitKnownObject(self) -> None:
        obj = self.ctx.known_object
        if obj is None:
            return
        obj.updated_at = time.time()
        self.event_queue.put(knownObjectToEvent(obj))

    def abandonInFlightObject(self, reason: str) -> None:
        # A piece was photographed (emitted to the UI with a crop) but its cycle
        # is being torn down before it ever classified or distributed — machine
        # stop, or a reset mid-capture. Mark it aborted and emit a final update
        # so the UI drops it instead of leaving it stuck in "capturing" forever.
        # No-op for finalized pieces (already classified/distributed) and pieces
        # that never started capturing.
        obj = self.ctx.known_object
        if obj is None or obj.aborted:
            return
        terminal_status = obj.classification_status not in (
            ClassificationStatus.pending,
            ClassificationStatus.classifying,
        )
        already_distributed = (
            obj.stage == PieceStage.distributed or obj.distributed_at is not None
        )
        if terminal_status or already_distributed:
            return
        obj.aborted = True
        self.logger.info(f"{LOG_TAG} abandoning in-flight piece {obj.uuid[:8]} ({reason})")
        self.emitKnownObject()

    @staticmethod
    def encodeFrame(frame: np.ndarray) -> Optional[str]:
        # Quality 90: these crops are persisted to disk (piece_image_store) and
        # eventually synced to the Hive for training, so keep them near-lossless.
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            return None
        return base64.b64encode(buf).decode("utf-8")

    @staticmethod
    def sharpness(frame: np.ndarray) -> float:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    @staticmethod
    def burstCaptureComplete(ctx, now: float) -> tuple[bool, str]:
        # Shared stop condition for the at-rest burst (single-piece CAPTURING and
        # the two-piece incoming worker). With require_sharp_capture on, keep
        # grabbing frames until at least one crop clears the motion-blur floor,
        # bounded by max_captures and capture_max_wait_ms; otherwise fall back to
        # the old fixed window (capture_at_rest_ms / max_captures). Returns
        # (done, reason) so callers can log why the burst ended.
        cfg = ctx.config
        n = len(ctx.captured_crops)
        if n <= 0:
            return False, ""
        elapsed_ms = (now - ctx.capturing_started_at) * 1000.0
        if not getattr(cfg, "require_sharp_capture", False):
            if n >= cfg.max_captures:
                return True, "frame_cap"
            if elapsed_ms >= cfg.capture_at_rest_ms:
                return True, "window"
            return False, ""
        floor = float(cfg.min_sharpness_laplacian_var)
        if any(s >= floor for s in ctx.captured_crop_sharpness):
            return True, "sharp"
        if n >= cfg.max_captures:
            return True, "frame_cap"
        if elapsed_ms >= float(cfg.capture_max_wait_ms):
            return True, "time_cap"
        return False, ""

    def _selectBurstIndices(self, crops: list[np.ndarray], n_use: int) -> list[int]:
        # Which burst frames drive classification. With require_sharp_capture on,
        # the SHARPEST n_use crops (least motion blur); otherwise the last n_use
        # (most-settled tail) to preserve the legacy behavior. Returned in capture
        # order so the anchors/sent images stay chronological.
        total = len(crops)
        n = max(1, min(int(n_use), total)) if total else 0
        if n == 0:
            return []
        cfg = self.ctx.config
        sharp = self.ctx.captured_crop_sharpness
        if getattr(cfg, "require_sharp_capture", False) and len(sharp) == total:
            order = sorted(range(total), key=lambda i: sharp[i], reverse=True)
        else:
            order = list(reversed(range(total)))
        return sorted(order[:n])

    def anyBboxInExitZone(
        self, bboxes: list[tuple[int, int, int, int]]
    ) -> tuple[bool, list[float]]:
        center = self.cv.channelCenter()
        if center is None:
            return False, []
        angles = [self.cv.bboxAngleDeg(b, center) for b in bboxes]
        hit = any(
            self.cv.bboxInExitZone(
                b, center, self.cc_config.drop_angle_deg, self.cc_config.drop_tolerance_deg
            )
            for b in bboxes
        )
        return hit, angles

    def computeDischargeOutputDeg(
        self, bbox: tuple[int, int, int, int]
    ) -> Optional[float]:
        center = self.cv.channelCenter()
        if center is None:
            return None
        piece_angle = self.cv.bboxAngleDeg(bbox, center)
        target_angle = (
            float(self.cc_config.drop_angle_deg)
            + float(self.cc_config.drop_tolerance_deg)
        ) % 360.0
        delta = (target_angle - piece_angle) % 360.0
        return max(2.0, min(delta, 270.0))

    def bboxesOutsideExitZone(
        self, bboxes: list[tuple[int, int, int, int]]
    ) -> list[tuple[int, int, int, int]]:
        center = self.cv.channelCenter()
        if center is None:
            return list(bboxes)
        return [
            b
            for b in bboxes
            if not self.cv.bboxInExitZone(
                b,
                center,
                self.cc_config.drop_angle_deg,
                self.cc_config.drop_tolerance_deg,
            )
        ]

    # ---- Brickognize classification helpers ----
    # Shared by CAPTURING (which spawns the request) and AWAITING_DISTRIBUTION
    # (which applies the result) — the spawn/apply split spans two states, and
    # all handoff flows through ``self.ctx``.

    def selectRecognitionCrops(self, crops: list[np.ndarray]) -> list[np.ndarray]:
        # Hard-cap at the Brickognize per-request image limit regardless of the
        # configured max_captures — over the limit the API errors the whole call.
        n = min(self.ctx.config.max_captures, MAX_QUERY_IMAGES)
        if n <= 0 or not crops:
            return []
        if len(crops) <= n:
            return list(crops)
        last_index = len(crops) - 1
        chosen_indices: list[int] = []
        for slot_idx in range(n):
            capture_idx = round((slot_idx * last_index) / max(1, n - 1))
            if chosen_indices and capture_idx <= chosen_indices[-1]:
                capture_idx = min(last_index, chosen_indices[-1] + 1)
            chosen_indices.append(capture_idx)
        return [crops[idx] for idx in chosen_indices]

    def spawnClassifyThread(self, all_captures: list[np.ndarray]) -> None:
        # Runs entirely off the state-machine thread: the Brickognize fan-out is
        # blocking HTTP and MUST NOT run on the main loop. Fires the parallel
        # request fan-out (the combined call plus single-image calls). The
        # combined call's result is kept whenever it recognizes the piece at all;
        # otherwise the highest-confidence single-image call wins (see
        # _runClassifyRequests).
        obj = self.ctx.known_object
        piece_uuid = obj.uuid if obj is not None else None
        # classify_burst_count frames drive classification: they are the C4 images
        # sent to Brickognize. _selectBurstIndices picks the sharpest (least
        # motion-blurred) frames when require_sharp_capture is on, the most-settled
        # tail otherwise. The rest of the burst is kept on the KnownObject
        # (used=False) for review.
        n_use = max(1, int(self.ctx.config.classify_burst_count))
        burst_entries = (
            [r for r in obj.recognition_image_set if r.source == "c4_burst"]
            if obj is not None
            else []
        )
        chosen = [i for i in self._selectBurstIndices(all_captures, n_use) if i < len(burst_entries)]
        used_entries = [burst_entries[i] for i in chosen]
        burst_crops = [all_captures[i] for i in chosen]

        def _run() -> None:
            try:
                # Pair each sendable image with its RecognitionImage.
                sendable: list[_SendImage] = [
                    _SendImage(bgr, rec) for bgr, rec in zip(burst_crops, used_entries)
                ]
                if not sendable:
                    with self.ctx.classify_lock:
                        self.ctx.classification_error = "no_captures"
                    return
                # The hosted color provider (when selected) runs alongside the
                # Brickognize fan-out rather than after it, so choosing it costs
                # no extra wall-clock unless it is slower than Brickognize.
                hosted_color = self._maybeStartHostedColorPredict(sendable, piece_uuid)
                requests = self._buildClassifyRequests(sendable)
                self._runClassifyRequests(requests, piece_uuid, hosted_color)
            except Exception as exc:
                with self.ctx.classify_lock:
                    self.ctx.classification_error = str(exc)

        thread = threading.Thread(target=_run, daemon=True)
        self.ctx.classify_thread = thread
        thread.start()

    def _buildClassifyRequests(self, sendable: list[_SendImage]) -> list[_ClassifyRequest]:
        # The parallel request fan-out. All of these are submitted at once; the
        # highest-confidence result wins (see _runClassifyRequests). They are
        # redundant, not sequential retries — a lone clean frame frequently
        # recognizes a piece the fused set confuses, and firing every variant
        # concurrently costs the same wall-clock as the slowest single call.
        #   combined        — the full set of used burst frames
        #   single_burst    — only the last (most-settled) burst frame, alone
        # A single-image request equal to the combined call (e.g. combined is
        # already just one burst frame) is skipped so we never pay for a duplicate.
        burst = [s for s in sendable if s.rec.source == "c4_burst"]
        requests: list[_ClassifyRequest] = [
            _ClassifyRequest(
                ClassificationAttemptStrategy.combined, "combined", list(sendable)
            )
        ]
        cfg = self.ctx.config
        if getattr(cfg, "classify_parallel_single_burst", True) and burst:
            last_burst = burst[-1]
            if not (len(sendable) == 1 and sendable[0] is last_burst):
                requests.append(
                    _ClassifyRequest(
                        ClassificationAttemptStrategy.single_burst,
                        "single_burst",
                        [last_burst],
                    )
                )
        return requests

    @staticmethod
    def _topItem(result: object) -> Optional[dict]:
        items = result.get("items", []) if isinstance(result, dict) else []
        return items[0] if items else None

    @staticmethod
    def _topColor(result: object) -> Optional[dict]:
        colors = result.get("colors", []) if isinstance(result, dict) else []
        valid = [c for c in colors if isinstance(c, dict)]
        if not valid:
            return None
        return max(valid, key=lambda c: c.get("score", 0))

    def _runRequestsParallel(
        self, requests: list[_ClassifyRequest], piece_uuid: Optional[str]
    ) -> list[tuple[_ClassifyRequest, Optional[dict], Optional[str], float]]:
        # Submit every request concurrently (one thread each) and wait for all to
        # return. A single request runs inline — no thread overhead. Each tuple is
        # (request, result|None, error|None, duration_s).
        out: list[Optional[tuple[_ClassifyRequest, Optional[dict], Optional[str], float]]] = [
            None
        ] * len(requests)

        def work(i: int, req: _ClassifyRequest) -> None:
            t0 = time.monotonic()
            try:
                result = _classifyImages(
                    self.gc,
                    [s.bgr for s in req.images],
                    piece_uuid=piece_uuid,
                    dump_label=req.label,
                )
                out[i] = (req, result if isinstance(result, dict) else None, None, time.monotonic() - t0)
            except Exception as exc:
                out[i] = (req, None, str(exc), time.monotonic() - t0)

        if len(requests) == 1:
            work(0, requests[0])
        else:
            threads = [
                threading.Thread(target=work, args=(i, req), daemon=True)
                for i, req in enumerate(requests)
            ]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
        return [r for r in out if r is not None]

    def _maybeStartHostedColorPredict(
        self, sendable: list[_SendImage], piece_uuid: Optional[str]
    ) -> Optional[dict]:
        # Fires the hosted color request on its own thread so it overlaps the
        # Brickognize fan-out. Returns None (and costs nothing) unless a hosted
        # provider is actually selected.
        # Imported lazily: basically_services pulls in local_state, and this
        # module is imported by the state machine at boot.
        import basically_services
        from toml_config import getClassificationProviders

        if getClassificationProviders()["color_provider"] != COLOR_PROVIDER_HIVE_BASICALLY:
            return None
        holder: dict = {"started_at": time.monotonic()}

        def run() -> None:
            blobs: list[bytes] = []
            channels: list[int] = []
            for s in sendable:
                ok, buf = cv2.imencode(".jpg", s.bgr)
                if not ok:
                    continue
                blobs.append(buf.tobytes())
                # Everything sent is a C4 burst frame.
                channels.append(4)
            if not blobs:
                return
            try:
                result = basically_services.predictColor(
                    self.gc,
                    blobs,
                    channels,
                    client_info={"piece_uuid": piece_uuid} if piece_uuid else None,
                )
            except Exception as exc:
                self.logger.warning(f"{LOG_TAG} hosted color predict failed: {exc}")
                return
            if result is not None:
                holder["result"] = result

        thread = threading.Thread(target=run, daemon=True, name="hosted-color-predict")
        holder["thread"] = thread
        thread.start()
        return holder

    def _resolveHostedColor(self, hosted_color: Optional[dict]) -> None:
        # Joins the hosted request within its budget and records BOTH the color
        # override and which provider actually answered. A timeout or a bad
        # payload is not an error: the piece keeps Brickognize's color and is
        # recorded as brickognize-sourced, so the stored provenance always
        # reflects what really produced the color rather than what was configured.
        if hosted_color is None:
            self.ctx.color_provider = COLOR_PROVIDER_BRICKOGNIZE
            self.ctx.hosted_color = None
            return
        remaining = max(
            0.0,
            HOSTED_COLOR_JOIN_BUDGET_S - (time.monotonic() - hosted_color["started_at"]),
        )
        hosted_color["thread"].join(remaining)
        result = hosted_color.get("result")
        color_id = result.get("color_id") if isinstance(result, dict) else None
        color_name = result.get("color_name") if isinstance(result, dict) else None
        if color_id is None or not color_name:
            self.ctx.color_provider = COLOR_PROVIDER_BRICKOGNIZE
            self.ctx.hosted_color = None
            self.logger.info(
                f"{LOG_TAG} hosted color unavailable within "
                f"{HOSTED_COLOR_JOIN_BUDGET_S:.0f}s — falling back to Brickognize's color"
            )
            return
        # Hive returns BrickLink color ids as ints; the sorting profile (and
        # Brickognize) key on the same ids as strings.
        self.ctx.color_provider = COLOR_PROVIDER_HIVE_BASICALLY
        self.ctx.hosted_color = (str(color_id), str(color_name))
        self.logger.info(
            f"{LOG_TAG} hosted color applied: {color_name} ({color_id})"
        )

    def _runClassifyRequests(
        self,
        requests: list[_ClassifyRequest],
        piece_uuid: Optional[str],
        hosted_color: Optional[dict] = None,
    ) -> None:
        # Fire every request concurrently and apply one result. No sequential
        # retries: the calls are redundant and run in parallel. The combined
        # (full burst set) call is preferred whenever it recognizes the
        # piece at all — it has the most context, so we trust it over a
        # higher-confidence lone-image call. Only if combined came back empty does
        # the highest-confidence single-image call win. The applied request's
        # images become the "used" set; every other sent image is thrown out
        # (excluded_from_result).
        # If a request errored but another returned, we just ignore the error. Only
        # when EVERY request errors (a transport failure across the board) is the
        # piece marked errored — a smaller image set can't fix a network failure.
        results = self._runRequestsParallel(requests, piece_uuid)
        attempts: list[ClassificationAttempt] = []
        # ClassificationAttempt <-> the request that produced it, so the applied
        # one can be flagged in _finalizeAttempts.
        attempt_reqs: list[_ClassifyRequest] = []
        # Requests that returned an item, with the top score, to pick the winner.
        found: list[tuple[_ClassifyRequest, dict, float]] = []
        # First non-error result, applied as the no-recognition fallback.
        fallback: Optional[tuple[_ClassifyRequest, dict]] = None
        errors: list[str] = []

        for req, result, error, dur in results:
            top = self._topItem(result)
            top_color = self._topColor(result)
            attempts.append(
                ClassificationAttempt(
                    strategy=req.strategy,
                    label=req.label,
                    n_burst=sum(1 for s in req.images if s.rec.source == "c4_burst"),
                    found=top is not None,
                    part_id=top.get("id") if isinstance(top, dict) else None,
                    part_name=top.get("name") if isinstance(top, dict) else None,
                    preview_url=top.get("img_url") if isinstance(top, dict) else None,
                    confidence=top.get("score") if isinstance(top, dict) else None,
                    color_id=(
                        str(top_color.get("id"))
                        if isinstance(top_color, dict) and top_color.get("id") is not None
                        else None
                    ),
                    color_name=(
                        str(top_color.get("name"))
                        if isinstance(top_color, dict) and top_color.get("name") is not None
                        else None
                    ),
                    error=error,
                    duration_s=dur,
                    image_ts=[
                        s.rec.ts for s in req.images if s.rec.ts is not None
                    ],
                    listing_id=(
                        result.get("listing_id") if isinstance(result, dict) else None
                    ),
                    item_rank=(
                        top.get("rank") if isinstance(top, dict) else None
                    ),
                    item_type=(
                        top.get("type") if isinstance(top, dict) else None
                    ),
                    color_rank=(
                        top_color.get("rank") if isinstance(top_color, dict) else None
                    ),
                )
            )
            attempt_reqs.append(req)
            if error is not None:
                errors.append(error)
                self.logger.warning(
                    f"{LOG_TAG} request [{req.label}] transport error: {error}"
                )
                continue
            if result is not None and fallback is None:
                fallback = (req, result)
            if top is not None and result is not None:
                score = top.get("score") if isinstance(top, dict) else None
                found.append((req, result, float(score) if score is not None else -1.0))

        applied: Optional[tuple[_ClassifyRequest, dict]] = None
        if found:
            # Prefer the combined (full burst set) request whenever it
            # recognized the piece at all — it sees the most context, so we trust
            # any result it returns over a higher-confidence lone-image call. Only
            # when the combined call came back empty do we fall back to the
            # highest-confidence single-image request.
            combined_hit = next(
                (
                    f
                    for f in found
                    if f[0].strategy == ClassificationAttemptStrategy.combined
                ),
                None,
            )
            if combined_hit is not None:
                best_req, best_result, best_score = combined_hit
                self.logger.info(
                    f"{LOG_TAG} classify winner [{best_req.label}] @ {best_score:.2f} "
                    f"(combined recognized the piece; "
                    f"{len(found)}/{len(requests)} requests recognized it)"
                )
            else:
                best_req, best_result, best_score = max(found, key=lambda x: x[2])
                self.logger.info(
                    f"{LOG_TAG} classify winner [{best_req.label}] @ {best_score:.2f} "
                    f"(combined missed; highest-confidence fallback; "
                    f"{len(found)}/{len(requests)} requests recognized the piece)"
                )
            applied = (best_req, best_result)
        elif fallback is not None:
            applied = fallback
            self.logger.info(
                f"{LOG_TAG} no request recognized the piece — applying not_found"
            )
        else:
            with self.ctx.classify_lock:
                self.ctx.classification_error = errors[0] if errors else "no_result"
            self.logger.warning(
                f"{LOG_TAG} all {len(requests)} classify requests errored"
            )

        # MUST settle before _finalizeAttempts publishes classification_result:
        # AWAITING_DISTRIBUTION polls for that field, not for this thread, so a
        # provider resolved afterwards could miss the piece entirely.
        self._resolveHostedColor(hosted_color)
        self.ctx.mold_provider = MOLD_PROVIDER_BRICKOGNIZE
        self._finalizeAttempts(requests, attempts, attempt_reqs, applied)

    def _finalizeAttempts(
        self,
        requests: list[_ClassifyRequest],
        attempts: list[ClassificationAttempt],
        attempt_reqs: list[_ClassifyRequest],
        applied: Optional[tuple[_ClassifyRequest, dict]],
    ) -> None:
        # Apply the winning request if one recognized the piece; otherwise fall
        # back to the first no-recognition result (its image set becomes the
        # "used" set). Every sendable image either drove the applied request
        # (used=True) or was sent in a losing request and thrown out
        # (excluded_from_result=True). Images never sent stay used=False. The
        # applied request's attempt record is flagged so the UI need not re-derive
        # it. requests[0] is the combined call, which holds the full sendable set.
        applied_req = applied[0] if applied is not None else None
        full = requests[0].images if requests else []
        winning_subset = applied_req.images if applied_req is not None else full
        winning_ids = {id(s) for s in winning_subset}
        for s in full:
            in_winner = id(s) in winning_ids
            s.rec.used = in_winner
            s.rec.excluded_from_result = not in_winner
        for att, req in zip(attempts, attempt_reqs):
            att.applied = req is applied_req
        strategy = applied_req.strategy if applied_req is not None else (
            requests[0].strategy if requests else ClassificationAttemptStrategy.combined
        )
        winner_result = applied[1] if applied is not None else None
        with self.ctx.classify_lock:
            self.ctx.classification_attempts = list(attempts)
            self.ctx.classification_strategy = strategy
            self.ctx.selected_captures = [
                s.bgr for s in winning_subset if s.rec.source == "c4_burst"
            ]
            if winner_result is not None:
                self.ctx.classification_result = winner_result
        self.logger.info(
            f"{LOG_TAG} classify done: applied [{strategy.value}] "
            f"(attempts={[(a.label, a.found) for a in attempts]})"
        )

    def updateKnownObjectWithResult(self, result: object, error: Optional[str]) -> None:
        obj = self.ctx.known_object
        if obj is None:
            return

        frames = list(self.ctx.captured_crops)

        obj.request_failed = False
        if error is not None:
            # A transport error (Brickognize timeout / DNS / connection failure on
            # a flaky network) means the request failed, not that the piece is
            # unidentifiable — a distinct `failed` status so it never renders as
            # classified. The local-pipeline sentinels ("no_captures"/"no_result")
            # are not network failures, so they stay plain "unknown". The
            # request_failed flag is kept for compat with existing consumers.
            if error in ("no_captures", "no_result"):
                obj.classification_status = ClassificationStatus.unknown
            else:
                obj.classification_status = ClassificationStatus.failed
                obj.request_failed = True
        elif isinstance(result, dict):
            items = result.get("items", [])
            colors = result.get("colors", [])
            # Correction provenance from the applied request: the search id, so a
            # later user correction can be submitted to Brickognize's feedback API
            # without re-querying. Per-result ranks are set alongside the applied
            # item/color below.
            obj.brickognize_listing_id = result.get("listing_id")
            if items:
                best = items[0]
                obj.part_id = best.get("id")
                obj.part_name = best.get("name")
                obj.part_category = best.get("category")
                obj.confidence = best.get("score")
                obj.brickognize_preview_url = best.get("img_url")
                obj.brickognize_item_rank = best.get("rank")
                obj.brickognize_item_type = best.get("type")
                obj.classification_status = ClassificationStatus.classified
            else:
                obj.classification_status = ClassificationStatus.not_found
            if colors:
                best_color = max(colors, key=lambda c: c.get("score", 0))
                obj.color_id = str(best_color.get("id", "any_color"))
                obj.color_name = str(best_color.get("name", "Any Color"))
                obj.brickognize_color_rank = best_color.get("rank")
            # A hosted provider's answer overrides Brickognize's color (the
            # per-attempt records keep Brickognize's, so both remain visible).
            if self.ctx.hosted_color is not None:
                obj.color_id, obj.color_name = self.ctx.hosted_color
                obj.brickognize_color_rank = None
        else:
            obj.classification_status = ClassificationStatus.unknown

        obj.color_provider = self.ctx.color_provider
        obj.mold_provider = self.ctx.mold_provider

        obj.classified_at = time.time()

        if obj.classification_status == ClassificationStatus.classified and obj.part_id:
            self._applyHiveSizeMetadata(obj)
            self._applyLocalPieceMetadata(obj)

        if frames:
            best_idx = max(range(len(frames)), key=lambda i: self.sharpness(frames[i]))
            obj.thumbnail = self.encodeFrame(frames[best_idx])

        with self.ctx.classify_lock:
            obj.classification_attempts = list(self.ctx.classification_attempts)
            obj.classification_strategy = self.ctx.classification_strategy

        self.emitKnownObject()
        self._spawnLinkMatch(obj, frames)

    def _spawnLinkMatch(self, obj, frames: list[np.ndarray]) -> None:
        # Experimental piece-link matching, off unless [link_matching] enables
        # it. Runs on its own thread and re-emits when it lands: it costs an
        # ONNX pass per candidate and this is the state-machine thread, and the
        # piece is already fully classified so nothing downstream waits on it.
        if not frames:
            return
        anchor = frames[max(range(len(frames)), key=lambda i: self.sharpness(frames[i]))]
        stamps = list(self.ctx.captured_crop_timestamps)
        # Arrival at C4 = the first burst frame's timestamp. dt is measured
        # against this, so getting it from the wrong end of the burst would
        # shift every candidate's meta features.
        arrival_ts = float(stamps[0]) if stamps else float(time.time())
        piece_uuid = obj.uuid

        def _run() -> None:
            try:
                import link_matcher

                scored = link_matcher.matchForPieceLive(
                    self.gc, piece_uuid, anchor, arrival_ts
                )
                if not scored:
                    return
                images = [
                    r
                    for r in (self._linkCropToRecognitionImage(c) for c in scored)
                    if r is not None
                ]
                if not images:
                    return
                with self.ctx.classify_lock:
                    # The piece may have been replaced while we were scoring.
                    if self.ctx.known_object is not obj:
                        return
                    obj.recognition_image_set.extend(images)
                used = sum(1 for r in images if r.used)
                self.logger.info(
                    f"{LOG_TAG} link match: {len(images)} crops, {used} above threshold"
                )
                self.emitKnownObject()
            except Exception as exc:
                self.logger.debug(f"{LOG_TAG} link match failed: {exc}")

        threading.Thread(target=_run, daemon=True).start()

    def _linkCropToRecognitionImage(self, cand: dict) -> Optional[RecognitionImage]:
        import base64

        import channel_crop_store

        path = channel_crop_store.getCropFileById(int(cand["id"]))
        if path is None or not path.is_file():
            return None
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        ts = cand.get("ts")
        return RecognitionImage(
            image=base64.b64encode(raw).decode("ascii"),
            source="link_match",
            # ``used`` means "was submitted to Brickognize in the winning
            # request". Link matches are not sent, so it stays False — the model
            # thinking a crop is the same piece is a different claim, and
            # conflating them would make the UI's used-highlighting lie about
            # what actually produced the result. ``score`` carries the model's
            # probability and the UI highlights on that instead.
            used=False,
            score=cand.get("model_score"),
            channel=int(cand["channel"]) if cand.get("channel") is not None else None,
            ts=float(ts) if isinstance(ts, (int, float)) else None,
            created_at=float(ts) if isinstance(ts, (int, float)) else None,
        )

    def _applyHiveSizeMetadata(self, obj) -> None:
        # Resolve physical dimensions from the primary Hive target and flag the
        # piece as too_big when any single axis exceeds the oversize limit. Hive
        # being unreachable must never block classification — best effort only.
        try:
            from hive_metadata import (
                OVERSIZE_MAX_DIMENSION_MM,
                getMetadataForPieceFromHive,
                isOversize,
                maxDimensionMm,
            )

            metadata = getMetadataForPieceFromHive(self.gc, obj.part_id)
            max_dim = maxDimensionMm(metadata)
            if max_dim is None:
                return
            obj.max_dimension_mm = max_dim
            obj.too_big = isOversize(max_dim)
            if obj.too_big:
                self.gc.logger.info(
                    f"piece {obj.uuid} part {obj.part_id} is oversize "
                    f"({max_dim:.1f}mm > {OVERSIZE_MAX_DIMENSION_MM}mm) -> misc bottom bin"
                )
        except Exception as exc:
            self.gc.logger.warn(f"hive size metadata lookup failed: {exc}")

    def _applyLocalPieceMetadata(self, obj) -> None:
        # Additive, local-only: pull metadata + BrickLink pricing for this
        # part+color straight off the local parts.db copy and stash it on the
        # piece. Temporary convenience alongside the network Hive path; a missing
        # DB or absent part must never affect classification.
        self._applyBsxInventoryFlag(obj)
        try:
            from piece_metadata_db import getLocalPieceMetadata

            metadata = getLocalPieceMetadata(self.gc, obj.part_id, obj.color_id)
            if metadata is None:
                return
            obj.piece_metadata = metadata
            obj.moving_avg_price = metadata.get("moving_avg_price")
        except Exception as exc:
            self.gc.logger.warn(f"local piece metadata lookup failed: {exc}")

    def _applyBsxInventoryFlag(self, obj) -> None:
        # Live membership test against the active .bsx inventory. Brickognize ids
        # are already in the BrickLink id space the .bsx uses, so this matches
        # directly. None when no inventory is active or the part is unknown.
        try:
            from bsx_inventory import getActiveBsxInventory

            inventory = getActiveBsxInventory(self.gc)
            if inventory is None:
                obj.not_in_inventory = None
                return
            in_inventory = inventory.isInInventory(obj.part_id, obj.color_id)
            obj.not_in_inventory = (in_inventory is False)
        except Exception as exc:
            self.gc.logger.warn(f"bsx inventory check failed: {exc}")

    def dumpBurstCaptureArtifacts(
        self,
        all_captures: list[np.ndarray],
        selected_captures: list[np.ndarray],
        *,
        result: object | None,
        error: str | None,
    ) -> None:
        root = getattr(self.gc, "classification_burst_dump_root", None)
        piece = self.ctx.known_object
        if root is None or piece is None:
            return
        piece_uuid = getattr(piece, "uuid", None)
        if not isinstance(piece_uuid, str) or not piece_uuid:
            return
        piece_dir = Path(root) / piece_uuid
        captures_dir = piece_dir / "captures"
        selected_dir = piece_dir / "selected"
        try:
            captures_dir.mkdir(parents=True, exist_ok=True)
            selected_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} could not create burst dump dir: {exc}")
            return

        all_paths: list[str] = []
        for idx, image in enumerate(all_captures):
            path = captures_dir / f"burst_{idx:03d}.jpg"
            if self._writeJpeg(path, image):
                all_paths.append(str(path))

        selected_paths: list[str] = []
        for idx, image in enumerate(selected_captures):
            path = selected_dir / f"selected_{idx:03d}.jpg"
            if self._writeJpeg(path, image):
                selected_paths.append(str(path))

        manifest = {
            "piece_uuid": piece_uuid,
            "captured_count": len(all_captures),
            "selected_count": len(selected_captures),
            "capture_timestamps": list(self.ctx.captured_crop_timestamps[: len(all_captures)]),
            "capture_paths": all_paths,
            "selected_paths": selected_paths,
            "classification_error": error,
            "classification_result": result if isinstance(result, dict) else None,
            "brickognize_result": self._knownObjectResultSnapshot(),
        }
        try:
            (piece_dir / "brickognize_result.json").write_text(
                json.dumps(
                    {
                        "piece_uuid": piece_uuid,
                        "classification_error": error,
                        "classification_result": result if isinstance(result, dict) else None,
                        "brickognize_result": self._knownObjectResultSnapshot(),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            (piece_dir / "burst_manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True)
            )
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} could not write burst manifest: {exc}")

    def _knownObjectResultSnapshot(self) -> dict[str, object]:
        obj = self.ctx.known_object
        if obj is None:
            return {}
        return {
            "status": str(obj.classification_status.value)
            if hasattr(obj.classification_status, "value")
            else str(obj.classification_status),
            "part_id": obj.part_id,
            "part_name": obj.part_name,
            "part_category": obj.part_category,
            "color_id": obj.color_id,
            "color_name": obj.color_name,
            "confidence": obj.confidence,
            "brickognize_preview_url": obj.brickognize_preview_url,
            "brickognize_source_view": obj.brickognize_source_view,
        }

    @staticmethod
    def _writeJpeg(path: Path, image: np.ndarray) -> bool:
        if image is None or image.size == 0:
            return False
        try:
            ok = bool(
                cv2.imwrite(
                    str(path),
                    image,
                    [cv2.IMWRITE_JPEG_QUALITY, 80],
                )
            )
        except Exception:
            return False
        return ok
