from dataclasses import dataclass

from .detection_registry import (
    ClassificationDetectionAlgorithm,
)


@dataclass
class CarouselDiffConfig:
    # carousel uses captureBaseline (single snapshot, no envelope)
    pixel_thresh: int = 8
    blur_kernel: int = 5
    min_hot_pixels: int = 50
    trigger_score: int = 17
    min_contour_area: int = 100
    min_hot_thickness_px: int = 12
    max_contour_aspect: float = 3.0
    heat_gain: float = 12.0
    current_frames: int = 3
    min_bbox_dim: int = 100
    min_bbox_area: int = 20000


@dataclass
class ClassificationDiffConfig:
    algorithm: ClassificationDetectionAlgorithm = "baseline_diff"
    color_mode: str = "lab"
    classification_scale: float = 0.25

    # envelope improvements applied on top of calibration min/max
    envelope_margin: int = 8
    adaptive_std_k: float = 0.5

    # heatmap diff params
    pixel_thresh: int = 3
    color_thresh_ab: int = 15
    blur_kernel: int = 3
    min_hot_pixels: int = 50
    trigger_score: int = 17
    min_contour_area: int = 500
    min_hot_thickness_px: int = 12
    hot_erode_iters: int = 4
    hot_regrow_iters: int = 8
    max_contour_aspect: float = 10.0
    heat_gain: float = 2.0
    current_frames: int = 1
    min_bbox_dim: int = 20
    min_bbox_area: int = 0

    # crop sent to classifier
    crop_margin_px: int = 100
    edge_bias_mult: float = 1.5
    edge_bias_threshold_px: int = 1000

    # tuning script params (not currently used in runtime path)
    bbox_diff_thresh: float = 0.0


DEFAULT_CAROUSEL_DIFF_CONFIG = CarouselDiffConfig()
DEFAULT_CLASSIFICATION_DIFF_CONFIG = ClassificationDiffConfig()
