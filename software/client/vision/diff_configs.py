from dataclasses import dataclass


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
    # envelope improvements applied on top of calibration min/max
    envelope_margin: int = 4
    adaptive_std_k: float = 1.0

    # heatmap diff params
    pixel_thresh: int = 22
    blur_kernel: int = 7
    min_hot_pixels: int = 50
    trigger_score: int = 17
    min_contour_area: int = 70
    min_hot_thickness_px: int = 12
    max_contour_aspect: float = 10.0
    heat_gain: float = 2.0
    current_frames: int = 1
    min_bbox_dim: int = 20
    min_bbox_area: int = 0

    # crop sent to classifier
    crop_margin_px: int = 50
    edge_bias_mult: float = 2.0
    edge_bias_threshold_px: int = 80


DEFAULT_CAROUSEL_DIFF_CONFIG = CarouselDiffConfig()
DEFAULT_CLASSIFICATION_DIFF_CONFIG = ClassificationDiffConfig()
