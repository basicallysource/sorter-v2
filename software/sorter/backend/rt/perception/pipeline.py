"""PerceptionPipeline: detect -> track -> filter orchestration per feed."""

from __future__ import annotations

from dataclasses import dataclass

from rt.config.schema import PipelineConfig
from rt.contracts.detection import DetectionBatch, Detector
from rt.contracts.feed import Feed, FeedFrame, PolarZone, Zone
from rt.contracts.filters import Filter, FilterChain
from rt.contracts.registry import DETECTORS, FILTERS, TRACKERS
from rt.contracts.tracking import TrackBatch, Tracker


@dataclass(frozen=True, slots=True)
class PerceptionFrameState:
    frame: FeedFrame
    detections: DetectionBatch
    raw_tracks: TrackBatch
    filtered_tracks: TrackBatch


class PerceptionPipeline:
    """Runs detect -> track -> filter for a single feed/zone/detector."""

    def __init__(
        self,
        feed: Feed,
        zone: Zone,
        detector: Detector,
        tracker: Tracker,
        filters: FilterChain,
    ) -> None:
        self.feed = feed
        self.zone = zone
        self.detector = detector
        self.tracker = tracker
        self.filters = filters

    def process_frame_state(self, frame: FeedFrame) -> PerceptionFrameState:
        detections = self.detector.detect(frame, self.zone)
        raw_tracks = self.tracker.update(detections, frame)
        filtered_tracks = self.filters.apply(raw_tracks, frame)
        return PerceptionFrameState(
            frame=frame,
            detections=detections,
            raw_tracks=raw_tracks,
            filtered_tracks=filtered_tracks,
        )

    def process_frame(self, frame: FeedFrame) -> TrackBatch:
        return self.process_frame_state(frame).filtered_tracks


def build_pipeline_from_config(
    pipeline_config: PipelineConfig,
    feed: Feed,
    zone: Zone,
) -> PerceptionPipeline:
    """Construct a PerceptionPipeline via the strategy registries.

    Note: registry keys only become available once the implementing modules
    have been imported. Callers should ensure
    ``rt.perception.detectors``, ``.trackers`` and ``.filters`` are imported
    before building a pipeline.
    """
    det_cfg = dict(pipeline_config.detector)
    det_key = det_cfg.pop("key")
    det_params = dict(det_cfg.pop("params", {}) or {})
    detector = DETECTORS.create(det_key, **det_params)

    trk_cfg = dict(pipeline_config.tracker)
    trk_key = trk_cfg.pop("key")
    trk_params = dict(trk_cfg.pop("params", {}) or {})
    # Auto-wire polar geometry from a PolarZone if the tracker accepts it
    # and no explicit polar_center/radius_range was given.
    if isinstance(zone, PolarZone):
        trk_params.setdefault("polar_center", zone.center_xy)
        trk_params.setdefault("polar_radius_range", (zone.r_inner, zone.r_outer))
    tracker = TRACKERS.create(trk_key, **trk_params)

    filters_built: list[Filter] = []
    for f_cfg in pipeline_config.filters:
        f_params = dict(f_cfg.params or {})
        filters_built.append(FILTERS.create(f_cfg.key, **f_params))
    chain = FilterChain(tuple(filters_built))

    return PerceptionPipeline(
        feed=feed,
        zone=zone,
        detector=detector,
        tracker=tracker,
        filters=chain,
    )


__all__ = ["PerceptionFrameState", "PerceptionPipeline", "build_pipeline_from_config"]
