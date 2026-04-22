from __future__ import annotations

from typing import Iterable


def translate_bbox_to_crop(
    bbox: tuple[int, int, int, int] | None,
    crop_bbox: tuple[int, int, int, int] | None,
) -> tuple[int, int, int, int] | None:
    if bbox is None or crop_bbox is None:
        return bbox

    crop_x1, crop_y1, crop_x2, crop_y2 = crop_bbox
    crop_w = max(0, crop_x2 - crop_x1)
    crop_h = max(0, crop_y2 - crop_y1)
    if crop_w == 0 or crop_h == 0:
        return None

    x1 = max(0, min(crop_w, bbox[0] - crop_x1))
    y1 = max(0, min(crop_h, bbox[1] - crop_y1))
    x2 = max(0, min(crop_w, bbox[2] - crop_x1))
    y2 = max(0, min(crop_h, bbox[3] - crop_y1))
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def translate_bboxes_to_crop(
    bboxes: Iterable[tuple[int, int, int, int]],
    crop_bbox: tuple[int, int, int, int] | None,
) -> list[tuple[int, int, int, int]]:
    translated: list[tuple[int, int, int, int]] = []
    for bbox in bboxes:
        projected = translate_bbox_to_crop(bbox, crop_bbox)
        if projected is not None:
            translated.append(projected)
    return translated
