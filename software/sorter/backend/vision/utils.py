import cv2
import numpy as np
from typing import Optional, Tuple


def maskCenterOfMass(mask: np.ndarray) -> Optional[Tuple[float, float]]:
    coords = np.argwhere(mask)
    if len(coords) == 0:
        return None
    center_y = float(np.mean(coords[:, 0]))
    center_x = float(np.mean(coords[:, 1]))
    return (center_x, center_y)


def masksOverlap(mask1: np.ndarray, mask2: np.ndarray) -> bool:
    overlap = np.logical_and(mask1, mask2)
    return bool(np.any(overlap))


def masksWithinDistance(
    mask1: np.ndarray, mask2: np.ndarray, threshold_px: int
) -> bool:
    kernel = np.ones((threshold_px * 2 + 1, threshold_px * 2 + 1), np.uint8)
    dilated = cv2.dilate(mask2.astype(np.uint8), kernel, iterations=1)
    return masksOverlap(mask1, dilated.astype(bool))


def maskMinDistance(object_mask: np.ndarray, target_mask: np.ndarray) -> int:
    object_coords = np.argwhere(object_mask)
    target_coords = np.argwhere(target_mask)

    if len(object_coords) == 0 or len(target_coords) == 0:
        return 999999

    # bounding box distance (much faster than pixel-by-pixel)
    obj_min_y, obj_min_x = object_coords.min(axis=0)
    obj_max_y, obj_max_x = object_coords.max(axis=0)
    tgt_min_y, tgt_min_x = target_coords.min(axis=0)
    tgt_max_y, tgt_max_x = target_coords.max(axis=0)

    dx = max(0, obj_min_x - tgt_max_x, tgt_min_x - obj_max_x)
    dy = max(0, obj_min_y - tgt_max_y, tgt_min_y - obj_max_y)

    return int(np.sqrt(dx * dx + dy * dy))
