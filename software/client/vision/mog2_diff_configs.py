from dataclasses import dataclass


@dataclass
class Mog2DiffConfig:
    color_mode: str = "lab"
    history: int = -1
    var_threshold: float = 25.0
    learning_rate: float = 0.003
    blur_kernel: int = 5
    min_contour_area: float = 350.0
    max_contour_area: int = 0
    morph_kernel: int = 5
    dilate_iterations: float = 1.0
    fg_threshold: int = 0
    n_mixtures: float = 4.0
    heat_gain: float = 5.0
    carousel_settle_ms: float = 500.0


DEFAULT_MOG2_DIFF_CONFIG = Mog2DiffConfig()
