from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Mapping

from rt.contracts.classification import ClassifierResult
from rt.services.sector_carousel.handler import SectorCarouselHandler


def install_sector_carousel_handler(
    *,
    orchestrator: Any,
    c3: Any,
    c4: Any,
    distributor: Any,
    perception_sources: Mapping[str, Any],
    classifier: Any,
    crop_provider: Callable[[Any, Any], Any | None],
    irl: Any,
    event_bus: Any,
    c4_eject: Callable[[], bool],
    fallback_transport: Callable[[float], bool],
    logger: logging.Logger,
) -> SectorCarouselHandler:
    """Build and attach the C3 -> C4 sector-carousel production bridge."""
    handler_ref: list[SectorCarouselHandler] = []

    def _latest_state(runner: Any) -> Any | None:
        latest_state = getattr(runner, "latest_state", None)
        return latest_state() if callable(latest_state) else None

    def _empty_result(slot: Any, reason: str) -> ClassifierResult:
        return ClassifierResult(
            part_id=None,
            color_id=None,
            category=None,
            confidence=0.0,
            algorithm="sector_carousel",
            latency_ms=0.0,
            meta={"reason": reason, "slot_index": slot.slot_index},
        )

    def _capture_start(piece_uuid: str, _slot: Any) -> None:
        runner = perception_sources.get("c4_feed")
        handler = handler_ref[0] if handler_ref else None
        if runner is None or handler is None:
            return

        def _capture_window() -> None:
            frame_pool: list[Any] = []
            seen_seq: set[int] = set()
            deadline = time.monotonic() + 0.8
            first_detection_at: float | None = None
            while time.monotonic() < deadline:
                state = _latest_state(runner)
                frame = getattr(state, "frame", None) if state is not None else None
                seq = getattr(frame, "frame_seq", None)
                if isinstance(seq, int) and seq not in seen_seq:
                    seen_seq.add(seq)
                    frame_pool.append(state)
                    detections = getattr(state, "detections", None)
                    entries = (
                        getattr(detections, "detections", None)
                        if detections is not None
                        else None
                    )
                    if entries and first_detection_at is None:
                        first_detection_at = time.monotonic()
                if (
                    first_detection_at is not None
                    and time.monotonic() - first_detection_at > 0.25
                ):
                    break
                time.sleep(0.02)
            handler.attach_frame_pool(piece_uuid, frame_pool, now_mono=time.monotonic())

        threading.Thread(
            target=_capture_window,
            name=f"SectorCarouselCapture[{piece_uuid}]",
            daemon=True,
        ).start()

    def _classifier_submit(slot: Any) -> Any:
        runner = perception_sources.get("c4_feed")
        latest_state = _latest_state(runner) if runner is not None else None
        frame = getattr(latest_state, "frame", None) if latest_state is not None else None
        batch = (
            getattr(latest_state, "filtered_tracks", None)
            if latest_state is not None
            else None
        )
        tracks = list(getattr(batch, "tracks", ()) or ())
        if not tracks:
            batch = (
                getattr(latest_state, "raw_tracks", None)
                if latest_state is not None
                else None
            )
            tracks = list(getattr(batch, "tracks", ()) or ())
        if frame is None or not tracks:
            return _empty_result(slot, "no_static_track")
        track = max(
            tracks,
            key=lambda tr: (
                float(getattr(tr, "score", 0.0) or 0.0),
                int(getattr(tr, "hit_count", 0) or 0),
            ),
        )
        crop = crop_provider(frame, track)
        if crop is None:
            return _empty_result(slot, "no_crop")
        return classifier.classify_async(track, frame, crop)

    def _c4_hw_busy() -> bool:
        hw = getattr(c4, "_hw", None)
        busy_fn = getattr(hw, "busy", None)
        if callable(busy_fn) and bool(busy_fn()):
            return True
        stepper = getattr(irl, "carousel_stepper", None)
        stopped = getattr(stepper, "stopped", True)
        return stopped is False

    handler = SectorCarouselHandler(
        c4_transport=getattr(c4, "_transport_move", fallback_transport),
        c4_eject=c4_eject,
        distributor_port=distributor,
        classifier_submit=_classifier_submit,
        capture_start=_capture_start,
        c4_hw_busy=_c4_hw_busy,
        event_bus=event_bus,
        sector_step_deg=72.0,
        settle_s=0.35,
        auto_rotate=True,
        rotate_cooldown_s=8.0,
        rotation_chunk_deg=2.0,
        rotation_chunk_settle_s=0.12,
        require_phase_verification=True,
        logger=logger,
    )
    handler_ref.append(handler)

    # Sector mode owns the physical C3 -> C4 landing gate. C3 must obtain
    # this lease before firing its eject pulse; the later C3_HANDOFF_TRIGGER
    # is only accepted if it carries the same lease id.
    c3.set_downstream_landing_lease_required(True)
    try:
        c3.set_landing_lease_port(handler.landing_lease_port())
    except Exception:
        logger.exception("rt.bootstrap: c3 sector landing-lease wiring failed")

    orchestrator.attach_sector_carousel_handler(handler)
    orchestrator.set_c4_mode("sector_carousel")
    return handler


__all__ = ["install_sector_carousel_handler"]
