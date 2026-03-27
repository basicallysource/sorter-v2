from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any

import cv2
import numpy as np

try:
    from calibration_reference import REFERENCE_TILE_HEX, REFERENCE_TILE_RGB
except ModuleNotFoundError:
    from .calibration_reference import REFERENCE_TILE_HEX, REFERENCE_TILE_RGB

_PATTERN_CANDIDATES: list[tuple[int, int]] = []
for cols, rows in [
    (4, 6),
    (5, 7),
    (6, 8),
    (6, 9),
    (7, 10),
    (8, 11),
    (9, 12),
    (10, 13),
    (10, 14),
    (11, 15),
    (12, 16),
    (13, 18),
]:
    _PATTERN_CANDIDATES.append((cols, rows))
    _PATTERN_CANDIDATES.append((rows, cols))


@dataclass(frozen=True)
class CellSample:
    mean_bgr: tuple[float, float, float]
    mean_lab: tuple[float, float, float]
    mean_hsv: tuple[float, float, float]
    luma: float
    saturation: float
    clip_fraction: float
    shadow_fraction: float


@dataclass(frozen=True)
class CalibrationAnalysis:
    pattern_size: tuple[int, int]
    score: float
    total_cells: int
    bright_cell_count: int
    dark_cell_count: int
    color_cell_count: int
    white_luma_mean: float
    black_luma_mean: float
    neutral_contrast: float
    clipped_white_fraction: float
    shadow_black_fraction: float
    white_balance_cast: float
    color_separation: float
    colorfulness: float
    reference_color_error_mean: float
    board_bbox: tuple[int, int, int, int]
    normalized_board_bbox: tuple[float, float, float, float]
    neutral_mean_bgr: tuple[float, float, float]
    tile_samples: dict[str, dict[str, float]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_size": [self.pattern_size[0], self.pattern_size[1]],
            "score": self.score,
            "total_cells": self.total_cells,
            "bright_cell_count": self.bright_cell_count,
            "dark_cell_count": self.dark_cell_count,
            "color_cell_count": self.color_cell_count,
            "white_luma_mean": self.white_luma_mean,
            "black_luma_mean": self.black_luma_mean,
            "neutral_contrast": self.neutral_contrast,
            "clipped_white_fraction": self.clipped_white_fraction,
            "shadow_black_fraction": self.shadow_black_fraction,
            "white_balance_cast": self.white_balance_cast,
            "color_separation": self.color_separation,
            "colorfulness": self.colorfulness,
            "reference_color_error_mean": self.reference_color_error_mean,
            "board_bbox": [
                self.board_bbox[0],
                self.board_bbox[1],
                self.board_bbox[2],
                self.board_bbox[3],
            ],
            "normalized_board_bbox": [
                self.normalized_board_bbox[0],
                self.normalized_board_bbox[1],
                self.normalized_board_bbox[2],
                self.normalized_board_bbox[3],
            ],
            "neutral_mean_bgr": [
                self.neutral_mean_bgr[0],
                self.neutral_mean_bgr[1],
                self.neutral_mean_bgr[2],
            ],
            "reference_palette": {
                label: {
                    "hex": REFERENCE_TILE_HEX[label],
                    "rgb": [REFERENCE_TILE_RGB[label][0], REFERENCE_TILE_RGB[label][1], REFERENCE_TILE_RGB[label][2]],
                }
                for label in ("white", "black", "blue", "red", "green", "yellow")
            },
            "tile_samples": self.tile_samples,
        }


@dataclass(frozen=True)
class TargetColorRegion:
    center: tuple[float, float]
    area: float


_TARGET_BOARD_WIDTH = 4.0
_TARGET_BOARD_HEIGHT = 6.0
_TARGET_ROTATIONS = (0, 90, 180, 270)

_TARGET_PATTERN_ROWS: tuple[tuple[str, ...], ...] = (
    ("white", "black", "white", "black"),
    ("blue", "blue", "red", "red"),
    ("blue", "blue", "red", "red"),
    ("green", "green", "yellow", "yellow"),
    ("green", "green", "yellow", "yellow"),
    ("black", "white", "black", "white"),
)

_TARGET_COLOR_ANCHOR_POINTS: dict[str, tuple[float, float]] = {
    "blue": (1.0, 2.0),
    "red": (3.0, 2.0),
    "green": (1.0, 4.0),
    "yellow": (3.0, 4.0),
}

_TARGET_TILE_GROUPS: dict[str, tuple[tuple[int, int], ...]] = {
    "white_top": ((0, 0), (2, 0)),
    "black_top": ((1, 0), (3, 0)),
    "blue": ((0, 1), (1, 1), (0, 2), (1, 2)),
    "red": ((2, 1), (3, 1), (2, 2), (3, 2)),
    "green": ((0, 3), (1, 3), (0, 4), (1, 4)),
    "yellow": ((2, 3), (3, 3), (2, 4), (3, 4)),
    "black_bottom": ((0, 5), (2, 5)),
    "white_bottom": ((1, 5), (3, 5)),
}

_TARGET_TILE_GROUP_EXPECTATION: dict[str, str] = {
    "white_top": "white",
    "black_top": "black",
    "blue": "blue",
    "red": "red",
    "green": "green",
    "yellow": "yellow",
    "black_bottom": "black",
    "white_bottom": "white",
}

_REFERENCE_TILE_LAB: dict[str, tuple[float, float, float]] = {
    label: tuple(
        float(value)
        for value in cv2.cvtColor(
            np.array([[[rgb[2], rgb[1], rgb[0]]]], dtype=np.uint8),
            cv2.COLOR_BGR2LAB,
        )[0, 0].astype(np.float32).tolist()
    )
    for label, rgb in REFERENCE_TILE_RGB.items()
}


def analyze_calibration_target(frame: np.ndarray) -> CalibrationAnalysis | None:
    if frame is None or frame.size == 0:
        return None

    fixed_target = _analyze_fixed_color_target(frame)
    if fixed_target is not None:
        return fixed_target

    detection = _detect_checkerboard(frame)
    if detection is not None:
        pattern_size, corners = detection
        cells = _sample_cells(frame, corners, pattern_size)
        if len(cells) >= 8:
            analysis = _build_analysis_from_cells(frame.shape, pattern_size, cells, _corners_bbox(corners))
            if analysis is not None:
                return analysis

    plate_quad = _detect_plate_quad(frame)
    if plate_quad is None:
        return None
    return _analyze_plate_quad(frame, plate_quad)


def _detect_checkerboard(frame: np.ndarray) -> tuple[tuple[int, int], np.ndarray] | None:
    max_dim = max(frame.shape[0], frame.shape[1])
    scale = min(1.0, 1280.0 / float(max_dim))
    if scale < 1.0:
        resized = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    else:
        resized = frame

    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    flags = 0
    if hasattr(cv2, "CALIB_CB_NORMALIZE_IMAGE"):
        flags |= cv2.CALIB_CB_NORMALIZE_IMAGE
    if hasattr(cv2, "CALIB_CB_EXHAUSTIVE"):
        flags |= cv2.CALIB_CB_EXHAUSTIVE
    if hasattr(cv2, "CALIB_CB_ACCURACY"):
        flags |= cv2.CALIB_CB_ACCURACY

    best: tuple[tuple[int, int], np.ndarray] | None = None
    best_area = -1

    use_sb = hasattr(cv2, "findChessboardCornersSB")
    for pattern_size in _PATTERN_CANDIDATES:
        try:
            if use_sb:
                ok, corners = cv2.findChessboardCornersSB(gray, pattern_size, flags=flags)
            else:
                ok, corners = cv2.findChessboardCorners(gray, pattern_size, flags=flags)
        except Exception:
            ok, corners = False, None
        if not ok or corners is None:
            continue

        corners = np.asarray(corners, dtype=np.float32).reshape(-1, 2)
        area = _bbox_area(_corners_bbox(corners))
        if area > best_area:
            best_area = area
            if scale < 1.0:
                corners = corners / scale
            best = (pattern_size, corners)

    return best


def _analyze_fixed_color_target(frame: np.ndarray) -> CalibrationAnalysis | None:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    region_candidates = {
        "red": _collect_color_regions(
            cv2.inRange(hsv, np.array([0, 70, 25]), np.array([12, 255, 255]))
            | cv2.inRange(hsv, np.array([165, 70, 25]), np.array([179, 255, 255])),
            min_area=25.0,
            max_regions=12,
        ),
        "yellow": _collect_color_regions(
            cv2.inRange(hsv, np.array([15, 35, 20]), np.array([50, 255, 255])),
            min_area=25.0,
            max_regions=12,
        ),
        "green": _collect_color_regions(
            cv2.inRange(hsv, np.array([35, 20, 15]), np.array([100, 255, 255])),
            min_area=25.0,
            max_regions=12,
        ),
        "blue": _collect_color_regions(
            cv2.inRange(hsv, np.array([80, 25, 15]), np.array([145, 255, 255])),
            min_area=25.0,
            max_regions=12,
        ),
    }
    available_anchor_colors = [label for label, candidates in region_candidates.items() if candidates]
    if len(available_anchor_colors) < 3:
        return None

    best: tuple[float, CalibrationAnalysis] | None = None
    for rotation in _TARGET_ROTATIONS:
        rotated_anchor_points = {
            label: _rotate_target_point(point, rotation)
            for label, point in _TARGET_COLOR_ANCHOR_POINTS.items()
        }
        for anchor_labels in _color_anchor_combinations(available_anchor_colors):
            src = np.array([rotated_anchor_points[label] for label in anchor_labels], dtype=np.float32)
            region_lists = [region_candidates[label][:8] for label in anchor_labels]
            for selected in product(*region_lists):
                dst = np.array([region.center for region in selected], dtype=np.float32)
                if not _target_anchor_cluster_is_plausible(dst):
                    continue
                affine = cv2.getAffineTransform(src, dst)
                analysis = _analyze_fixed_color_candidate(frame, affine, rotation)
                if analysis is None:
                    continue
                arrangement_score = analysis.score - _affine_residual(affine, src, dst) * 1.25
                if best is None or arrangement_score > best[0]:
                    best = (arrangement_score, analysis)

    return best[1] if best is not None else None


def _collect_color_regions(
    mask: np.ndarray,
    *,
    min_area: float = 220.0,
    max_regions: int = 8,
) -> list[TargetColorRegion]:
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    cleaned = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[TargetColorRegion] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < min_area:
            continue
        moments = cv2.moments(contour)
        if moments["m00"] <= 1e-6:
            continue
        candidates.append(
            TargetColorRegion(
                center=(float(moments["m10"] / moments["m00"]), float(moments["m01"] / moments["m00"])),
                area=area,
            )
        )
    candidates.sort(key=lambda region: region.area, reverse=True)
    return candidates[:max_regions]


def _color_anchor_combinations(colors: list[str]) -> list[tuple[str, str, str]]:
    ordered = [label for label in ("blue", "red", "green", "yellow") if label in colors]
    combinations: list[tuple[str, str, str]] = []
    if len(ordered) < 3:
        return combinations
    for index in range(len(ordered)):
        for middle in range(index + 1, len(ordered)):
            for last in range(middle + 1, len(ordered)):
                combinations.append((ordered[index], ordered[middle], ordered[last]))
    return combinations


def _target_anchor_cluster_is_plausible(points: np.ndarray) -> bool:
    if points.shape[0] < 3:
        return False
    span = np.ptp(points, axis=0)
    if float(max(span)) > 240.0 or float(min(span)) < 8.0:
        return False
    bbox_area = float(max(span[0], 1.0) * max(span[1], 1.0))
    return bbox_area <= 18_000.0


def _affine_residual(affine: np.ndarray, src: np.ndarray, dst: np.ndarray) -> float:
    predicted = _apply_affine(affine, src)
    return float(np.mean(np.linalg.norm(predicted - dst, axis=1)))


def _apply_affine(affine: np.ndarray, points: np.ndarray) -> np.ndarray:
    return (points @ affine[:, :2].T) + affine[:, 2]


def _analyze_fixed_color_candidate(
    frame: np.ndarray,
    affine: np.ndarray,
    rotation: int,
) -> CalibrationAnalysis | None:
    board_width, board_height = _target_board_dimensions(rotation)
    origin = _apply_affine(affine, np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32))
    x_scale = float(np.linalg.norm(origin[1] - origin[0]))
    y_scale = float(np.linalg.norm(origin[2] - origin[0]))
    if x_scale < 7.0 or y_scale < 7.0 or x_scale > 260.0 or y_scale > 260.0:
        return None

    board_quad = _apply_affine(
        affine,
        np.array(
            [[0.0, 0.0], [board_width, 0.0], [board_width, board_height], [0.0, board_height]],
            dtype=np.float32,
        ),
    )
    bbox = _corners_bbox(board_quad)
    if _bbox_area(bbox) < 1_500:
        return None
    if (
        bbox[0] < 0
        or bbox[1] < 0
        or bbox[2] > frame.shape[1]
        or bbox[3] > frame.shape[0]
    ):
        return None

    cell_samples: dict[tuple[int, int], CellSample] = {}
    samples_by_expectation: dict[str, list[CellSample]] = {
        "white": [],
        "black": [],
        "blue": [],
        "red": [],
        "green": [],
        "yellow": [],
    }
    layout_score = 0.0
    for row_index, row_labels in enumerate(_TARGET_PATTERN_ROWS):
        for column_index, label in enumerate(row_labels):
            quad = _apply_affine(
                affine,
                _rotate_target_quad(
                    np.array(
                        [
                            [float(column_index), float(row_index)],
                            [float(column_index + 1), float(row_index)],
                            [float(column_index + 1), float(row_index + 1)],
                            [float(column_index), float(row_index + 1)],
                        ],
                        dtype=np.float32,
                    ),
                    rotation,
                ),
            )
            sample = _sample_quad(frame, _shrink_quad(quad, factor=0.72))
            if sample is None:
                return None
            cell_samples[(column_index, row_index)] = sample
            samples_by_expectation[label].append(sample)
            layout_score += _expected_region_score(sample, label)

    if layout_score < 280.0:
        return None

    white_samples = samples_by_expectation["white"]
    black_samples = samples_by_expectation["black"]
    merged_color_samples = {
        label: _merge_sample_group(samples_by_expectation[label])
        for label in ("blue", "red", "green", "yellow")
    }
    merged_tile_samples = {
        tile_label: _merge_sample_group([cell_samples[cell] for cell in cells])
        for tile_label, cells in _TARGET_TILE_GROUPS.items()
    }
    color_cells = [
        merged_color_samples["blue"],
        merged_color_samples["red"],
        merged_color_samples["green"],
        merged_color_samples["yellow"],
    ]
    white_luma = float(np.mean([sample.luma for sample in white_samples]))
    black_luma = float(np.mean([sample.luma for sample in black_samples]))
    clipped_white_fraction = float(np.mean([sample.clip_fraction for sample in white_samples]))
    shadow_black_fraction = float(np.mean([sample.shadow_fraction for sample in black_samples]))
    white_balance_cast = _white_balance_cast(white_samples)
    color_separation = _color_separation(color_cells)
    colorfulness = float(np.mean([cell.saturation for cell in color_cells]))
    color_clip_fraction_mean = float(np.mean([cell.clip_fraction for cell in color_cells]))
    color_clip_fraction_max = float(np.max([cell.clip_fraction for cell in color_cells]))
    reference_errors = [
        *[_reference_lab_distance(sample, "white") for sample in white_samples],
        *[_reference_lab_distance(sample, "black") for sample in black_samples],
        _reference_lab_distance(merged_color_samples["red"], "red"),
        _reference_lab_distance(merged_color_samples["yellow"], "yellow"),
        _reference_lab_distance(merged_color_samples["green"], "green"),
        _reference_lab_distance(merged_color_samples["blue"], "blue"),
    ]
    reference_color_error_mean = float(
        np.mean(reference_errors)
    )
    reference_color_error_max = float(np.max(reference_errors))
    neutral_contrast = max(0.0, white_luma - black_luma)
    score = _score_analysis(
        white_luma=white_luma,
        black_luma=black_luma,
        clipped_white_fraction=clipped_white_fraction,
        shadow_black_fraction=shadow_black_fraction,
        white_balance_cast=white_balance_cast,
        neutral_contrast=neutral_contrast,
        color_separation=color_separation,
        colorfulness=colorfulness,
        color_count=len(color_cells),
        reference_color_error_mean=reference_color_error_mean,
        reference_color_error_max=reference_color_error_max,
        color_clip_fraction_mean=color_clip_fraction_mean,
        color_clip_fraction_max=color_clip_fraction_max,
    )

    return CalibrationAnalysis(
        pattern_size=(int(board_width), int(board_height)),
        score=float(score + layout_score * 0.25),
        total_cells=len(cell_samples),
        bright_cell_count=len(white_samples),
        dark_cell_count=len(black_samples),
        color_cell_count=len(color_cells),
        white_luma_mean=white_luma,
        black_luma_mean=black_luma,
        neutral_contrast=neutral_contrast,
        clipped_white_fraction=clipped_white_fraction,
        shadow_black_fraction=shadow_black_fraction,
        white_balance_cast=white_balance_cast,
        color_separation=color_separation,
        colorfulness=colorfulness,
        reference_color_error_mean=reference_color_error_mean,
        board_bbox=bbox,
        normalized_board_bbox=_normalized_bbox(frame.shape, bbox),
        neutral_mean_bgr=tuple(
            float(v)
            for v in np.mean(np.array([sample.mean_bgr for sample in white_samples], dtype=np.float32), axis=0).tolist()
        ),
        tile_samples={
            label: {
                "luma": float(merged.luma),
                "saturation": float(merged.saturation),
                "clip_fraction": float(merged.clip_fraction),
                "shadow_fraction": float(merged.shadow_fraction),
                "reference_error": float(
                    _reference_lab_distance(merged, _TARGET_TILE_GROUP_EXPECTATION[label])
                ),
                "reference_match_percent": float(
                    _reference_match_percent(
                        _reference_lab_distance(merged, _TARGET_TILE_GROUP_EXPECTATION[label])
                    )
                ),
            }
            for label, merged in merged_tile_samples.items()
        },
    )


def _expected_region_score(sample: CellSample, label: str) -> float:
    if label == "black":
        return 28.0 - abs(sample.luma - 24.0) * 0.28 - max(0.0, sample.saturation - 60.0) * 0.16
    if label == "white":
        return 30.0 - abs(sample.luma - 205.0) * 0.12 - sample.saturation * 0.09 - sample.clip_fraction * 55.0
    hue_targets = {
        "red": 0.0,
        "yellow": 28.0,
        "green": 60.0,
        "blue": 108.0,
    }
    hue = sample.mean_hsv[0]
    hue_error = min(abs(hue - hue_targets[label]), 180.0 - abs(hue - hue_targets[label]))
    return 24.0 - hue_error * 0.45 + min(sample.saturation, 255.0) * 0.04 - abs(sample.luma - 150.0) * 0.03


def _target_board_dimensions(rotation: int) -> tuple[float, float]:
    if rotation in (0, 180):
        return (_TARGET_BOARD_WIDTH, _TARGET_BOARD_HEIGHT)
    return (_TARGET_BOARD_HEIGHT, _TARGET_BOARD_WIDTH)


def _rotate_target_point(point: tuple[float, float], rotation: int) -> tuple[float, float]:
    x, y = point
    if rotation == 0:
        return (x, y)
    if rotation == 90:
        return (_TARGET_BOARD_HEIGHT - y, x)
    if rotation == 180:
        return (_TARGET_BOARD_WIDTH - x, _TARGET_BOARD_HEIGHT - y)
    if rotation == 270:
        return (y, _TARGET_BOARD_WIDTH - x)
    raise ValueError(f"Unsupported target rotation: {rotation}")


def _rotate_target_quad(quad: np.ndarray, rotation: int) -> np.ndarray:
    rotated = np.array([_rotate_target_point((float(x), float(y)), rotation) for x, y in quad], dtype=np.float32)
    ordered = _order_quad(rotated)
    return ordered if ordered is not None else rotated


def _merge_sample_group(samples: list[CellSample]) -> CellSample:
    mean_bgr = np.mean(np.array([sample.mean_bgr for sample in samples], dtype=np.float32), axis=0)
    bgr_patch = np.array([[mean_bgr]], dtype=np.uint8)
    mean_lab_arr = cv2.cvtColor(bgr_patch, cv2.COLOR_BGR2LAB)[0, 0].astype(np.float32)
    mean_hsv_arr = cv2.cvtColor(bgr_patch, cv2.COLOR_BGR2HSV)[0, 0].astype(np.float32)
    return CellSample(
        mean_bgr=tuple(float(value) for value in mean_bgr.tolist()),
        mean_lab=(float(mean_lab_arr[0]), float(mean_lab_arr[1]), float(mean_lab_arr[2])),
        mean_hsv=(float(mean_hsv_arr[0]), float(mean_hsv_arr[1]), float(mean_hsv_arr[2])),
        luma=float(np.mean([sample.luma for sample in samples])),
        saturation=float(np.mean([sample.saturation for sample in samples])),
        clip_fraction=float(np.mean([sample.clip_fraction for sample in samples])),
        shadow_fraction=float(np.mean([sample.shadow_fraction for sample in samples])),
    )


def _reference_lab_distance(sample: CellSample, label: str) -> float:
    reference = _REFERENCE_TILE_LAB[label]
    sample_lab = np.array(sample.mean_lab, dtype=np.float32)
    reference_lab = np.array(reference, dtype=np.float32)
    return float(np.linalg.norm(sample_lab - reference_lab))


def _reference_match_percent(distance: float) -> float:
    normalized = max(0.0, min(1.0, 1.0 - (distance / 80.0)))
    return float(normalized * 100.0)


def _detect_plate_quad(frame: np.ndarray) -> np.ndarray | None:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    value = hsv[:, :, 2]
    saturation = hsv[:, :, 1]

    bright_mask = np.where((value >= 105) & (saturation <= 125), 255, 0).astype(np.uint8)
    kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    bright_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_CLOSE, kernel_close)
    bright_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_OPEN, kernel_open)

    contours, _ = cv2.findContours(bright_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    frame_area = float(frame.shape[0] * frame.shape[1])
    best_quad: np.ndarray | None = None
    best_score = -1.0

    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < frame_area * 0.035:
            continue

        rect = cv2.minAreaRect(contour)
        width, height = rect[1]
        if width <= 1 or height <= 1:
            continue
        aspect = max(width, height) / max(1.0, min(width, height))
        if aspect < 1.1 or aspect > 2.3:
            continue

        quad = cv2.boxPoints(rect).astype(np.float32)
        quad_area = float(cv2.contourArea(quad))
        if quad_area <= 1:
            continue
        fill_ratio = area / quad_area
        if fill_ratio < 0.62:
            continue

        mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        cv2.fillConvexPoly(mask, np.round(_shrink_quad(quad, factor=0.92)).astype(np.int32), 255)
        bright_mean = float(cv2.mean(value, mask=mask)[0])
        color_mask = cv2.inRange(hsv, np.array([15, 55, 20]), np.array([170, 255, 255]))
        color_ratio = float(np.mean(color_mask[mask == 255] > 0)) if np.any(mask == 255) else 0.0
        score = quad_area * (0.6 + fill_ratio) + bright_mean * 200.0 + color_ratio * 100000.0
        if score > best_score:
            best_score = score
            best_quad = quad

    return _order_quad(best_quad) if best_quad is not None else None


def _bbox_area(bbox: tuple[int, int, int, int]) -> int:
    x0, y0, x1, y1 = bbox
    return max(0, x1 - x0) * max(0, y1 - y0)


def _corners_bbox(corners: np.ndarray) -> tuple[int, int, int, int]:
    min_xy = np.floor(np.min(corners, axis=0)).astype(int)
    max_xy = np.ceil(np.max(corners, axis=0)).astype(int)
    return (int(min_xy[0]), int(min_xy[1]), int(max_xy[0]), int(max_xy[1]))


def _normalized_bbox(
    frame_shape: tuple[int, ...],
    bbox: tuple[int, int, int, int],
) -> tuple[float, float, float, float]:
    return (
        float(bbox[0]) / float(frame_shape[1]),
        float(bbox[1]) / float(frame_shape[0]),
        float(bbox[2]) / float(frame_shape[1]),
        float(bbox[3]) / float(frame_shape[0]),
    )


def _build_analysis_from_cells(
    frame_shape: tuple[int, ...],
    pattern_size: tuple[int, int],
    cells: list[CellSample],
    bbox: tuple[int, int, int, int],
) -> CalibrationAnalysis | None:
    bright_cells, dark_cells, color_cells = _classify_cells(cells)
    if len(bright_cells) < 4 or len(dark_cells) < 4:
        return None

    white_luma = float(np.mean([cell.luma for cell in bright_cells]))
    black_luma = float(np.mean([cell.luma for cell in dark_cells]))
    clipped_white_fraction = float(np.mean([cell.clip_fraction for cell in bright_cells]))
    shadow_black_fraction = float(np.mean([cell.shadow_fraction for cell in dark_cells]))
    white_balance_cast = _white_balance_cast(bright_cells)
    color_separation = _color_separation(color_cells)
    colorfulness = float(np.mean([cell.saturation for cell in color_cells])) if color_cells else 0.0
    color_clip_fraction_mean = float(np.mean([cell.clip_fraction for cell in color_cells])) if color_cells else 0.0
    color_clip_fraction_max = float(np.max([cell.clip_fraction for cell in color_cells])) if color_cells else 0.0
    neutral_contrast = max(0.0, white_luma - black_luma)
    score = _score_analysis(
        white_luma=white_luma,
        black_luma=black_luma,
        clipped_white_fraction=clipped_white_fraction,
        shadow_black_fraction=shadow_black_fraction,
        white_balance_cast=white_balance_cast,
        neutral_contrast=neutral_contrast,
        color_separation=color_separation,
        colorfulness=colorfulness,
        color_count=len(color_cells),
        reference_color_error_max=0.0,
        color_clip_fraction_mean=color_clip_fraction_mean,
        color_clip_fraction_max=color_clip_fraction_max,
    )

    return CalibrationAnalysis(
        pattern_size=pattern_size,
        score=float(score),
        total_cells=len(cells),
        bright_cell_count=len(bright_cells),
        dark_cell_count=len(dark_cells),
        color_cell_count=len(color_cells),
        white_luma_mean=white_luma,
        black_luma_mean=black_luma,
        neutral_contrast=neutral_contrast,
        clipped_white_fraction=clipped_white_fraction,
        shadow_black_fraction=shadow_black_fraction,
        white_balance_cast=white_balance_cast,
        color_separation=color_separation,
        colorfulness=colorfulness,
        reference_color_error_mean=0.0,
        board_bbox=bbox,
        normalized_board_bbox=_normalized_bbox(frame_shape, bbox),
        neutral_mean_bgr=tuple(
            float(v)
            for v in np.mean(np.array([cell.mean_bgr for cell in bright_cells], dtype=np.float32), axis=0).tolist()
        ),
        tile_samples={},
    )


def _sample_cells(
    frame: np.ndarray,
    corners: np.ndarray,
    pattern_size: tuple[int, int],
) -> list[CellSample]:
    cols, rows = pattern_size
    grid = corners.reshape(rows, cols, 2)
    samples: list[CellSample] = []

    for row in range(rows - 1):
        for col in range(cols - 1):
            quad = np.array(
                [
                    grid[row, col],
                    grid[row, col + 1],
                    grid[row + 1, col + 1],
                    grid[row + 1, col],
                ],
                dtype=np.float32,
            )
            sample = _sample_quad(frame, _shrink_quad(quad, factor=0.58))
            if sample is not None:
                samples.append(sample)

    return samples


def _shrink_quad(quad: np.ndarray, *, factor: float) -> np.ndarray:
    center = np.mean(quad, axis=0)
    return center + (quad - center) * factor


def _sample_quad(frame: np.ndarray, quad: np.ndarray) -> CellSample | None:
    x0 = max(0, int(np.floor(np.min(quad[:, 0]))))
    y0 = max(0, int(np.floor(np.min(quad[:, 1]))))
    x1 = min(frame.shape[1], int(np.ceil(np.max(quad[:, 0]))))
    y1 = min(frame.shape[0], int(np.ceil(np.max(quad[:, 1]))))
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None

    roi = frame[y0:y1, x0:x1]
    if roi.size == 0:
        return None

    mask = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    shifted = np.round(quad - np.array([x0, y0], dtype=np.float32)).astype(np.int32)
    cv2.fillConvexPoly(mask, shifted, 255)
    pixels = roi[mask == 255]
    if pixels.size == 0:
        return None

    pixels_f = pixels.astype(np.float32)
    mean_bgr_arr = np.mean(pixels_f, axis=0)
    mean_bgr = tuple(float(value) for value in mean_bgr_arr.tolist())

    bgr_patch = np.array([[mean_bgr_arr]], dtype=np.uint8)
    mean_lab_arr = cv2.cvtColor(bgr_patch, cv2.COLOR_BGR2LAB)[0, 0].astype(np.float32)
    mean_hsv_arr = cv2.cvtColor(bgr_patch, cv2.COLOR_BGR2HSV)[0, 0].astype(np.float32)

    luma = float(0.114 * mean_bgr_arr[0] + 0.587 * mean_bgr_arr[1] + 0.299 * mean_bgr_arr[2])
    saturation = float(mean_hsv_arr[1])
    clip_fraction = float(np.mean(np.any(pixels >= 250, axis=1)))
    shadow_fraction = float(np.mean(np.all(pixels <= 12, axis=1)))

    return CellSample(
        mean_bgr=mean_bgr,
        mean_lab=(float(mean_lab_arr[0]), float(mean_lab_arr[1]), float(mean_lab_arr[2])),
        mean_hsv=(float(mean_hsv_arr[0]), float(mean_hsv_arr[1]), float(mean_hsv_arr[2])),
        luma=luma,
        saturation=saturation,
        clip_fraction=clip_fraction,
        shadow_fraction=shadow_fraction,
    )


def _classify_cells(cells: list[CellSample]) -> tuple[list[CellSample], list[CellSample], list[CellSample]]:
    neutral_cells = [cell for cell in cells if cell.saturation <= 42.0]
    if len(neutral_cells) < 6:
        neutral_cells = sorted(cells, key=lambda cell: cell.saturation)[: max(6, len(cells) // 2)]

    luma_values = np.array([cell.luma for cell in neutral_cells], dtype=np.float32)
    if len(luma_values) >= 2:
        compactness, labels, centers = cv2.kmeans(
            luma_values.reshape(-1, 1),
            2,
            None,
            (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 15, 0.5),
            3,
            cv2.KMEANS_PP_CENTERS,
        )
        del compactness
        centers = centers.reshape(-1)
        bright_label = int(np.argmax(centers))
        dark_label = int(np.argmin(centers))
        bright_cells = [cell for cell, label in zip(neutral_cells, labels.reshape(-1)) if int(label) == bright_label]
        dark_cells = [cell for cell, label in zip(neutral_cells, labels.reshape(-1)) if int(label) == dark_label]
    else:
        sorted_neutral = sorted(neutral_cells, key=lambda cell: cell.luma)
        split = max(1, len(sorted_neutral) // 2)
        dark_cells = sorted_neutral[:split]
        bright_cells = sorted_neutral[split:]

    color_cells = [
        cell
        for cell in cells
        if cell.saturation >= 52.0 and 25.0 <= cell.luma <= 245.0
    ]

    return bright_cells, dark_cells, color_cells


def _white_balance_cast(cells: list[CellSample]) -> float:
    if not cells:
        return 1.0
    mean_bgr = np.mean(np.array([cell.mean_bgr for cell in cells], dtype=np.float32), axis=0)
    channel_mean = float(np.mean(mean_bgr))
    if channel_mean <= 1e-6:
        return 1.0
    normalized = mean_bgr / channel_mean
    return float(np.std(normalized))


def _color_separation(cells: list[CellSample]) -> float:
    if len(cells) < 2:
        return 0.0
    top_cells = sorted(cells, key=lambda cell: cell.saturation, reverse=True)[:6]
    labs = np.array([cell.mean_lab for cell in top_cells], dtype=np.float32)
    distances: list[float] = []
    for i in range(len(labs)):
        for j in range(i + 1, len(labs)):
            distances.append(float(np.linalg.norm(labs[i] - labs[j])))
    if not distances:
        return 0.0
    return float(np.mean(distances))


def _order_quad(quad: np.ndarray | None) -> np.ndarray | None:
    if quad is None or quad.shape != (4, 2):
        return None
    sums = quad.sum(axis=1)
    diffs = quad[:, 0] - quad[:, 1]
    top_left = quad[np.argmin(sums)]
    bottom_right = quad[np.argmax(sums)]
    top_right = quad[np.argmax(diffs)]
    bottom_left = quad[np.argmin(diffs)]
    return np.array([top_left, top_right, bottom_right, bottom_left], dtype=np.float32)


def _analyze_plate_quad(frame: np.ndarray, quad: np.ndarray) -> CalibrationAnalysis | None:
    quad = _order_quad(quad)
    if quad is None:
        return None

    bbox = _corners_bbox(quad)
    inner_quad = _shrink_quad(quad, factor=0.94)
    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    cv2.fillConvexPoly(mask, np.round(inner_quad).astype(np.int32), 255)
    pixels = frame[mask == 255]
    if pixels.size == 0:
        return None

    pixels_f = pixels.astype(np.float32)
    hsv_pixels = cv2.cvtColor(pixels.reshape(1, -1, 3), cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float32)
    lab_pixels = cv2.cvtColor(pixels.reshape(1, -1, 3), cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
    luma = 0.114 * pixels_f[:, 0] + 0.587 * pixels_f[:, 1] + 0.299 * pixels_f[:, 2]
    saturation = hsv_pixels[:, 1]

    white_mask = (saturation <= 40.0) & (luma >= 150.0)
    color_mask = (saturation >= 55.0) & (luma >= 25.0) & (luma <= 245.0)
    dark_mask = (luma <= 85.0) & (saturation <= 120.0)

    if int(np.count_nonzero(white_mask)) < 200:
        return None

    white_pixels = pixels_f[white_mask]
    white_luma = float(np.mean(luma[white_mask]))
    clipped_white_fraction = float(np.mean(np.any(white_pixels >= 250.0, axis=1)))
    white_mean_bgr = np.mean(white_pixels, axis=0)
    white_balance_cast = float(np.std(white_mean_bgr / max(1.0, float(np.mean(white_mean_bgr)))))

    if int(np.count_nonzero(dark_mask)) >= 40:
        black_luma = float(np.mean(luma[dark_mask]))
        shadow_black_fraction = float(np.mean(np.all(pixels_f[dark_mask] <= 12.0, axis=1)))
    else:
        black_luma = float(np.percentile(luma, 5))
        shadow_black_fraction = float(np.mean(luma <= 12.0))

    color_separation = 0.0
    colorfulness = float(np.mean(saturation[color_mask])) if np.any(color_mask) else 0.0
    color_clip_fraction_mean = float(np.mean(np.any(pixels_f[color_mask] >= 250.0, axis=1))) if np.any(color_mask) else 0.0
    color_clip_fraction_max = color_clip_fraction_mean
    color_count = 0
    if int(np.count_nonzero(color_mask)) >= 120:
        color_lab = lab_pixels[color_mask]
        sample = color_lab
        if len(sample) > 2000:
            indices = np.linspace(0, len(sample) - 1, num=2000, dtype=int)
            sample = sample[indices]
        cluster_count = min(6, max(2, len(sample) // 250))
        if len(sample) >= cluster_count:
            _, labels, centers = cv2.kmeans(
                sample.astype(np.float32),
                cluster_count,
                None,
                (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5),
                3,
                cv2.KMEANS_PP_CENTERS,
            )
            labels = labels.reshape(-1)
            counts = np.bincount(labels, minlength=cluster_count)
            strong_centers = centers[counts >= max(20, len(sample) * 0.06)]
            color_count = int(len(strong_centers))
            if len(strong_centers) >= 2:
                distances: list[float] = []
                for i in range(len(strong_centers)):
                    for j in range(i + 1, len(strong_centers)):
                        distances.append(float(np.linalg.norm(strong_centers[i] - strong_centers[j])))
                color_separation = float(np.mean(distances)) if distances else 0.0

    neutral_contrast = max(0.0, white_luma - black_luma)
    score = _score_analysis(
        white_luma=white_luma,
        black_luma=black_luma,
        clipped_white_fraction=clipped_white_fraction,
        shadow_black_fraction=shadow_black_fraction,
        white_balance_cast=white_balance_cast,
        neutral_contrast=neutral_contrast,
        color_separation=color_separation,
        colorfulness=colorfulness,
        color_count=color_count,
        reference_color_error_max=0.0,
        color_clip_fraction_mean=color_clip_fraction_mean,
        color_clip_fraction_max=color_clip_fraction_max,
    )

    return CalibrationAnalysis(
        pattern_size=(4, 6),
        score=float(score),
        total_cells=int(len(pixels)),
        bright_cell_count=int(np.count_nonzero(white_mask)),
        dark_cell_count=int(np.count_nonzero(dark_mask)),
        color_cell_count=color_count,
        white_luma_mean=white_luma,
        black_luma_mean=black_luma,
        neutral_contrast=neutral_contrast,
        clipped_white_fraction=clipped_white_fraction,
        shadow_black_fraction=shadow_black_fraction,
        white_balance_cast=white_balance_cast,
        color_separation=color_separation,
        colorfulness=colorfulness,
        reference_color_error_mean=0.0,
        board_bbox=bbox,
        normalized_board_bbox=_normalized_bbox(frame.shape, bbox),
        neutral_mean_bgr=tuple(float(v) for v in np.mean(white_pixels, axis=0).tolist()),
        tile_samples={},
    )


def _score_analysis(
    *,
    white_luma: float,
    black_luma: float,
    clipped_white_fraction: float,
    shadow_black_fraction: float,
    white_balance_cast: float,
    neutral_contrast: float,
    color_separation: float,
    colorfulness: float,
    color_count: int,
    reference_color_error_mean: float = 0.0,
    reference_color_error_max: float = 0.0,
    color_clip_fraction_mean: float = 0.0,
    color_clip_fraction_max: float = 0.0,
) -> float:
    white_target = 224.0
    black_target = 38.0
    score = 100.0
    score -= abs(white_luma - white_target) * 1.9
    score -= abs(black_luma - black_target) * 1.1
    score -= clipped_white_fraction * 260.0
    score -= shadow_black_fraction * 40.0
    score -= white_balance_cast * 230.0
    score -= color_clip_fraction_mean * 100.0
    score -= color_clip_fraction_max * 60.0
    score += min(max(neutral_contrast - 110.0, 0.0), 80.0) * 0.35
    score += min(color_separation, 90.0) * 0.16
    score += min(colorfulness, 180.0) * 0.03
    score -= max(colorfulness - 210.0, 0.0) * 0.08
    score += min(float(color_count), 8.0) * 1.5
    score -= min(reference_color_error_mean, 80.0) * 1.0
    score -= min(reference_color_error_max, 80.0) * 0.45
    return float(score)
