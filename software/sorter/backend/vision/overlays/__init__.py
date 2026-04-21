"""Modular frame annotation overlays for camera feeds."""

from .base import FrameOverlay
from .region import RegionOverlay, ChannelRegionOverlay
from .detector import DetectorOverlay, DynamicDetectionOverlay
from .heatmap import HeatmapOverlay
from .classification import ClassificationOverlay
from .classification_zones import ClassificationChannelZoneOverlay
from .ignored_regions import IgnoredRegionOverlay
from .tracker import TrackOverlay

__all__ = [
    "FrameOverlay",
    "RegionOverlay",
    "ChannelRegionOverlay",
    "DetectorOverlay",
    "DynamicDetectionOverlay",
    "HeatmapOverlay",
    "ClassificationOverlay",
    "ClassificationChannelZoneOverlay",
    "IgnoredRegionOverlay",
    "TrackOverlay",
]
