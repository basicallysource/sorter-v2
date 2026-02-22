from dataclasses import dataclass, field
from typing import Optional, Tuple, List
import time
import numpy as np


@dataclass
class VisionResult:
    class_id: Optional[int]
    class_name: Optional[str]
    confidence: float
    bbox: Optional[Tuple[int, int, int, int]]
    timestamp: float
    from_cache: bool = False
    created_at: float = field(default_factory=time.time)


@dataclass
class DetectedMask:
    mask: np.ndarray
    confidence: float
    class_id: int
    instance_id: int
    from_cache: bool = False
    created_at: float = field(default_factory=time.time)


@dataclass
class CameraFrame:
    raw: np.ndarray
    annotated: Optional[np.ndarray]
    results: List[VisionResult]
    timestamp: float
    segmentation_map: Optional[np.ndarray] = field(default=None)
