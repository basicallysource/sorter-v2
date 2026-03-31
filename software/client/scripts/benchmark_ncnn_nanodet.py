from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
from pathlib import Path
from typing import Any

import cv2
import ncnn
import numpy as np


MEAN = np.array([103.53, 116.28, 123.675], dtype=np.float32)
STD = np.array([57.375, 57.12, 58.395], dtype=np.float32)
NORM = np.array([1.0 / 57.375, 1.0 / 57.12, 1.0 / 58.395], dtype=np.float32)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark a NanoDet NCNN model on a manifest of chamber images.")
    parser.add_argument("--manifest", required=True, help="Path to manifest.json")
    parser.add_argument("--image-dir", required=True, help="Directory holding the benchmark images")
    parser.add_argument("--param", required=True, help="Path to .ncnn.param")
    parser.add_argument("--bin", required=True, help="Path to .ncnn.bin")
    parser.add_argument("--output", required=True, help="Where to write benchmark_result.json")
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--iou", type=float, default=0.45)
    parser.add_argument("--threads", type=int, default=max(1, os.cpu_count() or 1))
    parser.add_argument("--warmup", type=int, default=3)
    return parser.parse_args()


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text())
    samples = payload.get("samples")
    if not isinstance(samples, list):
        raise RuntimeError(f"Manifest is missing samples list: {path}")
    return [sample for sample in samples if isinstance(sample, dict)]


def _normalize_box(box: list[int], width: int, height: int) -> list[float]:
    return [
        max(0.0, min(1.0, box[0] / width)),
        max(0.0, min(1.0, box[1] / height)),
        max(0.0, min(1.0, box[2] / width)),
        max(0.0, min(1.0, box[3] / height)),
    ]


def _iou(box_a: list[float], box_b: list[float]) -> float:
    x_min = max(box_a[0], box_b[0])
    y_min = max(box_a[1], box_b[1])
    x_max = min(box_a[2], box_b[2])
    y_max = min(box_a[3], box_b[3])
    inter_w = max(0.0, x_max - x_min)
    inter_h = max(0.0, y_max - y_min)
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    area_a = max(0.0, box_a[2] - box_a[0]) * max(0.0, box_a[3] - box_a[1])
    area_b = max(0.0, box_b[2] - box_b[0]) * max(0.0, box_b[3] - box_b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    if boxes.size == 0:
        return []
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(boxes[i, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[i, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[i, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        area_i = max(0.0, boxes[i, 2] - boxes[i, 0]) * max(0.0, boxes[i, 3] - boxes[i, 1])
        area_rest = np.maximum(0.0, boxes[rest, 2] - boxes[rest, 0]) * np.maximum(0.0, boxes[rest, 3] - boxes[rest, 1])
        union = area_i + area_rest - inter
        ious = np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)
        order = rest[ious <= iou_threshold]
    return keep


def _decode_nanodet_output(
    output: np.ndarray,
    *,
    imgsz: int,
    original_h: int,
    original_w: int,
    reg_max: int = 7,
    strides: list[int] | None = None,
    conf_threshold: float = 0.25,
    iou_threshold: float = 0.45,
) -> tuple[list[list[int]], list[float]]:
    if strides is None:
        strides = [8, 16, 32, 64]

    anchor_points: list[tuple[float, float, int]] = []
    for stride in strides:
        grid_h = imgsz // stride
        grid_w = imgsz // stride
        for y in range(grid_h):
            for x in range(grid_w):
                anchor_points.append((x * stride, y * stride, stride))

    preds = output
    num_reg = 4 * (reg_max + 1)
    num_classes = preds.shape[1] - num_reg
    cls_scores = preds[:, :num_classes]
    bbox_preds = preds[:, num_classes:]

    if cls_scores.max() > 1.0 or cls_scores.min() < 0.0:
        cls_scores = 1.0 / (1.0 + np.exp(-cls_scores))

    all_boxes: list[list[float]] = []
    all_scores: list[float] = []

    for idx in range(min(len(anchor_points), preds.shape[0])):
        score = float(np.max(cls_scores[idx]))
        if score < conf_threshold:
            continue

        cx, cy, stride = anchor_points[idx]
        reg = bbox_preds[idx].reshape(4, reg_max + 1)
        distances = []
        for side in range(4):
            side_vals = reg[side]
            exp_vals = np.exp(side_vals - np.max(side_vals))
            probs = exp_vals / np.sum(exp_vals)
            dist = sum(j * probs[j] for j in range(reg_max + 1))
            distances.append(dist * stride)

        x1 = cx - distances[0]
        y1 = cy - distances[1]
        x2 = cx + distances[2]
        y2 = cy + distances[3]

        scale_x = original_w / imgsz
        scale_y = original_h / imgsz
        x1 = max(0, min(original_w, x1 * scale_x))
        y1 = max(0, min(original_h, y1 * scale_y))
        x2 = max(0, min(original_w, x2 * scale_x))
        y2 = max(0, min(original_h, y2 * scale_y))

        if x2 > x1 and y2 > y1:
            all_boxes.append([x1, y1, x2, y2])
            all_scores.append(score)

    if not all_boxes:
        return [], []

    boxes_np = np.array(all_boxes)
    scores_np = np.array(all_scores)
    kept = _nms(boxes_np, scores_np, iou_threshold)
    result_boxes = [[int(round(v)) for v in all_boxes[i]] for i in kept]
    result_scores = [float(all_scores[i]) for i in kept]
    return result_boxes, result_scores


def _prepare_input(image: np.ndarray, imgsz: int) -> ncnn.Mat:
    height, width = image.shape[:2]
    mat = ncnn.Mat.from_pixels_resize(
        image,
        ncnn.Mat.PixelType.PIXEL_BGR,
        width,
        height,
        imgsz,
        imgsz,
    )
    mat.substract_mean_normalize(MEAN.tolist(), NORM.tolist())
    return mat


def _decision(count: int) -> str:
    if count <= 0:
        return "empty"
    if count == 1:
        return "single"
    return "multi"


def main() -> int:
    args = _parse_args()
    manifest_path = Path(args.manifest).resolve()
    image_dir = Path(args.image_dir).resolve()
    param_path = Path(args.param).resolve()
    bin_path = Path(args.bin).resolve()
    output_path = Path(args.output).resolve()

    samples = _load_manifest(manifest_path)

    net = ncnn.Net()
    net.opt.use_vulkan_compute = False
    net.opt.num_threads = args.threads
    net.load_param(str(param_path))
    net.load_model(str(bin_path))

    # Warm the model on the first sample a few times to reduce first-run noise.
    if samples:
        warm_image = cv2.imread(str(image_dir / samples[0]["image"]), cv2.IMREAD_COLOR)
        if warm_image is not None:
            warm_blob = _prepare_input(warm_image, args.imgsz)
            for _ in range(max(0, args.warmup)):
                with net.create_extractor() as ex:
                    ex.input("in0", warm_blob)
                    ex.extract("out0")

    total = 0
    exact_count = 0
    decision_match = 0
    single_ious: list[float] = []
    multi_samples = 0
    multi_detect = 0
    latencies_ms: list[float] = []
    per_sample: list[dict[str, Any]] = []

    for sample in samples:
        image_path = image_dir / sample["image"]
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            per_sample.append({
                "image": sample["image"],
                "ok": False,
                "error": "could_not_read_image",
            })
            continue

        original_h, original_w = image.shape[:2]
        blob = _prepare_input(image, args.imgsz)

        with net.create_extractor() as ex:
            ex.input("in0", blob)
            start = time.perf_counter()
            _, out0 = ex.extract("out0")
            latency_ms = (time.perf_counter() - start) * 1000.0

        output = np.array(out0)
        if output.ndim == 3:
            output = output[0]

        pred_boxes, pred_scores = _decode_nanodet_output(
            output,
            imgsz=args.imgsz,
            original_h=original_h,
            original_w=original_w,
            conf_threshold=args.conf,
            iou_threshold=args.iou,
        )

        pred_boxes_normalized = [_normalize_box(box, original_w, original_h) for box in pred_boxes]
        gt_boxes = sample.get("gt_boxes_normalized") if isinstance(sample.get("gt_boxes_normalized"), list) else []
        gt_count = int(sample.get("detection_count", len(gt_boxes)))
        pred_count = len(pred_boxes)

        total += 1
        latencies_ms.append(latency_ms)
        if pred_count == gt_count:
            exact_count += 1
        if _decision(pred_count) == _decision(gt_count):
            decision_match += 1
        if gt_count > 1:
            multi_samples += 1
            if pred_count > 1:
                multi_detect += 1
        if gt_count == 1 and pred_count == 1 and gt_boxes:
            single_ious.append(_iou(pred_boxes_normalized[0], [float(v) for v in gt_boxes[0]]))

        per_sample.append({
            "image": sample["image"],
            "ok": True,
            "latency_ms": round(latency_ms, 3),
            "fps": round(1000.0 / latency_ms, 2) if latency_ms > 0 else None,
            "gt_count": gt_count,
            "pred_count": pred_count,
            "gt_decision": _decision(gt_count),
            "pred_decision": _decision(pred_count),
            "scores": [round(score, 5) for score in pred_scores],
            "candidate_bboxes": pred_boxes,
            "candidate_bboxes_normalized": pred_boxes_normalized,
        })

    summary = {
        "model_family": "nanodet",
        "runtime": "ncnn",
        "imgsz": args.imgsz,
        "conf": args.conf,
        "iou": args.iou,
        "threads": args.threads,
        "sample_count": total,
        "avg_latency_ms": round(float(sum(latencies_ms) / total), 3) if total else None,
        "median_latency_ms": round(float(statistics.median(latencies_ms)), 3) if latencies_ms else None,
        "p95_latency_ms": round(float(np.percentile(np.asarray(latencies_ms, dtype=np.float32), 95)), 3) if latencies_ms else None,
        "avg_fps": round(float(1000.0 / (sum(latencies_ms) / total)), 2) if total and sum(latencies_ms) > 0 else None,
        "exact_count_match_rate": round(exact_count / total, 5) if total else None,
        "decision_match_rate": round(decision_match / total, 5) if total else None,
        "single_mean_iou": round(float(sum(single_ious) / len(single_ious)), 5) if single_ious else None,
        "multi_detect_rate": round(multi_detect / multi_samples, 5) if multi_samples else None,
    }
    payload = {
        "created_at": time.time(),
        "system": {
            "hostname": os.uname().nodename,
            "machine": os.uname().machine,
            "sysname": os.uname().sysname,
            "release": os.uname().release,
            "cpu_count": os.cpu_count(),
        },
        "summary": summary,
        "per_sample": per_sample,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
