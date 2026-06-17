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
    # HSV detection: when True the pipeline runs the envelope test on hue +
    # saturation (V discarded) instead of grayscale luminance. The calibration
    # script must have produced the *_baseline_{h,s}_{min,max}.png envelopes;
    # set False to fall back to the legacy grayscale *_baseline_{min,max}.png.
    use_hsv: bool = True
    # Also use V (value/brightness) as a third channel. Opaque pieces block the
    # backlight and read darker than the glowing floor, so V catches pieces that
    # are hue/saturation-contaminated against the magenta background. The floor's
    # per-pixel V envelope is permissive exactly where the floor varies (tray
    # edges), so this self-gates and stays clean on the background.
    use_value: bool = True
    # Below this saturation (0-255) hue is too noisy/biased to trust (the camera
    # has a green channel cast WB can't fully neutralize), so a low-sat pixel is
    # judged on saturation (and value) difference alone. Empirically tuned; ~60.
    low_sat_thresh: int = 60

    # envelope improvements applied on top of calibration min/max. Saturation and
    # value are noisier than hue under fixed lighting, so they get wider margins.
    envelope_margin: int = 4         # hue (and the legacy gray) envelope margin
    envelope_margin_s: int = 8       # saturation envelope margin (HSV mode only)
    envelope_margin_v: int = 8       # value envelope margin (HSV+value mode only)
    adaptive_std_k: float = 1.0

    # heatmap diff params. In HSV mode the combined diff is normalized to 0-255
    # (hue circular distance scaled up from its 0-90 range), so pixel_thresh
    # carries roughly the same meaning it did for the 0-255 grayscale diff.
    # Tuned via tune_classification_detection.py to catch contaminated reds; the
    # floor sits at ~0 diff after a fresh baseline, leaving headroom. Validate
    # empty-tray false positives across a full carousel rotation after changing.
    pixel_thresh: int = 10
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
