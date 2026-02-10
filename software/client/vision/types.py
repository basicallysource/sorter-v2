from dataclasses import dataclass, field
from typing import Optional, Tuple, List
import numpy as np


@dataclass
class VisionResult:
    class_id: Optional[int]
    class_name: Optional[str]
    confidence: float
    bbox: Optional[Tuple[int, int, int, int]]
    timestamp: float


@dataclass
class DetectedMask:
    mask: np.ndarray
    confidence: float
    class_id: int
    instance_id: int


@dataclass
class CameraFrame:
    raw: np.ndarray
    annotated: Optional[np.ndarray]
    results: List[VisionResult]
    timestamp: float
    segmentation_map: Optional[np.ndarray] = field(default=None)
