from __future__ import annotations

import base64
import math
import threading
import time
from typing import Optional

import cv2
import numpy as np

from classification.brickognize import (
    ANY_COLOR,
    ANY_COLOR_NAME,
    _classifyImages,
    _pickBestColor,
    _pickBestItem,
)
from defs.known_object import ClassificationStatus
from utils.event import knownObjectToEvent

MIN_RECOGNIZE_CROPS = 1
CLASSIFICATION_TIMEOUT_S = 12.0
MAX_MULTI_RECOGNIZE_CROPS = 8
SINGLE_CROP_FALLBACK_COUNT = 3
# Fraction of the Brickognize multi-crop batch reserved for c_channel_3 crops so
# the selection isn't dominated by the (more numerous) c2 / carousel views. With
# MAX_MULTI_RECOGNIZE_CROPS=8 and 0.25 this reserves 2 slots for the sharpest c3
# crops. Shortfall is filled from the general (sharpness-ranked) pool.
C3_CROP_QUOTA_RATIO = 0.25

# Laplacian-variance floor applied to the sharpest crop in the pool. If every
# tracker crop we collected is below this threshold the piece is likely still
# motion-blurred on every view; skip firing and wait for more frames rather
# than burning a Brickognize call on blurry evidence. Tuned empirically: focused
# carousel crops land in the 80-400 range; motion-blurred ones rarely exceed 25.
MIN_SHARPNESS_LAPLACIAN_VAR = 5.0

# Border (as a fraction of the smaller crop edge) added via reflection padding
# before each crop ships to Brickognize. The model prefers a little breathing
# room around the piece — without access to the original frame at recognition
# time we approximate via BORDER_REFLECT_101, which introduces no hard edges.
CROP_REFLECTION_PAD_RATIO = 0.15

# (image, source_role, captured_ts). captured_ts is kept so the frontend can
# later map shipped crops back to the tracker's sector snapshots by timestamp.
CropEntry = tuple[np.ndarray, str, float]


class ClassificationChannelRecognizer:
    def __init__(
        self,
        *,
        gc,
        logger,
        vision,
        transport,
        event_queue,
    ) -> None:
        self.gc = gc
        self.logger = logger
        self.vision = vision
        self.transport = transport
        self.event_queue = event_queue

    def fire(self, piece) -> bool:
        crops = self._collectTrackedImages(piece)
        if len(crops) < MIN_RECOGNIZE_CROPS:
            self._bumpRecognizerCounter("recognize_skipped_no_crops")
            self.logger.debug(
                "ClassificationChannel: only %d tracker crop(s) for piece %s; "
                "waiting for more views before Brickognize"
                % (len(crops), piece.uuid[:8])
            )
            return False

        # Fast secondary gate: if NONE of the available crops come from the
        # carousel role, the piece is still physically upstream (on c3 or
        # earlier) and classifying now would commit on c2/c3 views only —
        # which, under a misbind, can belong to a different piece entirely.
        # The Running state's _fireRecognition also enforces the carousel
        # quota/dwell; this is belt-and-suspenders for callers that bypass it.
        carousel_crop_count = sum(
            1 for _image, role, _ts in crops if role == "carousel"
        )
        if carousel_crop_count <= 0:
            self._bumpRecognizerCounter("recognize_skipped_no_carousel_crops")
            self.logger.debug(
                "ClassificationChannel: piece %s has %d crop(s) but 0 from "
                "carousel; deferring recognition until it lands on C4"
                % (piece.uuid[:8], len(crops))
            )
            return False

        crop_images = [image for image, _role, _ts in crops]
        sharpest = self._pickSharpestCrop(crop_images)

        # Sharpness floor: if the very best crop we have is below the
        # motion-blur threshold, defer firing. The Running state will retry
        # on subsequent ticks as fresher (and hopefully sharper) frames land.
        if sharpest is not None:
            best_score = self._laplacianVariance(sharpest)
            if best_score < MIN_SHARPNESS_LAPLACIAN_VAR:
                self._bumpRecognizerCounter("recognize_skipped_low_sharpness")
                self.logger.debug(
                    "ClassificationChannel: piece %s sharpest crop score %.1f "
                    "< %.1f floor; waiting for a sharper view"
                    % (piece.uuid[:8], best_score, MIN_SHARPNESS_LAPLACIAN_VAR)
                )
                return False

        if sharpest is not None:
            piece.thumbnail = self._encodeImageBase64(sharpest)

        # Decide which crops actually ship *before* flipping status so the
        # per-piece event carries the identifying timestamps. The frontend
        # uses these to highlight the "Captured Crops" that participated.
        selected = self._selectCropsWithSourceQuota(
            crops,
            max_count=MAX_MULTI_RECOGNIZE_CROPS,
            c3_quota_ratio=C3_CROP_QUOTA_RATIO,
        )
        piece.recognition_used_crop_ts = [
            float(ts) for _image, _role, ts in selected if ts
        ]

        piece.classification_status = ClassificationStatus.classifying
        piece.updated_at = time.time()
        if self.event_queue is not None:
            self.event_queue.put(knownObjectToEvent(piece))

        self.transport.markPendingClassification(piece)
        self._classifyImagesAsync(piece, selected)
        self._bumpRecognizerCounter("recognize_fired_total")
        self.logger.info(
            "ClassificationChannel: fired Brickognize for piece %s with %d tracker crops"
            % (piece.uuid[:8], len(crops))
        )
        return True

    def countCarouselCrops(self, piece) -> int:
        """Return the number of carousel-source crops currently available.

        Exposed for the Running state's pre-fire gate so it can require a
        minimum carousel crop count before calling ``fire()``. Uses the
        same crop-collection path as ``fire()`` itself.
        """
        crops = self._collectTrackedImages(piece)
        return sum(
            1 for _image, role, _ts in crops if role in ("carousel", "c_channel_3")
        )

    def _bumpRecognizerCounter(self, name: str) -> None:
        runtime_stats = getattr(self.gc, "runtime_stats", None)
        if runtime_stats is None:
            return
        observe = getattr(runtime_stats, "observeRecognizerCounter", None)
        if observe is None:
            return
        try:
            observe(name)
        except Exception:
            pass

    def _collectTrackedImages(self, piece) -> list[CropEntry]:
        track_id = getattr(piece, "tracked_global_id", None)
        if not isinstance(track_id, int) or self.vision is None:
            return []
        details: list[dict] = []
        seen_global_ids: set[int] = set()
        detail = self.vision.getFeederTrackHistoryDetail(track_id)
        if isinstance(detail, dict):
            details.append(detail)
            global_id = detail.get("global_id")
            if isinstance(global_id, int):
                seen_global_ids.add(global_id)
        if not details:
            return []
        reference_ts = self._reference_ts(piece, details)
        if not any(self._detailHasRole(d, "c_channel_3") for d in details):
            fallback_detail = self._findFallbackUpstreamDetail(
                source_role="c_channel_3",
                before_ts=reference_ts,
                max_age_s=20.0,
                limit=80,
                seen_global_ids=seen_global_ids,
                required_global_id=track_id,
            )
            if isinstance(fallback_detail, dict):
                details.append(fallback_detail)
                global_id = fallback_detail.get("global_id")
                if isinstance(global_id, int):
                    seen_global_ids.add(global_id)
        c3_reference_ts = (
            self._earliest_role_timestamp(details, "c_channel_3") or reference_ts
        )
        if not any(self._detailHasRole(d, "c_channel_2") for d in details):
            fallback_detail = self._findFallbackUpstreamDetail(
                source_role="c_channel_2",
                before_ts=c3_reference_ts,
                max_age_s=30.0,
                limit=120,
                seen_global_ids=seen_global_ids,
                required_global_id=track_id,
            )
            if isinstance(fallback_detail, dict):
                details.append(fallback_detail)
                global_id = fallback_detail.get("global_id")
                if isinstance(global_id, int):
                    seen_global_ids.add(global_id)
        images: list[tuple[float, np.ndarray, str]] = []
        for detail in details:
            for segment in detail.get("segments", []):
                if not isinstance(segment, dict):
                    continue
                source_role = segment.get("source_role")
                if source_role not in {
                    "c_channel_2",
                    "c_channel_3",
                    "carousel",
                }:
                    continue
                for snap in segment.get("sector_snapshots", []):
                    if not isinstance(snap, dict):
                        continue
                    image = self._decodeImageBase64(snap.get("piece_jpeg_b64"))
                    if image is None:
                        continue
                    captured_ts = snap.get("captured_ts")
                    images.append(
                        (
                            float(captured_ts)
                            if isinstance(captured_ts, (int, float))
                            else 0.0,
                            image,
                            str(source_role),
                        )
                    )
        images.sort(key=lambda item: item[0])
        return [(image, role, ts) for ts, image, role in images[:12]]

    def _findFallbackUpstreamDetail(
        self,
        *,
        source_role: str,
        before_ts: float,
        max_age_s: float,
        limit: int,
        seen_global_ids: set[int],
        required_global_id: int | None = None,
    ) -> dict | None:
        if self.vision is None or not hasattr(
            self.vision, "findRecentFeederTrackHistoryDetailByRole"
        ):
            return None
        try:
            detail = self.vision.findRecentFeederTrackHistoryDetailByRole(
                source_role=source_role,
                before_ts=float(before_ts),
                max_age_s=float(max_age_s),
                limit=int(limit),
                required_global_id=required_global_id,
            )
        except Exception as exc:
            self.logger.debug(
                "ClassificationChannel: could not load fallback %s history: %s"
                % (source_role, exc)
            )
            return None
        if not isinstance(detail, dict):
            return None
        global_id = detail.get("global_id")
        if isinstance(global_id, int) and global_id in seen_global_ids:
            return None
        return detail

    @staticmethod
    def _reference_ts(piece, details: list[dict]) -> float:
        detail_ts = ClassificationChannelRecognizer._earliest_role_timestamp(
            details,
            "carousel",
        )
        if detail_ts is not None:
            return detail_ts
        return float(
            getattr(piece, "carousel_detected_confirmed_at", None)
            or getattr(piece, "feeding_started_at", None)
            or time.time()
        )

    @staticmethod
    def _earliest_role_timestamp(
        details: list[dict],
        source_role: str,
    ) -> float | None:
        earliest: float | None = None
        for detail in details:
            for segment in detail.get("segments", []):
                if not isinstance(segment, dict):
                    continue
                if segment.get("source_role") != source_role:
                    continue
                first_seen_ts = segment.get("first_seen_ts")
                if not isinstance(first_seen_ts, (int, float)):
                    continue
                ts = float(first_seen_ts)
                if earliest is None or ts < earliest:
                    earliest = ts
        return earliest

    @staticmethod
    def _detailHasRole(detail: dict, source_role: str) -> bool:
        return any(
            isinstance(segment, dict) and segment.get("source_role") == source_role
            for segment in detail.get("segments", [])
        )

    def _classifyImagesAsync(self, piece, images: list[CropEntry]) -> None:
        piece_uuid = piece.uuid
        event_queue = self.event_queue
        logger = self.logger
        transport = self.transport
        gc = self.gc

        bump_counter = self._bumpRecognizerCounter

        def _run() -> None:
            api_call_succeeded = False
            try:
                (
                    part_id,
                    color_id,
                    color_name,
                    confidence,
                    preview_url,
                    best_view,
                    part_name,
                    part_category,
                ) = self._classifyTrackedCrops(images)
                api_call_succeeded = True
            except Exception as exc:
                logger.error(
                    "ClassificationChannel: Brickognize call failed: %s" % exc
                )
                part_id = None
                color_id = ANY_COLOR
                color_name = ANY_COLOR_NAME
                confidence = None
                preview_url = None
                best_view = None
                part_name = None
                part_category = None

            if api_call_succeeded and part_id is None:
                bump_counter("brickognize_empty_result")

            resolved = transport.resolveClassification(
                piece_uuid,
                part_id,
                color_id,
                color_name,
                confidence,
                part_name=part_name,
                part_category=part_category,
            )
            if not resolved:
                logger.warning(
                    "ClassificationChannel: ignoring late Brickognize result for "
                    f"{piece_uuid[:8]}"
                )
                return
            piece.brickognize_preview_url = preview_url
            piece.brickognize_source_view = best_view or "tracked_multi"
            piece.updated_at = time.time()
            if event_queue is not None:
                event_queue.put(knownObjectToEvent(piece))
            logger.info(
                "ClassificationChannel: classified %s -> %s color=%s"
                % (piece_uuid[:8], part_id, color_name)
            )

        def _timeout_guard() -> None:
            time.sleep(CLASSIFICATION_TIMEOUT_S)
            resolved = transport.resolveFallbackClassification(
                piece_uuid,
                status=ClassificationStatus.unknown,
            )
            if not resolved:
                return
            piece.updated_at = time.time()
            if event_queue is not None:
                event_queue.put(knownObjectToEvent(piece))
            gc.runtime_stats.observeBlockedReason(
                "classification", "brickognize_timeout"
            )
            bump_counter("brickognize_timeout_total")
            logger.warning(
                "ClassificationChannel: Brickognize timed out for "
                f"{piece_uuid[:8]} after {CLASSIFICATION_TIMEOUT_S:.1f}s; "
                "marking unknown so distribution can continue"
            )

        threading.Thread(target=_run, daemon=True).start()
        threading.Thread(target=_timeout_guard, daemon=True).start()

    @staticmethod
    def _decodeImageBase64(payload: object) -> np.ndarray | None:
        if not isinstance(payload, str) or not payload:
            return None
        try:
            raw = base64.b64decode(payload)
        except Exception:
            return None
        arr = np.frombuffer(raw, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    @staticmethod
    def _encodeImageBase64(image: np.ndarray | None) -> Optional[str]:
        if image is None:
            return None
        ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return None
        return base64.b64encode(buffer).decode("utf-8")

    @staticmethod
    def _laplacianVariance(crop: np.ndarray) -> float:
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    @staticmethod
    def _padCropForBrickognize(
        crop: np.ndarray,
        pad_ratio: float = CROP_REFLECTION_PAD_RATIO,
    ) -> np.ndarray:
        """Add a reflection border around the crop before shipping to
        Brickognize. The tracker produces tight bbox crops (~8 px margin);
        Brickognize tends to match better with a bit of surrounding context.
        We can't widen from the original frame here (it's gone by this point),
        so we approximate with BORDER_REFLECT_101 which avoids the hard black
        edges that BORDER_CONSTANT would introduce.
        """
        if crop is None or crop.size == 0 or pad_ratio <= 0:
            return crop
        h, w = crop.shape[:2]
        pad = int(round(min(h, w) * float(pad_ratio)))
        if pad <= 0:
            return crop
        return cv2.copyMakeBorder(
            crop, pad, pad, pad, pad, cv2.BORDER_REFLECT_101
        )

    @staticmethod
    def _pickSharpestCrop(crops: list[np.ndarray]) -> np.ndarray | None:
        best_score = -1.0
        best_crop: np.ndarray | None = None
        for crop in crops:
            score = ClassificationChannelRecognizer._laplacianVariance(crop)
            if score > best_score:
                best_score = score
                best_crop = crop
        return best_crop

    def _classifyTrackedCrops(
        self,
        images: list[CropEntry],
    ) -> tuple[
        Optional[str],
        str,
        str,
        Optional[float],
        Optional[str],
        Optional[str],
        Optional[str],
        Optional[str],
    ]:
        selected = self._selectCropsWithSourceQuota(
            images,
            max_count=MAX_MULTI_RECOGNIZE_CROPS,
            c3_quota_ratio=C3_CROP_QUOTA_RATIO,
        )
        c3_slots_used = sum(1 for _image, role, _ts in selected if role == "c_channel_3")
        if c3_slots_used > 0:
            for _ in range(c3_slots_used):
                self._bumpRecognizerCounter("recognize_c3_slots_used")
        selected_images = [
            self._padCropForBrickognize(image) for image, _role, _ts in selected
        ]
        primary_result = _classifyImages(selected_images)
        candidate = self._candidateFromResult(
            primary_result,
            source_view="tracked_multi",
        )
        if candidate[0] is not None:
            return candidate

        best_single = candidate
        for crop in selected_images[:SINGLE_CROP_FALLBACK_COUNT]:
            single_result = _classifyImages([crop])
            single_candidate = self._candidateFromResult(
                single_result,
                source_view="tracked_single",
            )
            if single_candidate[0] is None:
                continue
            if best_single[0] is None or (single_candidate[3] or 0.0) > (best_single[3] or 0.0):
                best_single = single_candidate
        return best_single  # type: ignore[return-value]

    @staticmethod
    def _selectCropsWithSourceQuota(
        crops: list[CropEntry],
        *,
        max_count: int = MAX_MULTI_RECOGNIZE_CROPS,
        c3_quota_ratio: float = C3_CROP_QUOTA_RATIO,
    ) -> list[CropEntry]:
        """Pick up to ``max_count`` crops, ranked by Laplacian sharpness,
        while reserving ``ceil(max_count * c3_quota_ratio)`` slots for
        ``c_channel_3`` crops when available.

        Opinionated ordering: the sharpest c3 crop is placed at index 0 so the
        single-crop fallback (``selected[:SINGLE_CROP_FALLBACK_COUNT]``) picks
        up a c3 view first. Any shortfall in the c3 quota falls back to the
        sharpest remaining crops regardless of source.
        """
        if not crops:
            return []

        def _score(entry: CropEntry) -> float:
            return ClassificationChannelRecognizer._laplacianVariance(entry[0])

        ranked = sorted(crops, key=_score, reverse=True)
        if len(ranked) <= max_count:
            return ranked

        c3_quota = max(0, math.ceil(max_count * max(0.0, c3_quota_ratio)))
        c3_quota = min(c3_quota, max_count)
        c3_ranked = [entry for entry in ranked if entry[1] == "c_channel_3"]
        reserved_c3 = c3_ranked[:c3_quota]
        reserved_ids = {id(entry) for entry in reserved_c3}

        remaining_slots = max_count - len(reserved_c3)
        filler: list[CropEntry] = []
        for entry in ranked:
            if id(entry) in reserved_ids:
                continue
            filler.append(entry)
            if len(filler) >= remaining_slots:
                break

        # Assemble: put sharpest c3 at position 0 so the single-crop fallback
        # starts from a c3 view; remainder interleaves / appends sharpness-first.
        if not reserved_c3:
            return filler[:max_count]

        result: list[CropEntry] = [reserved_c3[0]]
        extra_c3 = reserved_c3[1:]
        # Alternate: best filler, next reserved c3, then rest of filler.
        filler_iter = iter(filler)
        next_filler = next(filler_iter, None)
        if next_filler is not None:
            result.append(next_filler)
            next_filler = next(filler_iter, None)
        for c3_entry in extra_c3:
            result.append(c3_entry)
        while next_filler is not None and len(result) < max_count:
            result.append(next_filler)
            next_filler = next(filler_iter, None)
        return result[:max_count]

    @staticmethod
    def _candidateFromResult(
        result: dict | None,
        *,
        source_view: str,
    ) -> tuple[
        Optional[str],
        str,
        str,
        Optional[float],
        Optional[str],
        Optional[str],
        Optional[str],
        Optional[str],
    ]:
        if result is None:
            return (None, ANY_COLOR, ANY_COLOR_NAME, None, None, source_view, None, None)
        best_item = ClassificationChannelRecognizer._pickBestItemFromResult(result)
        best_color = ClassificationChannelRecognizer._pickBestColorFromResult(result)
        return (
            best_item.get("id") if best_item else None,
            best_color["id"] if best_color else ANY_COLOR,
            best_color["name"] if best_color else ANY_COLOR_NAME,
            best_item.get("score") if best_item else None,
            best_item.get("img_url") if best_item else None,
            source_view,
            best_item.get("name") if best_item else None,
            best_item.get("category") if best_item else None,
        )

    @staticmethod
    def _pickBestItemFromResult(result: dict | None) -> dict | None:
        if not isinstance(result, dict):
            return None
        items = result.get("items")
        if not isinstance(items, list) or not items:
            return None
        return max(
            (
                item
                for item in items
                if isinstance(item, dict)
            ),
            key=lambda item: item.get("score", 0.0),
            default=None,
        )

    @staticmethod
    def _pickBestColorFromResult(result: dict | None) -> dict | None:
        if not isinstance(result, dict):
            return None
        colors = result.get("colors")
        if not isinstance(colors, list) or not colors:
            return None
        return max(
            (
                color
                for color in colors
                if isinstance(color, dict)
            ),
            key=lambda color: color.get("score", 0.0),
            default=None,
        )

    @staticmethod
    def _rankCropsBySharpness(crops: list[np.ndarray]) -> list[np.ndarray]:
        return sorted(
            crops,
            key=ClassificationChannelRecognizer._laplacianVariance,
            reverse=True,
        )
