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
class CameraFrame:
    raw: np.ndarray
    annotated: Optional[np.ndarray]
    results: List[VisionResult]
    timestamp: float
    segmentation_map: Optional[np.ndarray] = field(default=None)
    # The camera's own JPEG for this frame, untouched (no rotation, flip or
    # colour profile applied): what the recording tee ships. None when the
    # capture path could not hand us the compressed buffer (non-MJPEG source,
    # URL source, or a driver that ignores CAP_PROP_CONVERT_RGB).
    raw_jpeg: Optional[bytes] = field(default=None, repr=False)
