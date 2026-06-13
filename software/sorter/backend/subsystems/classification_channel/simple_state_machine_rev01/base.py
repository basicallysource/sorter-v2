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

from .constants import LOG_TAG
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
    # One Brickognize call: a labelled subset of the sendable images. Most steps
    # have a single request; a fan-out step (e.g. split_singles) carries several
    # that are submitted in parallel and merged by confidence.
    label: str
    images: list[_SendImage]


@dataclass
class _AttemptStep:
    # One rung of the retry ladder. ``requests`` is submitted as a unit: a single
    # request is one Brickognize call; multiple requests run in parallel and the
    # step's applied result is the highest-confidence one that came back. Steps
    # run in order, each only if the previous recognized nothing.
    strategy: ClassificationAttemptStrategy
    requests: list[_ClassifyRequest]


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
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return None
        return base64.b64encode(buf).decode("utf-8")

    @staticmethod
    def sharpness(frame: np.ndarray) -> float:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

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

    def selectRecognitionCrops(
        self, crops: list[np.ndarray], max_images: Optional[int] = None
    ) -> list[np.ndarray]:
        # Hard-cap at the Brickognize per-request image limit regardless of the
        # configured max_captures — over the limit the API errors the whole call.
        # ``max_images`` lets the caller reserve slots for injected upstream
        # matches (the total across both must stay <= MAX_QUERY_IMAGES).
        cap = MAX_QUERY_IMAGES if max_images is None else max_images
        n = min(self.ctx.config.max_captures, cap)
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
        # Runs entirely off the state-machine thread: the upstream-match search
        # is a paid, blocking HTTP call (embed the burst, KNN the vec DB), so it
        # MUST NOT run on the main loop. The thread fuses any upstream matches
        # with the C4 burst — bursts give up slots so the total never exceeds
        # Brickognize's 8-image limit — then runs the attempt sequence: submit
        # the full set, and on a no-recognition result retry with a reduced set
        # (see _runClassifyAttempts).
        obj = self.ctx.known_object
        piece_uuid = obj.uuid if obj is not None else None
        # Only the last classify_burst_count burst frames drive classification:
        # they anchor the upstream-similarity search and are the C4 images sent to
        # Brickognize. The rest of the burst is kept on the KnownObject
        # (used=False) for review.
        n_use = max(1, int(self.ctx.config.classify_burst_count))
        burst_entries = (
            [r for r in obj.recognition_image_set if r.source == "c4_burst"]
            if obj is not None
            else []
        )
        used_entries = burst_entries[-n_use:]
        anchor_b64s = [e.image for e in used_entries]
        burst_crops = list(all_captures[-n_use:])
        ref_ts = float(
            (obj.first_carousel_seen_ts or obj.created_at)
            if obj is not None
            else time.time()
        )

        def _run() -> None:
            try:
                upstream_bgr, upstream_images = self._gatherUpstreamMatches(
                    anchor_b64s, ref_ts, max_inject=MAX_QUERY_IMAGES - len(burst_crops)
                )
                with self.ctx.classify_lock:
                    self.ctx.upstream_recognition_images = list(upstream_images)
                # Pair each sendable image with its RecognitionImage. The used
                # upstream entries (flagged by the store) align 1:1, in order,
                # with upstream_bgr.
                sendable: list[_SendImage] = [
                    _SendImage(bgr, rec) for bgr, rec in zip(burst_crops, used_entries)
                ]
                used_upstream = [r for r in upstream_images if r.used]
                sendable += [
                    _SendImage(bgr, rec) for bgr, rec in zip(upstream_bgr, used_upstream)
                ]
                if not sendable:
                    with self.ctx.classify_lock:
                        self.ctx.classification_error = "no_captures"
                    return
                plan = self._buildAttemptPlan(sendable)
                self._runClassifyAttempts(plan, piece_uuid)
            except Exception as exc:
                with self.ctx.classify_lock:
                    self.ctx.classification_error = str(exc)

        thread = threading.Thread(target=_run, daemon=True)
        self.ctx.classify_thread = thread
        thread.start()

    def _buildAttemptPlan(self, sendable: list[_SendImage]) -> list[_AttemptStep]:
        # The ordered retry ladder. Step 0 submits the full set; each enabled
        # strategy appends a step, tried in order only if a prior step recognized
        # nothing. A strategy that wouldn't change anything (e.g. drop_upstream
        # with no upstream present) is skipped so we never pay for an identical
        # re-submit.
        burst = [s for s in sendable if s.rec.source == "c4_burst"]
        upstream = [s for s in sendable if s.rec.source == "upstream"]
        plan: list[_AttemptStep] = [
            _AttemptStep(
                ClassificationAttemptStrategy.initial,
                [_ClassifyRequest("initial", list(sendable))],
            )
        ]
        cfg = self.ctx.config
        if getattr(cfg, "classify_retry_drop_upstream", False) and upstream and burst:
            plan.append(
                _AttemptStep(
                    ClassificationAttemptStrategy.drop_upstream,
                    [_ClassifyRequest("drop_upstream", list(burst))],
                )
            )
        if getattr(cfg, "classify_retry_split_singles", False) and upstream and burst:
            # Two single-image queries in parallel: the last (most-settled) burst
            # frame vs. the single highest-similarity upstream crop. We keep the
            # higher-confidence of whichever come back, so a piece the fused set
            # confused can still be carried by either view alone.
            last_burst = burst[-1]
            top_upstream = max(
                upstream, key=lambda s: s.rec.score if s.rec.score is not None else -1.0
            )
            plan.append(
                _AttemptStep(
                    ClassificationAttemptStrategy.split_singles,
                    [
                        _ClassifyRequest("last_burst", [last_burst]),
                        _ClassifyRequest("top_upstream", [top_upstream]),
                    ],
                )
            )
        return plan

    @staticmethod
    def _topItem(result: object) -> Optional[dict]:
        items = result.get("items", []) if isinstance(result, dict) else []
        return items[0] if items else None

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

    def _runClassifyAttempts(
        self, plan: list[_AttemptStep], piece_uuid: Optional[str]
    ) -> None:
        # Walk the ladder until a step recognizes the piece or the time budget is
        # spent. Within a step, all requests run in parallel and the step winner
        # is the highest-confidence request that returned an item. A transport
        # failure on the very first (initial) call is fatal — no retry can fix a
        # network error — otherwise errors are swallowed and the loop continues.
        deadline = self.ctx.classify_started_at + float(self.ctx.config.classify_timeout_s)
        attempts: list[ClassificationAttempt] = []
        # ClassificationAttempt <-> the request that produced it, so the applied
        # one can be flagged in _finalizeAttempts.
        attempt_reqs: list[_ClassifyRequest] = []
        # (winning request, applied result dict, strategy) once decided.
        winner: Optional[tuple[_ClassifyRequest, dict, ClassificationAttemptStrategy]] = None
        # First non-error result, used as the no-recognition fallback to apply.
        fallback: Optional[tuple[_ClassifyRequest, dict, ClassificationAttemptStrategy]] = None

        for idx, step in enumerate(plan):
            if idx > 0 and time.monotonic() >= deadline:
                self.logger.warning(
                    f"{LOG_TAG} classify budget spent before retry [{step.strategy.value}] — stopping"
                )
                break
            self.logger.info(
                f"{LOG_TAG} Brickognize step {idx + 1}/{len(plan)} [{step.strategy.value}]: "
                f"{len(step.requests)} request(s) "
                f"({', '.join(r.label for r in step.requests)})"
            )
            results = self._runRequestsParallel(step.requests, piece_uuid)
            step_found: list[tuple[_ClassifyRequest, dict, float]] = []
            for req, result, error, dur in results:
                top = self._topItem(result)
                attempts.append(
                    ClassificationAttempt(
                        strategy=step.strategy,
                        label=req.label,
                        n_burst=sum(1 for s in req.images if s.rec.source == "c4_burst"),
                        n_upstream=sum(1 for s in req.images if s.rec.source == "upstream"),
                        found=top is not None,
                        part_id=top.get("id") if isinstance(top, dict) else None,
                        confidence=top.get("score") if isinstance(top, dict) else None,
                        error=error,
                        duration_s=dur,
                    )
                )
                attempt_reqs.append(req)
                if error is not None:
                    if idx == 0 and len(step.requests) == 1:
                        with self.ctx.classify_lock:
                            self.ctx.classification_error = error
                        self._finalizeAttempts(plan, attempts, attempt_reqs, fallback)
                        return
                    self.logger.warning(
                        f"{LOG_TAG} request [{step.strategy.value}/{req.label}] transport "
                        f"error: {error}"
                    )
                    continue
                if result is not None and fallback is None:
                    fallback = (req, result, plan[0].strategy)
                if top is not None and result is not None:
                    score = top.get("score") if isinstance(top, dict) else None
                    step_found.append((req, result, float(score) if score is not None else -1.0))
            if step_found:
                best_req, best_result, _ = max(step_found, key=lambda x: x[2])
                winner = (best_req, best_result, step.strategy)
                if idx > 0:
                    self.logger.info(
                        f"{LOG_TAG} step [{step.strategy.value}] recognized piece via "
                        f"[{best_req.label}] after earlier no-recognition"
                    )
                break
            self.logger.info(
                f"{LOG_TAG} step [{step.strategy.value}] recognized nothing"
            )

        self._finalizeAttempts(plan, attempts, attempt_reqs, winner or fallback)

    def _finalizeAttempts(
        self,
        plan: list[_AttemptStep],
        attempts: list[ClassificationAttempt],
        attempt_reqs: list[_ClassifyRequest],
        applied: Optional[tuple[_ClassifyRequest, dict, ClassificationAttemptStrategy]],
    ) -> None:
        # Apply the winning attempt if one recognized the piece; otherwise fall
        # back to the first no-recognition result (its full image set becomes the
        # "used" set). Every sendable image either drove the applied attempt
        # (used=True) or was sent in a losing/earlier attempt and pulled
        # (excluded_from_result=True). Images never sent stay used=False. The
        # applied attempt's record is flagged so the UI need not re-derive it.
        applied_req = applied[0] if applied is not None else None
        full = plan[0].requests[0].images if plan else []
        winning_subset = applied_req.images if applied_req is not None else full
        winning_ids = {id(s) for s in winning_subset}
        for s in full:
            in_winner = id(s) in winning_ids
            s.rec.used = in_winner
            s.rec.excluded_from_result = not in_winner
        for att, req in zip(attempts, attempt_reqs):
            att.applied = req is applied_req
        strategy = applied[2] if applied is not None else (
            plan[0].strategy if plan else ClassificationAttemptStrategy.initial
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
            f"(attempts={[(a.strategy.value, a.label, a.found) for a in attempts]})"
        )

    def _gatherUpstreamMatches(
        self, anchor_b64s: list[str], ref_ts: float, max_inject: int
    ) -> tuple[list[np.ndarray], list[RecognitionImage]]:
        # Returns (decoded BGR crops to SEND to Brickognize, wrapped
        # RecognitionImages for the KnownObject/UI). The store grabs
        # classify_top_n matches and flags the most-similar classify_use_n as
        # used; we send only the used crops (capped by max_inject for the 8-image
        # limit) but attach ALL grabbed crops to the piece for review, each with
        # its cosine similarity to the anchor (the classified C4 frame).
        # Best-effort: any failure yields none.
        store = getattr(getattr(self.gc, "perception_service", None), "upstream_store", None)
        if store is None:
            return [], []
        try:
            candidates = store.matchForClassification(anchor_b64s, ref_ts)
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} upstream match failed: {exc}")
            return [], []
        bgr_list: list[np.ndarray] = []
        image_list: list[RecognitionImage] = []
        for cand in candidates:
            b64 = cand.get("jpeg_b64") if isinstance(cand, dict) else None
            if not isinstance(b64, str) or not b64:
                continue
            img = self._decodeB64Jpeg(b64)
            if img is None or img.size == 0:
                continue
            score = cand.get("score")
            used = bool(cand.get("used")) and len(bgr_list) < max_inject
            if used:
                bgr_list.append(img)
            image_list.append(
                RecognitionImage(
                    image=b64,
                    source="upstream",
                    used=used,
                    score=float(score) if isinstance(score, (int, float)) else None,
                )
            )
        if image_list:
            self.logger.info(
                f"{LOG_TAG} upstream match: grabbed {len(image_list)}, using "
                f"{len(bgr_list)} (scores={[r.score for r in image_list]})"
            )
        return bgr_list, image_list

    @staticmethod
    def _decodeB64Jpeg(b64: str) -> Optional[np.ndarray]:
        try:
            raw = base64.b64decode(b64)
            arr = np.frombuffer(raw, dtype=np.uint8)
            return cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Exception:
            return None

    def updateKnownObjectWithResult(self, result: object, error: Optional[str]) -> None:
        obj = self.ctx.known_object
        if obj is None:
            return

        frames = list(self.ctx.captured_crops)

        if error is not None:
            obj.classification_status = ClassificationStatus.unknown
        elif isinstance(result, dict):
            items = result.get("items", [])
            colors = result.get("colors", [])
            if items:
                best = items[0]
                obj.part_id = best.get("id")
                obj.part_name = best.get("name")
                obj.part_category = best.get("category")
                obj.confidence = best.get("score")
                obj.brickognize_preview_url = best.get("img_url")
                obj.classification_status = ClassificationStatus.classified
            else:
                obj.classification_status = ClassificationStatus.not_found
            if colors:
                best_color = max(colors, key=lambda c: c.get("score", 0))
                obj.color_id = str(best_color.get("id", "any_color"))
                obj.color_name = str(best_color.get("name", "Any Color"))
        else:
            obj.classification_status = ClassificationStatus.unknown

        obj.classified_at = time.time()

        if obj.classification_status == ClassificationStatus.classified and obj.part_id:
            self._applyHiveSizeMetadata(obj)

        if frames:
            best_idx = max(range(len(frames)), key=lambda i: self.sharpness(frames[i]))
            obj.thumbnail = self.encodeFrame(frames[best_idx])

        with self.ctx.classify_lock:
            obj.recognition_image_set.extend(self.ctx.upstream_recognition_images)
            obj.classification_attempts = list(self.ctx.classification_attempts)
            obj.classification_strategy = self.ctx.classification_strategy

        self.emitKnownObject()

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
