"""Shared helpers for ML detection processors (ONNX/NCNN/Hailo).

The YOLO and NanoDet decode paths are ported from
``software/training/src/training/reports/benchmark.py``. Keep the two in sync
when either changes — the benchmark bundle is the cross-device reference.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


NANODET_MEAN = np.array([103.53, 116.28, 123.675], dtype=np.float32)
NANODET_STD = np.array([57.375, 57.12, 58.395], dtype=np.float32)


@dataclass(frozen=True)
class Detection:
    bbox: tuple[int, int, int, int]
    score: float


def letterbox(image: np.ndarray, size: int) -> tuple[np.ndarray, float, float, float]:
    height, width = image.shape[:2]
    scale = min(float(size) / float(height), float(size) / float(width))
    resized_w = int(round(width * scale))
    resized_h = int(round(height * scale))
    resized = cv2.resize(image, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    pad_x = (size - resized_w) / 2.0
    pad_y = (size - resized_h) / 2.0
    left = int(round(pad_x - 0.1))
    top = int(round(pad_y - 0.1))
    canvas[top : top + resized_h, left : left + resized_w] = resized
    return canvas, scale, float(left), float(top)


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    if boxes.size == 0:
        return []
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        index = int(order[0])
        keep.append(index)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(boxes[index, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[index, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[index, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[index, 3], boxes[rest, 3])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        area_index = max(0.0, boxes[index, 2] - boxes[index, 0]) * max(0.0, boxes[index, 3] - boxes[index, 1])
        area_rest = np.maximum(0.0, boxes[rest, 2] - boxes[rest, 0]) * np.maximum(0.0, boxes[rest, 3] - boxes[rest, 1])
        union = area_index + area_rest - inter
        ious = np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)
        order = rest[ious <= iou_threshold]
    return keep


class BaseProcessor:
    """Shared lifecycle hooks + common config for all runtime processors."""

    family: str = "base"
    runtime: str = "base"

    def __init__(
        self,
        model_path: Path,
        *,
        imgsz: int,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
    ) -> None:
        self.model_path = Path(model_path)
        self.imgsz = int(imgsz)
        self.conf_threshold = float(conf_threshold)
        self.iou_threshold = float(iou_threshold)
        self._lock = threading.Lock()

    def infer(
        self,
        image_bgr: np.ndarray,
        *,
        conf_threshold: float | None = None,
    ) -> list[Detection]:  # pragma: no cover - abstract
        raise NotImplementedError


def decode_yolo(
    output: np.ndarray,
    *,
    pre: dict[str, float],
    conf_threshold: float,
    iou_threshold: float,
) -> list[Detection]:
    preds = np.asarray(output)
    if preds.ndim == 3:
        preds = preds[0]
    if preds.ndim != 2:
        raise RuntimeError(f"Unexpected YOLO output rank: {preds.shape}")
    if preds.shape[0] <= 16 and preds.shape[1] > preds.shape[0]:
        preds = preds.T
    if preds.shape[1] < 5:
        raise RuntimeError(f"Unexpected YOLO output shape: {preds.shape}")

    raw_boxes = preds[:, :4].astype(np.float32)
    raw_scores = preds[:, 4:].astype(np.float32)
    scores = raw_scores.max(axis=1)
    keep_mask = scores >= conf_threshold
    if not np.any(keep_mask):
        return []
    raw_boxes = raw_boxes[keep_mask]
    scores = scores[keep_mask]

    x_center, y_center = raw_boxes[:, 0], raw_boxes[:, 1]
    widths, heights = raw_boxes[:, 2], raw_boxes[:, 3]
    x1 = (x_center - widths / 2.0 - pre["pad_x"]) / pre["scale"]
    y1 = (y_center - heights / 2.0 - pre["pad_y"]) / pre["scale"]
    x2 = (x_center + widths / 2.0 - pre["pad_x"]) / pre["scale"]
    y2 = (y_center + heights / 2.0 - pre["pad_y"]) / pre["scale"]

    w, h = pre["original_w"], pre["original_h"]
    x1 = np.clip(x1, 0.0, w)
    y1 = np.clip(y1, 0.0, h)
    x2 = np.clip(x2, 0.0, w)
    y2 = np.clip(y2, 0.0, h)
    valid = (x2 > x1) & (y2 > y1)
    if not np.any(valid):
        return []
    boxes = np.stack([x1[valid], y1[valid], x2[valid], y2[valid]], axis=1)
    scores = scores[valid]

    kept = nms(boxes, scores, iou_threshold)
    return [
        Detection(
            bbox=(
                int(round(boxes[i, 0])),
                int(round(boxes[i, 1])),
                int(round(boxes[i, 2])),
                int(round(boxes[i, 3])),
            ),
            score=float(scores[i]),
        )
        for i in kept
    ]


def decode_yolo_head_stripped(
    outputs: list,
    *,
    pre: dict[str, float],
    imgsz: int,
    conf_threshold: float,
    iou_threshold: float,
    reg_max: int = 16,
) -> list[Detection]:
    """Decode head-stripped YOLO outputs: list of [1, 4*reg_max+nc, H, W] per scale.

    Each tensor contains concatenated cv2 (box, 4*reg_max channels) + cv3 (cls, nc channels)
    outputs before DFL decode / sigmoid / anchor math. Strides are inferred from imgsz / H.
    """
    proj = np.arange(reg_max, dtype=np.float32)
    n_box_ch = 4 * reg_max
    all_boxes: list[np.ndarray] = []
    all_scores: list[np.ndarray] = []

    for feat in outputs:
        arr = np.asarray(feat, dtype=np.float32)
        if arr.ndim == 4:
            arr = arr[0]  # [C, H, W]
        if arr.ndim != 3:
            continue
        C, H, W = arr.shape
        n_cls = C - n_box_ch
        if n_cls <= 0:
            continue

        stride = imgsz / H
        # anchor grid in feature-map coords (col+0.5, row+0.5)
        ys, xs = np.meshgrid(np.arange(H, dtype=np.float32), np.arange(W, dtype=np.float32), indexing="ij")
        anchor_x = xs.ravel() + 0.5  # [H*W]
        anchor_y = ys.ravel() + 0.5

        # box: [n_box_ch, H*W] → [H*W, 4, reg_max]
        box_raw = arr[:n_box_ch].reshape(n_box_ch, H * W).T.reshape(H * W, 4, reg_max)
        # numerically-stable softmax over reg_max dim
        box_raw -= box_raw.max(axis=-1, keepdims=True)
        box_exp = np.exp(box_raw)
        box_dist = box_exp / box_exp.sum(axis=-1, keepdims=True)
        # DFL: expected value of distribution → [H*W, 4] (l, t, r, b in feat-px)
        box_ltrb = (box_dist * proj).sum(axis=-1)

        # cls: sigmoid → [H*W, n_cls]
        cls_raw = arr[n_box_ch:].reshape(n_cls, H * W).T
        cls_scores = 1.0 / (1.0 + np.exp(-cls_raw))
        scores = cls_scores.max(axis=1)

        keep = scores >= conf_threshold
        if not np.any(keep):
            continue

        ltrb = box_ltrb[keep]
        sc = scores[keep]
        ax = anchor_x[keep]
        ay = anchor_y[keep]

        # xyxy in feature-map px → input-image px → original-image px
        x1 = (ax - ltrb[:, 0]) * stride
        y1 = (ay - ltrb[:, 1]) * stride
        x2 = (ax + ltrb[:, 2]) * stride
        y2 = (ay + ltrb[:, 3]) * stride
        x1 = (x1 - pre["pad_x"]) / pre["scale"]
        y1 = (y1 - pre["pad_y"]) / pre["scale"]
        x2 = (x2 - pre["pad_x"]) / pre["scale"]
        y2 = (y2 - pre["pad_y"]) / pre["scale"]

        all_boxes.append(np.stack([x1, y1, x2, y2], axis=1))
        all_scores.append(sc)

    if not all_boxes:
        return []

    boxes = np.concatenate(all_boxes, axis=0)
    scores = np.concatenate(all_scores, axis=0)

    w, h = pre["original_w"], pre["original_h"]
    boxes[:, 0] = np.clip(boxes[:, 0], 0.0, w)
    boxes[:, 1] = np.clip(boxes[:, 1], 0.0, h)
    boxes[:, 2] = np.clip(boxes[:, 2], 0.0, w)
    boxes[:, 3] = np.clip(boxes[:, 3], 0.0, h)
    valid = (boxes[:, 2] > boxes[:, 0]) & (boxes[:, 3] > boxes[:, 1])
    if not np.any(valid):
        return []
    boxes = boxes[valid]
    scores = scores[valid]

    kept = nms(boxes, scores, iou_threshold)
    return [
        Detection(
            bbox=(
                int(round(boxes[i, 0])),
                int(round(boxes[i, 1])),
                int(round(boxes[i, 2])),
                int(round(boxes[i, 3])),
            ),
            score=float(scores[i]),
        )
        for i in kept
    ]


def decode_nanodet(
    output: np.ndarray,
    *,
    pre: dict[str, float],
    imgsz: int,
    reg_max: int,
    strides: tuple[int, ...],
    conf_threshold: float,
    iou_threshold: float,
) -> list[Detection]:
    preds = np.asarray(output)
    if preds.ndim == 3:
        preds = preds[0]
    if preds.ndim != 2:
        raise RuntimeError(f"Unexpected NanoDet output rank: {preds.shape}")
    if preds.shape[0] <= 64 and preds.shape[1] > preds.shape[0]:
        preds = preds.T

    num_reg = 4 * (reg_max + 1)
    num_classes = preds.shape[1] - num_reg
    if num_classes <= 0:
        raise RuntimeError(f"Unexpected NanoDet channel count: {preds.shape}")
    cls_scores = preds[:, :num_classes]
    bbox_preds = preds[:, num_classes:]
    if cls_scores.max() > 1.0 or cls_scores.min() < 0.0:
        cls_scores = 1.0 / (1.0 + np.exp(-cls_scores))

    anchor_points: list[tuple[float, float, int]] = []
    for stride in strides:
        grid_h = imgsz // stride
        grid_w = imgsz // stride
        for y in range(grid_h):
            for x in range(grid_w):
                anchor_points.append((x * stride, y * stride, stride))

    w, h = pre["original_w"], pre["original_h"]
    scale_x = float(w) / float(imgsz)
    scale_y = float(h) / float(imgsz)
    all_boxes: list[list[float]] = []
    all_scores: list[float] = []
    for index in range(min(len(anchor_points), preds.shape[0])):
        score = float(np.max(cls_scores[index]))
        if score < conf_threshold:
            continue
        cx, cy, stride = anchor_points[index]
        reg = bbox_preds[index].reshape(4, reg_max + 1)
        distances = []
        for side in range(4):
            side_vals = reg[side]
            exp_vals = np.exp(side_vals - np.max(side_vals))
            probs = exp_vals / np.sum(exp_vals)
            dist = float(np.sum(np.arange(reg_max + 1, dtype=np.float32) * probs))
            distances.append(dist * stride)
        x1 = max(0.0, min(float(w), (cx - distances[0]) * scale_x))
        y1 = max(0.0, min(float(h), (cy - distances[1]) * scale_y))
        x2 = max(0.0, min(float(w), (cx + distances[2]) * scale_x))
        y2 = max(0.0, min(float(h), (cy + distances[3]) * scale_y))
        if x2 <= x1 or y2 <= y1:
            continue
        all_boxes.append([x1, y1, x2, y2])
        all_scores.append(score)

    if not all_boxes:
        return []
    boxes_np = np.asarray(all_boxes, dtype=np.float32)
    scores_np = np.asarray(all_scores, dtype=np.float32)
    kept = nms(boxes_np, scores_np, iou_threshold)
    return [
        Detection(
            bbox=(
                int(round(boxes_np[i, 0])),
                int(round(boxes_np[i, 1])),
                int(round(boxes_np[i, 2])),
                int(round(boxes_np[i, 3])),
            ),
            score=float(scores_np[i]),
        )
        for i in kept
    ]


def preprocess_yolo(image: np.ndarray, imgsz: int) -> tuple[np.ndarray, dict[str, float]]:
    letterboxed, scale, pad_x, pad_y = letterbox(image, imgsz)
    rgb = cv2.cvtColor(letterboxed, cv2.COLOR_BGR2RGB)
    blob = np.transpose(rgb.astype(np.float32) / 255.0, (2, 0, 1))[None, ...]
    return blob.astype(np.float32), {
        "scale": scale,
        "pad_x": pad_x,
        "pad_y": pad_y,
        "original_w": float(image.shape[1]),
        "original_h": float(image.shape[0]),
    }


def preprocess_nanodet(image: np.ndarray, imgsz: int) -> tuple[np.ndarray, dict[str, float]]:
    resized = cv2.resize(image, (imgsz, imgsz), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    normalized = (resized - NANODET_MEAN) / NANODET_STD
    blob = np.transpose(normalized, (2, 0, 1))[None, ...].astype(np.float32)
    return blob, {
        "original_w": float(image.shape[1]),
        "original_h": float(image.shape[0]),
    }
