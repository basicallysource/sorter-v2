from __future__ import annotations

import math
from typing import Any

from rt.contracts.classification import ClassifierResult
from rt.contracts.feed import FeedFrame
from rt.contracts.tracking import Track
from rt.events.topics import PIECE_CLASSIFIED


class C4ClassificationController:
    """Own C4 classifier submission and classifier-future polling."""

    def __init__(self, runtime: Any) -> None:
        self._rt = runtime

    def submit_classifications(self, tracks: list[Track], now_mono: float) -> None:
        rt = self._rt
        if rt._latest_frame is None and rt._crop_provider is None:
            self.mark_skip("no_frame_or_crop_provider")
            return
        for track in tracks:
            if track.global_id is None:
                self.mark_skip("track_without_global_id")
                continue
            piece_uuid = rt._piece_uuid_for_track(track)
            if piece_uuid is None:
                self.mark_skip("unowned_track")
                continue
            dossier = rt._pieces.get(piece_uuid)
            if dossier is None:
                self.mark_skip("missing_dossier")
                continue
            if dossier.result is not None or dossier.classify_future is not None:
                self.mark_skip("already_classifying_or_classified")
                continue
            angle_deg = math.degrees(track.angle_rad or 0.0)
            at_classify = rt._near_angle(angle_deg, rt._classify_angle_deg)
            at_pretrigger = self.in_classify_pretrigger(angle_deg)
            at_exit = rt._near_angle(angle_deg, rt._exit_angle_deg)
            if not at_classify and not at_pretrigger and not at_exit:
                self.mark_skip("not_at_classify_angle")
                continue
            crop = rt._build_crop(track)
            if crop is None:
                self.mark_skip("no_crop")
                continue
            frame = rt._latest_frame or _synthetic_frame(
                feed_id=rt.feed_id or "c4_feed",
                now_mono=now_mono,
            )
            try:
                future = rt._classifier.classify_async(track, frame, crop)
            except Exception:
                rt._logger.exception(
                    "RuntimeC4: classifier.classify_async raised for piece=%s",
                    piece_uuid,
                )
                self.mark_skip("classify_async_raised")
                continue
            dossier.classify_future = future
            dossier.last_seen_mono = now_mono
            self.mark_skip(
                "submitted"
                if at_classify
                else "submitted_early"
                if at_pretrigger
                else "submitted_late_exit"
            )

    def in_classify_pretrigger(self, angle_deg: float) -> bool:
        rt = self._rt
        lead_deg = float(rt._classify_pretrigger_exit_lead_deg)
        if lead_deg <= 0.0:
            return False
        if rt._near_angle(angle_deg, rt._zone_manager.intake_angle_deg):
            return False
        intake_guard = (
            rt._intake_half_width_deg
            + float(getattr(rt._zone_manager, "guard_angle_deg", 0.0))
        )
        if abs(_wrap_deg(angle_deg - rt._zone_manager.intake_angle_deg)) <= intake_guard:
            return False
        if rt._near_angle(angle_deg, rt._exit_angle_deg):
            return False
        return abs(_wrap_deg(angle_deg - rt._exit_angle_deg)) <= lead_deg

    def mark_skip(self, reason: str) -> None:
        rt = self._rt
        rt._last_classify_skip = reason
        rt._classify_debug_counts[reason] = (
            rt._classify_debug_counts.get(reason, 0) + 1
        )

    def poll_futures(self, now_mono: float) -> None:
        rt = self._rt
        for dossier in rt._pieces.values():
            future = dossier.classify_future
            if future is None or not future.done():
                continue
            dossier.classify_future = None
            try:
                dossier.result = future.result(timeout=0.0)
            except Exception:
                rt._logger.exception(
                    "RuntimeC4: classifier future raised for piece=%s",
                    dossier.piece_uuid,
                )
                dossier.result = ClassifierResult(
                    part_id=None,
                    color_id=None,
                    category=None,
                    confidence=0.0,
                    algorithm=getattr(rt._classifier, "key", "unknown"),
                    latency_ms=0.0,
                    meta={"error": "future_raised"},
                )
            dossier.classified_ts = now_mono
            rt._bank_bind_classification(dossier.piece_uuid, dossier)
            result = dossier.result
            result_payload = rt._classification_payload(result)
            zone_payload = rt._dossier_event_payload(dossier, zone_state="active")
            payload: dict[str, Any] = {
                **zone_payload,
                "classified_ts_mono": now_mono,
                "confirmed_real": True,
                "stage": "classified",
                "classification_status": rt._classification_status(
                    result,
                    missing="unknown",
                ),
                "dossier": {
                    **zone_payload,
                    **result_payload,
                    "classified_at": now_mono,
                },
            }
            rt._publish(PIECE_CLASSIFIED, payload, now_mono)


def _synthetic_frame(*, feed_id: str, now_mono: float) -> FeedFrame:
    return FeedFrame(
        feed_id=feed_id,
        camera_id="synthetic",
        raw=None,
        gray=None,
        timestamp=now_mono,
        monotonic_ts=now_mono,
        frame_seq=0,
    )


def _wrap_deg(angle: float) -> float:
    return (float(angle) + 180.0) % 360.0 - 180.0


__all__ = ["C4ClassificationController"]
