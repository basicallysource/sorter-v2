import numpy as np
import cv2
from .regions import RegionName, Region

DEFAULT_REGION_SIZE = 100

DEFAULT_REGION_POSITIONS: dict[RegionName, tuple[int, int, tuple[int, int, int]]] = {
    RegionName.CHANNEL_2: (400, 200, (0, 255, 255)),
    RegionName.CHANNEL_3: (250, 200, (255, 0, 255)),
    RegionName.CHANNEL_2_DROPZONE: (450, 100, (0, 180, 0)),
    RegionName.CHANNEL_2_PRECISE: (450, 300, (0, 100, 255)),
    RegionName.CHANNEL_3_DROPZONE: (300, 100, (255, 180, 0)),
    RegionName.CHANNEL_3_PRECISE: (300, 300, (100, 0, 255)),
    RegionName.CAROUSEL_PLATFORM: (100, 350, (255, 255, 0)),
}


class DefaultRegionProvider:
    _cached_regions: dict[RegionName, Region]
    _cached_frame_shape: tuple[int, int]

    def __init__(self) -> None:
        self._cached_regions = {}
        self._cached_frame_shape = (0, 0)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def getRegions(self, frame: np.ndarray) -> dict[RegionName, Region]:
        h, w = frame.shape[:2]
        if (h, w) == self._cached_frame_shape and self._cached_regions:
            return self._cached_regions

        regions: dict[RegionName, Region] = {}
        half = DEFAULT_REGION_SIZE // 2
        for name, (cx, cy, _color) in DEFAULT_REGION_POSITIONS.items():
            mask = np.zeros((h, w), dtype=np.bool_)
            x1 = max(0, cx - half)
            y1 = max(0, cy - half)
            x2 = min(w, cx + half)
            y2 = min(h, cy + half)
            mask[y1:y2, x1:x2] = True
            regions[name] = Region(name, mask)

        self._cached_regions = regions
        self._cached_frame_shape = (h, w)
        return regions

    def annotateFrame(self, frame: np.ndarray) -> np.ndarray:
        annotated = frame.copy()
        half = DEFAULT_REGION_SIZE // 2
        for name, (cx, cy, color) in DEFAULT_REGION_POSITIONS.items():
            cv2.rectangle(
                annotated,
                (cx - half, cy - half),
                (cx + half, cy + half),
                color,
                2,
            )
            cv2.putText(
                annotated,
                name.value,
                (cx - half, cy - half - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35,
                color,
                1,
            )
        return annotated
