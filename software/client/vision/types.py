from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np


@dataclass
class VisionResult:
    class_id: Optional[int]
    class_name: Optional[str]
    confidence: float
    bbox: Optional[Tuple[int, int, int, int]]
    timestamp: float


@dataclass
class CameraFrame:
    raw: np.ndarray
    annotated: Optional[np.ndarray]
    result: Optional[VisionResult]
    timestamp: float
