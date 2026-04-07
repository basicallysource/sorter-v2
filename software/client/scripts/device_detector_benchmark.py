from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from html import escape
from pathlib import Path
from typing import Any

import cv2
import numpy as np


CLIENT_ROOT = Path(__file__).resolve().parents[1]
BLOB_DIR = CLIENT_ROOT / "blob"
CLASSIFICATION_ROOT = BLOB_DIR / "classification_training"
DEFAULT_SAMPLE_IDS_JSON = BLOB_DIR / "benchmark_reports" / "benchmark-1774996075" / "benchmark_data.json"

PRESETS: dict[str, dict[str, Any]] = {
    "chamber_zone_pair": {
        "label": "Classification chamber zone pair",
        "description": "Imported chamber-zone YOLO11s and NanoDet exports on the 50-sample benchmark set.",
        "model_runs": [
            "blob/local_detection_models/20260331-zone-classification_chamber-yolo11s/run.json",
            "blob/local_detection_models/20260331-zone-classification_chamber-nanodet/run.json",
        ],
        "sample_ids_json": "blob/benchmark_reports/benchmark-1774996075/benchmark_data.json",
    },
    "chamber_pair": {
        "label": "Classification chamber local pair",
        "description": "Locally trained chamber YOLO11n and NanoDet exports on the 50-sample benchmark set.",
        "model_runs": [
            "blob/local_detection_models/20260331-234738-chamber-yolo11n-320/run.json",
            "blob/local_detection_models/20260331-234738-chamber-nanodet-1-5x-416/run.json",
        ],
        "sample_ids_json": "blob/benchmark_reports/benchmark-1774996075/benchmark_data.json",
        "split_source_run": "blob/local_detection_models/20260331-234738-chamber-yolo11n-320/run.json",
    },
}

NANODET_MEAN = np.array([103.53, 116.28, 123.675], dtype=np.float32)
NANODET_STD = np.array([57.375, 57.12, 58.395], dtype=np.float32)
HAILO_TIMEOUT_MS = 10_000


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object in {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _slugify(value: str) -> str:
    cleaned = []
    previous_dash = False
    for char in value.lower():
        if char.isalnum():
            cleaned.append(char)
            previous_dash = False
            continue
        if not previous_dash:
            cleaned.append("-")
            previous_dash = True
    result = "".join(cleaned).strip("-")
    return result or "item"


def _decision(count: int) -> str:
    if count <= 0:
        return "empty"
    if count == 1:
        return "single"
    return "multi"


def _normalize_box(box: list[int], width: int, height: int) -> list[float]:
    return [
        max(0.0, min(1.0, float(box[0]) / float(width))),
        max(0.0, min(1.0, float(box[1]) / float(height))),
        max(0.0, min(1.0, float(box[2]) / float(width))),
        max(0.0, min(1.0, float(box[3]) / float(height))),
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


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=np.float32), percentile))


def _cpu_model() -> str | None:
    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                check=True,
            )
            value = result.stdout.strip()
            return value or None
        cpuinfo = Path("/proc/cpuinfo")
        if cpuinfo.exists():
            for line in cpuinfo.read_text().splitlines():
                if ":" not in line:
                    continue
                key, value = [part.strip() for part in line.split(":", 1)]
                if key in {"model name", "Hardware", "Processor"} and value:
                    return value
    except Exception:
        return None
    return platform.processor() or None


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _find_metadata_path(sample_id: str) -> Path:
    matches = sorted(CLASSIFICATION_ROOT.glob(f"*/metadata/{sample_id}.json"))
    if not matches:
        raise FileNotFoundError(f"Could not resolve metadata for sample {sample_id}")
    return matches[0]


def _extract_review_boxes(metadata: dict[str, Any]) -> list[list[int]] | None:
    review = metadata.get("review")
    if not isinstance(review, dict):
        return None
    status = str(review.get("status") or "")
    if status not in {"accepted", "confirmed"}:
        return None
    corrections = review.get("box_corrections")
    if not isinstance(corrections, list):
        return None
    boxes: list[list[int]] = []
    for correction in corrections:
        if not isinstance(correction, dict):
            continue
        correction_status = str(correction.get("status") or "")
        if correction_status in {"removed", "rejected", "deleted"}:
            continue
        bbox = correction.get("bbox")
        if isinstance(bbox, list) and len(bbox) >= 4:
            boxes.append([int(round(float(value))) for value in bbox[:4]])
    return boxes if boxes else None


def _extract_gt_boxes(metadata: dict[str, Any], distill_payload: dict[str, Any]) -> list[list[int]]:
    review_boxes = _extract_review_boxes(metadata)
    if review_boxes is not None:
        return review_boxes
    detections = distill_payload.get("detections")
    if not isinstance(detections, list):
        return []
    boxes: list[list[int]] = []
    for detection in detections:
        if not isinstance(detection, dict):
            continue
        bbox = detection.get("bbox")
        if isinstance(bbox, list) and len(bbox) >= 4:
            boxes.append([int(round(float(value))) for value in bbox[:4]])
    return boxes


def _build_sample_entry(sample_id: str, image_dir: Path) -> dict[str, Any]:
    metadata_path = _find_metadata_path(sample_id)
    metadata = _read_json(metadata_path)
    image_path_value = metadata.get("input_image")
    if not isinstance(image_path_value, str) or not image_path_value:
        raise RuntimeError(f"Sample {sample_id} is missing input_image in {metadata_path}")
    image_path = Path(image_path_value)
    if not image_path.exists():
        raise FileNotFoundError(f"Image missing for sample {sample_id}: {image_path}")

    distill = metadata.get("distill_result")
    if not isinstance(distill, dict):
        raise RuntimeError(f"Sample {sample_id} is missing distill_result in {metadata_path}")
    result_json_value = distill.get("result_json")
    if not isinstance(result_json_value, str) or not result_json_value:
        raise RuntimeError(f"Sample {sample_id} is missing distill_result.result_json in {metadata_path}")
    distill_path = Path(result_json_value)
    if not distill_path.exists():
        raise FileNotFoundError(f"Distill JSON missing for sample {sample_id}: {distill_path}")
    distill_payload = _read_json(distill_path)

    gt_boxes = _extract_gt_boxes(metadata, distill_payload)
    width = int(distill_payload.get("width") or 0)
    height = int(distill_payload.get("height") or 0)
    if width <= 0 or height <= 0:
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"Could not read image for {sample_id}: {image_path}")
        height, width = image.shape[:2]

    image_dir.mkdir(parents=True, exist_ok=True)
    dest_name = f"{sample_id}{image_path.suffix or '.jpg'}"
    shutil.copy2(image_path, image_dir / dest_name)

    return {
        "sample_id": sample_id,
        "image": dest_name,
        "session_id": metadata.get("session_id"),
        "source_role": metadata.get("source_role"),
        "width": width,
        "height": height,
        "gt_boxes": gt_boxes,
        "gt_boxes_normalized": [_normalize_box(box, width, height) for box in gt_boxes],
        "detection_count": len(gt_boxes),
        "decision": _decision(len(gt_boxes)),
        "metadata_review_status": metadata.get("review", {}).get("status") if isinstance(metadata.get("review"), dict) else None,
    }


def _resolve_preset(name: str) -> dict[str, Any]:
    preset = PRESETS.get(name)
    if preset is None:
        raise RuntimeError(f"Unknown preset: {name}")
    return preset


def _path_from_client_root(relative_path: str) -> Path:
    return (CLIENT_ROOT / relative_path).resolve()


def _resolve_run_json_paths(args: argparse.Namespace) -> list[Path]:
    if args.preset and args.model_run:
        raise RuntimeError("Use either --preset or --model-run, not both.")
    if args.model_run:
        return [Path(value).resolve() for value in args.model_run]
    if args.preset:
        preset = _resolve_preset(args.preset)
        return [_path_from_client_root(path) for path in preset.get("model_runs", [])]
    raise RuntimeError("Please provide --preset or at least one --model-run.")


def _resolve_manifest_jsonl(run_json_path: Path, run_payload: dict[str, Any]) -> Path | None:
    dataset = run_payload.get("dataset")
    if isinstance(dataset, dict):
        manifest_value = dataset.get("manifest_path")
        if isinstance(manifest_value, str) and manifest_value:
            manifest_path = Path(manifest_value)
            if manifest_path.exists():
                return manifest_path
    sibling = run_json_path.parent / "manifest.jsonl"
    return sibling if sibling.exists() else None


def _load_sample_ids_from_json(path: Path) -> list[str]:
    payload = json.loads(path.read_text())
    if isinstance(payload, dict):
        values = payload.get("samples")
    else:
        values = payload
    if not isinstance(values, list):
        raise RuntimeError(f"Expected a list or {{'samples': [...]}} in {path}")
    sample_ids = [str(value) for value in values if str(value).strip()]
    if not sample_ids:
        raise RuntimeError(f"No sample IDs found in {path}")
    return sample_ids


def _load_sample_ids_from_split(run_json_path: Path, split: str) -> list[str]:
    run_payload = _read_json(run_json_path)
    manifest_path = _resolve_manifest_jsonl(run_json_path, run_payload)
    if manifest_path is None:
        raise RuntimeError(f"Run {run_json_path} does not expose manifest.jsonl for split selection.")
    sample_ids: list[str] = []
    for row in _iter_jsonl(manifest_path):
        if str(row.get("split") or "") != split:
            continue
        sample_id = row.get("sample_id")
        if isinstance(sample_id, str) and sample_id:
            sample_ids.append(sample_id)
    if not sample_ids:
        raise RuntimeError(f"No samples found for split '{split}' in {manifest_path}")
    return sample_ids


def _resolve_sample_ids(args: argparse.Namespace, run_json_paths: list[Path]) -> tuple[list[str], str]:
    if args.sample_ids_json:
        path = Path(args.sample_ids_json).resolve()
        return _load_sample_ids_from_json(path), str(path)
    if args.split:
        return _load_sample_ids_from_split(run_json_paths[0], args.split), f"{run_json_paths[0]}::{args.split}"
    if args.preset:
        preset = _resolve_preset(args.preset)
        sample_ids_json = preset.get("sample_ids_json")
        if isinstance(sample_ids_json, str):
            path = _path_from_client_root(sample_ids_json)
            return _load_sample_ids_from_json(path), str(path)
        split_source_run = preset.get("split_source_run")
        if isinstance(split_source_run, str):
            run_json_path = _path_from_client_root(split_source_run)
            return _load_sample_ids_from_split(run_json_path, "test"), f"{run_json_path}::test"
    return _load_sample_ids_from_json(DEFAULT_SAMPLE_IDS_JSON), str(DEFAULT_SAMPLE_IDS_JSON.resolve())


def _resolve_onnx_path(run_json_path: Path, run_payload: dict[str, Any]) -> Path | None:
    training = run_payload.get("training")
    if isinstance(training, dict):
        value = training.get("onnx_model") or training.get("onnx_path")
        if isinstance(value, str) and value:
            path = Path(value)
            if not path.is_absolute():
                path = (run_json_path.parent / value).resolve()
            if path.exists():
                return path
        onnx_export = training.get("onnx_export")
        if isinstance(onnx_export, dict):
            for key in ("final_onnx", "simplified_path", "onnx_path"):
                value = onnx_export.get(key)
                if isinstance(value, str) and value:
                    path = Path(value)
                    if not path.is_absolute():
                        path = (run_json_path.parent / value).resolve()
                    if path.exists():
                        return path
    for candidate in (
        run_json_path.parent / "exports" / "best.onnx",
        run_json_path.parent / "exports" / "model.onnx",
        run_json_path.parent / "exports" / "best-sim.onnx",
    ):
        if candidate.exists():
            return candidate.resolve()
    return None


def _resolve_ncnn_paths(run_json_path: Path, run_payload: dict[str, Any]) -> tuple[Path | None, Path | None]:
    training = run_payload.get("training")
    if isinstance(training, dict):
        ncnn_model_dir_value = training.get("ncnn_model_dir")
        if isinstance(ncnn_model_dir_value, str) and ncnn_model_dir_value:
            ncnn_model_dir = Path(ncnn_model_dir_value)
            if not ncnn_model_dir.is_absolute():
                ncnn_model_dir = (run_json_path.parent / ncnn_model_dir).resolve()
            param_path = ncnn_model_dir / "model.ncnn.param"
            bin_path = ncnn_model_dir / "model.ncnn.bin"
            if param_path.exists() and bin_path.exists():
                return param_path, bin_path
    for parent in (
        run_json_path.parent / "exports" / "best_ncnn_model",
        run_json_path.parent / "exports",
    ):
        param_path = parent / "model.ncnn.param"
        bin_path = parent / "model.ncnn.bin"
        if param_path.exists() and bin_path.exists():
            return param_path.resolve(), bin_path.resolve()
    legacy_param = run_json_path.parent / "exports" / "best.ncnn.param"
    legacy_bin = run_json_path.parent / "exports" / "best.ncnn.bin"
    if legacy_param.exists() and legacy_bin.exists():
        return legacy_param.resolve(), legacy_bin.resolve()
    return None, None


def _build_model_entry(run_json_path: Path, model_dir: Path, bundle_root: Path) -> dict[str, Any]:
    run_payload = _read_json(run_json_path)
    family = str(run_payload.get("model_family") or run_payload.get("inference", {}).get("family") or "")
    if family not in {"yolo", "nanodet"}:
        raise RuntimeError(f"Unsupported model family '{family}' in {run_json_path}")
    label = str(run_payload.get("run_name") or run_json_path.parent.name)
    model_id = _slugify(run_json_path.parent.name)
    imgsz = int(run_payload.get("inference", {}).get("imgsz") or run_payload.get("train_args", {}).get("imgsz") or 320)
    default_conf = float(
        run_payload.get("training", {}).get("benchmark", {}).get("selected_confidence_threshold")
        or run_payload.get("train_args", {}).get("conf")
        or 0.25
    )
    default_iou = float(run_payload.get("train_args", {}).get("iou") or 0.45)
    model_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(run_json_path, model_dir / "source_run.json")

    onnx_path = _resolve_onnx_path(run_json_path, run_payload)
    ncnn_param_path, ncnn_bin_path = _resolve_ncnn_paths(run_json_path, run_payload)

    manifest: dict[str, Any] = {
        "id": model_id,
        "label": label,
        "family": family,
        "imgsz": imgsz,
        "default_conf": default_conf,
        "default_iou": default_iou,
        "source_run_json": str(run_json_path),
        "source_run_rel": str((model_dir / "source_run.json").relative_to(bundle_root)),
    }
    if onnx_path is not None:
        onnx_dest = model_dir / "model.onnx"
        shutil.copy2(onnx_path, onnx_dest)
        manifest["onnx_rel"] = str(onnx_dest.relative_to(bundle_root))
    if ncnn_param_path is not None and ncnn_bin_path is not None:
        param_dest = model_dir / "model.ncnn.param"
        bin_dest = model_dir / "model.ncnn.bin"
        shutil.copy2(ncnn_param_path, param_dest)
        shutil.copy2(ncnn_bin_path, bin_dest)
        manifest["ncnn_param_rel"] = str(param_dest.relative_to(bundle_root))
        manifest["ncnn_bin_rel"] = str(bin_dest.relative_to(bundle_root))
    return manifest


def _build_bundle(args: argparse.Namespace) -> int:
    output_dir = Path(args.output).resolve()
    if output_dir.exists():
        if not args.force:
            raise RuntimeError(f"Output already exists: {output_dir}. Use --force to replace it.")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_json_paths = _resolve_run_json_paths(args)
    sample_ids, sample_source = _resolve_sample_ids(args, run_json_paths)
    if args.sample_limit and args.sample_limit > 0:
        sample_ids = sample_ids[: args.sample_limit]

    samples_dir = output_dir / "images"
    samples = [_build_sample_entry(sample_id, samples_dir) for sample_id in sample_ids]
    models_dir = output_dir / "models"
    models = [
        _build_model_entry(run_json_path, models_dir / _slugify(run_json_path.parent.name), output_dir)
        for run_json_path in run_json_paths
    ]

    payload = {
        "bundle_version": 1,
        "created_at": time.time(),
        "preset": args.preset,
        "sample_source": sample_source,
        "sample_count": len(samples),
        "models": models,
        "samples": samples,
    }
    _write_json(output_dir / "manifest.json", payload)

    if args.archive:
        archive_base = str(output_dir)
        shutil.make_archive(archive_base, "gztar", root_dir=output_dir.parent, base_dir=output_dir.name)

    print(json.dumps(
        {
            "ok": True,
            "bundle": str(output_dir),
            "sample_count": len(samples),
            "model_count": len(models),
            "archive": f"{output_dir}.tar.gz" if args.archive else None,
        },
        indent=2,
    ))
    return 0


def _letterbox(image: np.ndarray, size: int) -> tuple[np.ndarray, float, float, float]:
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


def _prepare_yolo_input(image: np.ndarray, imgsz: int) -> tuple[np.ndarray, dict[str, float]]:
    letterboxed, scale, pad_x, pad_y = _letterbox(image, imgsz)
    rgb = cv2.cvtColor(letterboxed, cv2.COLOR_BGR2RGB)
    blob = np.transpose(rgb.astype(np.float32) / 255.0, (2, 0, 1))[None, ...]
    metadata = {
        "scale": scale,
        "pad_x": pad_x,
        "pad_y": pad_y,
        "original_w": float(image.shape[1]),
        "original_h": float(image.shape[0]),
    }
    return blob.astype(np.float32), metadata


def _prepare_resized_rgb_input(image: np.ndarray, imgsz: int) -> tuple[np.ndarray, dict[str, float]]:
    resized = cv2.resize(image, (imgsz, imgsz), interpolation=cv2.INTER_LINEAR)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    metadata = {
        "input_size": float(imgsz),
        "original_w": float(image.shape[1]),
        "original_h": float(image.shape[0]),
        "mode": "resize",
    }
    return np.ascontiguousarray(rgb, dtype=np.uint8), metadata


def _decode_yolo_output(
    output: np.ndarray,
    *,
    preprocess: dict[str, float],
    conf_threshold: float,
    iou_threshold: float,
) -> tuple[list[list[int]], list[float]]:
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
        return [], []

    raw_boxes = raw_boxes[keep_mask]
    scores = scores[keep_mask]
    x_center = raw_boxes[:, 0]
    y_center = raw_boxes[:, 1]
    widths = raw_boxes[:, 2]
    heights = raw_boxes[:, 3]
    x1 = x_center - widths / 2.0
    y1 = y_center - heights / 2.0
    x2 = x_center + widths / 2.0
    y2 = y_center + heights / 2.0

    if "pad_x" in preprocess and "scale" in preprocess:
        x1 = (x1 - preprocess["pad_x"]) / preprocess["scale"]
        y1 = (y1 - preprocess["pad_y"]) / preprocess["scale"]
        x2 = (x2 - preprocess["pad_x"]) / preprocess["scale"]
        y2 = (y2 - preprocess["pad_y"]) / preprocess["scale"]
    else:
        scale_x = preprocess["original_w"] / preprocess["input_size"]
        scale_y = preprocess["original_h"] / preprocess["input_size"]
        x1 = x1 * scale_x
        y1 = y1 * scale_y
        x2 = x2 * scale_x
        y2 = y2 * scale_y

    boxes = np.stack([x1, y1, x2, y2], axis=1)
    boxes[:, 0] = np.clip(boxes[:, 0], 0.0, preprocess["original_w"])
    boxes[:, 1] = np.clip(boxes[:, 1], 0.0, preprocess["original_h"])
    boxes[:, 2] = np.clip(boxes[:, 2], 0.0, preprocess["original_w"])
    boxes[:, 3] = np.clip(boxes[:, 3], 0.0, preprocess["original_h"])
    valid = (boxes[:, 2] > boxes[:, 0]) & (boxes[:, 3] > boxes[:, 1])
    if not np.any(valid):
        return [], []
    boxes = boxes[valid]
    scores = scores[valid]

    kept = _nms(boxes, scores, iou_threshold)
    result_boxes = [[int(round(value)) for value in boxes[index].tolist()] for index in kept]
    result_scores = [float(scores[index]) for index in kept]
    return result_boxes, result_scores


def _prepare_nanodet_input(image: np.ndarray, imgsz: int) -> np.ndarray:
    resized = cv2.resize(image, (imgsz, imgsz), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    normalized = (resized - NANODET_MEAN) / NANODET_STD
    return np.transpose(normalized, (2, 0, 1))[None, ...].astype(np.float32)


def _prepare_hailo_yolo_input(image: np.ndarray, imgsz: int) -> tuple[np.ndarray, dict[str, float]]:
    letterboxed, scale, pad_x, pad_y = _letterbox(image, imgsz)
    rgb = cv2.cvtColor(letterboxed, cv2.COLOR_BGR2RGB)
    metadata = {
        "scale": scale,
        "pad_x": pad_x,
        "pad_y": pad_y,
        "original_w": float(image.shape[1]),
        "original_h": float(image.shape[0]),
        "input_size": float(imgsz),
    }
    return np.ascontiguousarray(rgb, dtype=np.uint8), metadata


def _prepare_hailo_nanodet_input(image: np.ndarray, imgsz: int) -> np.ndarray:
    resized = cv2.resize(image, (imgsz, imgsz), interpolation=cv2.INTER_LINEAR)
    return np.ascontiguousarray(resized, dtype=np.uint8)


def _decode_nanodet_output(
    output: np.ndarray,
    *,
    imgsz: int,
    original_h: int,
    original_w: int,
    conf_threshold: float,
    iou_threshold: float,
    reg_max: int = 7,
    strides: list[int] | None = None,
) -> tuple[list[list[int]], list[float]]:
    if strides is None:
        strides = [8, 16, 32, 64]
    preds = np.asarray(output)
    if preds.ndim == 3:
        preds = preds[0]
    if preds.ndim != 2:
        raise RuntimeError(f"Unexpected NanoDet output rank: {preds.shape}")
    if preds.shape[0] <= 64 and preds.shape[1] > preds.shape[0]:
        preds = preds.T

    anchor_points: list[tuple[float, float, int]] = []
    for stride in strides:
        grid_h = imgsz // stride
        grid_w = imgsz // stride
        for y in range(grid_h):
            for x in range(grid_w):
                anchor_points.append((x * stride, y * stride, stride))

    num_reg = 4 * (reg_max + 1)
    num_classes = preds.shape[1] - num_reg
    if num_classes <= 0:
        raise RuntimeError(f"Unexpected NanoDet channel count: {preds.shape}")
    cls_scores = preds[:, :num_classes]
    bbox_preds = preds[:, num_classes:]
    if cls_scores.max() > 1.0 or cls_scores.min() < 0.0:
        cls_scores = 1.0 / (1.0 + np.exp(-cls_scores))

    all_boxes: list[list[float]] = []
    all_scores: list[float] = []
    scale_x = float(original_w) / float(imgsz)
    scale_y = float(original_h) / float(imgsz)
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
        x1 = max(0.0, min(float(original_w), (cx - distances[0]) * scale_x))
        y1 = max(0.0, min(float(original_h), (cy - distances[1]) * scale_y))
        x2 = max(0.0, min(float(original_w), (cx + distances[2]) * scale_x))
        y2 = max(0.0, min(float(original_h), (cy + distances[3]) * scale_y))
        if x2 <= x1 or y2 <= y1:
            continue
        all_boxes.append([x1, y1, x2, y2])
        all_scores.append(score)

    if not all_boxes:
        return [], []
    boxes_np = np.asarray(all_boxes, dtype=np.float32)
    scores_np = np.asarray(all_scores, dtype=np.float32)
    kept = _nms(boxes_np, scores_np, iou_threshold)
    result_boxes = [[int(round(value)) for value in all_boxes[index]] for index in kept]
    result_scores = [float(all_scores[index]) for index in kept]
    return result_boxes, result_scores


def _make_onnx_session(model_path: Path, threads: int) -> Any:
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError(
            "onnxruntime is not installed. Run `uv sync` in software/client or install onnxruntime manually."
        ) from exc
    session_options = ort.SessionOptions()
    session_options.intra_op_num_threads = max(1, threads)
    session_options.inter_op_num_threads = 1
    session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session_options.log_severity_level = 3
    return ort.InferenceSession(str(model_path), sess_options=session_options, providers=["CPUExecutionProvider"])


def _make_coreml_session(model_path: Path, threads: int) -> Any:
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError(
            "onnxruntime is not installed. Run `uv sync` in software/client or install onnxruntime manually."
        ) from exc
    session_options = ort.SessionOptions()
    session_options.intra_op_num_threads = max(1, threads)
    session_options.inter_op_num_threads = 1
    session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session_options.log_severity_level = 3
    providers = ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    session = ort.InferenceSession(str(model_path), sess_options=session_options, providers=providers)
    if "CoreMLExecutionProvider" not in session.get_providers():
        raise RuntimeError(
            "CoreMLExecutionProvider is not available in this onnxruntime build. "
            "Use runtime=onnx or install a build that exposes CoreML on macOS."
        )
    return session


def _make_ncnn_net(param_path: Path, bin_path: Path, threads: int) -> Any:
    try:
        import ncnn
    except ImportError as exc:
        raise RuntimeError(
            "ncnn is not installed. Use runtime=onnx or install the ncnn Python bindings on the target device."
        ) from exc
    net = ncnn.Net()
    net.opt.use_vulkan_compute = False
    net.opt.num_threads = max(1, threads)
    net.load_param(str(param_path))
    net.load_model(str(bin_path))
    input_names = list(net.input_names())
    output_names = list(net.output_names())
    if not input_names or not output_names:
        raise RuntimeError(f"Could not resolve NCNN input/output names from {param_path}")
    return {
        "net": net,
        "input_name": str(input_names[0]),
        "output_name": str(output_names[0]),
    }


class _RKNNRunner:
    def __init__(self, model_path: Path):
        try:
            from rknnlite.api import RKNNLite
        except ImportError as exc:
            raise RuntimeError(
                "rknnlite is not installed. Install the RKNNLite runtime or use a different runtime."
            ) from exc

        self._RKNNLite = RKNNLite
        self.model_path = model_path
        self._rknn = RKNNLite()
        ret = self._rknn.load_rknn(str(model_path))
        if ret != 0:
            raise RuntimeError(f"Failed to load RKNN model {model_path} (ret={ret})")

        init_ok = False
        core_masks = [
            getattr(RKNNLite, "NPU_CORE_0_1_2", None),
            getattr(RKNNLite, "NPU_CORE_AUTO", None),
            getattr(RKNNLite, "NPU_CORE_0", None),
        ]
        self.core_mask_name = "default"
        for core_mask in core_masks:
            if core_mask is None:
                continue
            ret = self._rknn.init_runtime(core_mask=core_mask)
            if ret == 0:
                self.core_mask_name = {
                    getattr(RKNNLite, "NPU_CORE_0_1_2", object()): "NPU_CORE_0_1_2",
                    getattr(RKNNLite, "NPU_CORE_AUTO", object()): "NPU_CORE_AUTO",
                    getattr(RKNNLite, "NPU_CORE_0", object()): "NPU_CORE_0",
                }.get(core_mask, "custom")
                init_ok = True
                break
        if not init_ok:
            ret = self._rknn.init_runtime()
            if ret != 0:
                raise RuntimeError(f"Failed to init RKNN runtime for {model_path} (ret={ret})")

    def close(self) -> None:
        rknn = getattr(self, "_rknn", None)
        if rknn is not None:
            try:
                rknn.release()
            except Exception:
                pass
            self._rknn = None

    def infer(self, input_buffer: np.ndarray) -> Any:
        batch = np.ascontiguousarray(input_buffer)
        if batch.ndim == 3:
            batch = batch[None, ...]
        outputs = self._rknn.inference(inputs=[batch])
        if outputs is None:
            raise RuntimeError("RKNN inference returned no outputs.")
        if len(outputs) == 1:
            return np.asarray(outputs[0])
        return [np.asarray(value) for value in outputs]


class _HailoRunner:
    def __init__(self, hef_path: Path, family: str):
        try:
            from hailo_platform import (
                ConfigureParams,
                FormatType,
                HailoStreamInterface,
                HEF,
                InferVStreams,
                InputVStreamParams,
                OutputVStreamParams,
                VDevice,
            )
        except ImportError as exc:
            raise RuntimeError(
                "hailo_platform is not installed. Install python3-hailort or use a different runtime."
            ) from exc

        self.family = family
        self.hef_path = hef_path
        self._vdevice = VDevice()
        self._hef = HEF(str(hef_path))
        configure_params = ConfigureParams.create_from_hef(self._hef, HailoStreamInterface.PCIe)
        configured_networks = self._vdevice.configure(self._hef, configure_params)
        if not configured_networks:
            raise RuntimeError(f"Could not configure HEF: {hef_path}")
        self._network_group = configured_networks[0]
        self.input_name = self._hef.get_input_vstream_infos()[0].name
        self.output_names = [info.name for info in self._hef.get_output_vstream_infos()]

        input_params = InputVStreamParams.make_from_network_group(
            self._network_group,
            quantized=False,
            format_type=FormatType.UINT8,
            timeout_ms=HAILO_TIMEOUT_MS,
        )
        output_params = OutputVStreamParams.make_from_network_group(
            self._network_group,
            quantized=False,
            format_type=FormatType.FLOAT32,
            timeout_ms=HAILO_TIMEOUT_MS,
        )
        self._activation = self._network_group.activate(self._network_group.create_params())
        self._activation.__enter__()
        self._pipeline = InferVStreams(self._network_group, input_params, output_params)
        self._pipeline.__enter__()

    def close(self) -> None:
        pipeline = getattr(self, "_pipeline", None)
        if pipeline is not None:
            try:
                pipeline.__exit__(None, None, None)
            except Exception:
                pass
            self._pipeline = None
        activation = getattr(self, "_activation", None)
        if activation is not None:
            try:
                activation.__exit__(None, None, None)
            except Exception:
                pass
            self._activation = None
        vdevice = getattr(self, "_vdevice", None)
        if vdevice is not None:
            try:
                vdevice.release()
            except Exception:
                pass
            self._vdevice = None

    def infer(self, input_buffer: np.ndarray) -> Any:
        batch = np.ascontiguousarray(input_buffer)
        if batch.ndim == 3:
            batch = batch[None, ...]
        outputs = self._pipeline.infer({self.input_name: batch})
        if len(outputs) == 1:
            return next(iter(outputs.values()))
        return outputs


def _decode_hailo_yolo_box(
    raw_box: list[float],
    *,
    preprocess: dict[str, float],
    assume_yxyx: bool,
) -> list[int] | None:
    coords = np.asarray(raw_box[:4], dtype=np.float32)
    if np.max(np.abs(coords)) <= 1.5:
        coords = coords * float(preprocess["input_size"])
    if assume_yxyx:
        y1, x1, y2, x2 = coords.tolist()
    else:
        x1, y1, x2, y2 = coords.tolist()
    x1 = (x1 - preprocess["pad_x"]) / preprocess["scale"]
    y1 = (y1 - preprocess["pad_y"]) / preprocess["scale"]
    x2 = (x2 - preprocess["pad_x"]) / preprocess["scale"]
    y2 = (y2 - preprocess["pad_y"]) / preprocess["scale"]
    x1 = max(0.0, min(float(preprocess["original_w"]), x1))
    y1 = max(0.0, min(float(preprocess["original_h"]), y1))
    x2 = max(0.0, min(float(preprocess["original_w"]), x2))
    y2 = max(0.0, min(float(preprocess["original_h"]), y2))
    if x2 <= x1 or y2 <= y1:
        return None
    return [int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))]


def _decode_hailo_yolo_output(
    output: Any,
    *,
    preprocess: dict[str, float],
    conf_threshold: float,
) -> tuple[list[list[int]], list[float]]:
    class_outputs = output if isinstance(output, list) else [output]
    boxes: list[list[int]] = []
    scores: list[float] = []
    for class_output in class_outputs:
        array = np.asarray(class_output)
        if array.size == 0:
            continue
        if array.ndim == 3 and array.shape[0] == 1:
            array = array[0]
        if array.ndim == 1:
            if array.size % 5 != 0:
                raise RuntimeError(f"Unexpected Hailo YOLO output shape: {array.shape}")
            array = array.reshape(-1, 5)
        if array.ndim == 3 and array.shape[-1] >= 5:
            array = array.reshape(-1, array.shape[-1])
        if array.ndim != 2 or array.shape[1] < 5:
            raise RuntimeError(f"Unexpected Hailo YOLO output shape: {array.shape}")
        for row in array:
            score = float(row[4])
            if score < conf_threshold:
                continue
            box = _decode_hailo_yolo_box(row.tolist(), preprocess=preprocess, assume_yxyx=True)
            if box is None:
                box = _decode_hailo_yolo_box(row.tolist(), preprocess=preprocess, assume_yxyx=False)
            if box is None:
                continue
            boxes.append(box)
            scores.append(score)
    return boxes, scores


def _flatten_hailo_nanodet_outputs(output: Any) -> np.ndarray:
    if isinstance(output, dict):
        arrays = [np.asarray(value) for _, value in sorted(output.items(), key=lambda item: (-np.asarray(item[1]).shape[1], item[0]))]
    elif isinstance(output, list):
        arrays = [np.asarray(value) for value in output]
        arrays.sort(key=lambda value: -value.shape[1])
    else:
        raise RuntimeError(f"Unexpected Hailo NanoDet output container: {type(output)!r}")

    flattened: list[np.ndarray] = []
    for array in arrays:
        if array.ndim == 4 and array.shape[0] == 1:
            array = array[0]
        if array.ndim != 3:
            raise RuntimeError(f"Unexpected Hailo NanoDet output shape: {array.shape}")
        flattened.append(array.reshape(-1, array.shape[-1]))
    if not flattened:
        raise RuntimeError("Hailo NanoDet inference returned no outputs.")
    return np.concatenate(flattened, axis=0)


def _infer_onnx(
    session: Any,
    family: str,
    image: np.ndarray,
    imgsz: int,
    conf: float,
    iou: float,
    repeat: int,
) -> tuple[list[list[int]], list[float], float]:
    input_name = session.get_inputs()[0].name
    if family == "yolo":
        blob, preprocess = _prepare_yolo_input(image, imgsz)
    elif family == "nanodet":
        blob = _prepare_nanodet_input(image, imgsz)
        preprocess = {}
    else:
        raise RuntimeError(f"Unsupported family for ONNX runtime: {family}")

    outputs: list[Any] = []
    start = time.perf_counter()
    for _ in range(max(1, repeat)):
        outputs = session.run(None, {input_name: blob})
    latency_ms = (time.perf_counter() - start) * 1000.0 / float(max(1, repeat))

    if not outputs:
        raise RuntimeError("Model returned no outputs.")
    if family == "yolo":
        boxes, scores = _decode_yolo_output(outputs[0], preprocess=preprocess, conf_threshold=conf, iou_threshold=iou)
    else:
        boxes, scores = _decode_nanodet_output(
            outputs[0],
            imgsz=imgsz,
            original_h=image.shape[0],
            original_w=image.shape[1],
            conf_threshold=conf,
            iou_threshold=iou,
        )
    return boxes, scores, latency_ms


def _infer_coreml(
    session: Any,
    family: str,
    image: np.ndarray,
    imgsz: int,
    conf: float,
    iou: float,
    repeat: int,
) -> tuple[list[list[int]], list[float], float]:
    return _infer_onnx(session, family, image, imgsz, conf, iou, repeat)


def _infer_ncnn(
    net_bundle: Any,
    family: str,
    image: np.ndarray,
    imgsz: int,
    conf: float,
    iou: float,
    repeat: int,
) -> tuple[list[list[int]], list[float], float]:
    try:
        import ncnn
    except ImportError as exc:
        raise RuntimeError("ncnn import failed unexpectedly.") from exc

    if family == "yolo":
        blob, preprocess = _prepare_yolo_input(image, imgsz)
    elif family == "nanodet":
        blob = _prepare_nanodet_input(image, imgsz)
        preprocess = {}
    else:
        raise RuntimeError(f"Unsupported family for NCNN runtime: {family}")

    mat = ncnn.Mat(blob[0]).clone()
    raw_output: np.ndarray | None = None
    start = time.perf_counter()
    for _ in range(max(1, repeat)):
        with net_bundle["net"].create_extractor() as extractor:
            extractor.input(net_bundle["input_name"], mat)
            _, out0 = extractor.extract(net_bundle["output_name"])
            raw_output = np.array(out0)
    latency_ms = (time.perf_counter() - start) * 1000.0 / float(max(1, repeat))

    if raw_output is None:
        raise RuntimeError("NCNN inference returned no output.")
    if family == "yolo":
        boxes, scores = _decode_yolo_output(raw_output, preprocess=preprocess, conf_threshold=conf, iou_threshold=iou)
    else:
        boxes, scores = _decode_nanodet_output(
            raw_output,
            imgsz=imgsz,
            original_h=image.shape[0],
            original_w=image.shape[1],
            conf_threshold=conf,
            iou_threshold=iou,
        )
    return boxes, scores, latency_ms


def _infer_rknn(
    runner: _RKNNRunner,
    family: str,
    image: np.ndarray,
    imgsz: int,
    conf: float,
    iou: float,
    repeat: int,
) -> tuple[list[list[int]], list[float], float]:
    if family == "yolo":
        input_buffer, preprocess = _prepare_resized_rgb_input(image, imgsz)
    elif family == "nanodet":
        input_buffer, _ = _prepare_resized_rgb_input(image, imgsz)
        preprocess = {}
    else:
        raise RuntimeError(f"Unsupported family for RKNN runtime: {family}")

    raw_output: Any = None
    start = time.perf_counter()
    for _ in range(max(1, repeat)):
        raw_output = runner.infer(input_buffer)
    latency_ms = (time.perf_counter() - start) * 1000.0 / float(max(1, repeat))

    if raw_output is None:
        raise RuntimeError("RKNN inference returned no output.")
    if family == "yolo":
        boxes, scores = _decode_yolo_output(raw_output, preprocess=preprocess, conf_threshold=conf, iou_threshold=iou)
    else:
        boxes, scores = _decode_nanodet_output(
            raw_output,
            imgsz=imgsz,
            original_h=image.shape[0],
            original_w=image.shape[1],
            conf_threshold=conf,
            iou_threshold=iou,
        )
    return boxes, scores, latency_ms


def _infer_hailo(
    runner: _HailoRunner,
    family: str,
    image: np.ndarray,
    imgsz: int,
    conf: float,
    iou: float,
    repeat: int,
) -> tuple[list[list[int]], list[float], float]:
    if family == "yolo":
        input_buffer, preprocess = _prepare_hailo_yolo_input(image, imgsz)
    elif family == "nanodet":
        input_buffer = _prepare_hailo_nanodet_input(image, imgsz)
        preprocess = {}
    else:
        raise RuntimeError(f"Unsupported family for Hailo runtime: {family}")

    raw_output: Any = None
    start = time.perf_counter()
    for _ in range(max(1, repeat)):
        raw_output = runner.infer(input_buffer)
    latency_ms = (time.perf_counter() - start) * 1000.0 / float(max(1, repeat))

    if raw_output is None:
        raise RuntimeError("Hailo inference returned no output.")
    if family == "yolo":
        boxes, scores = _decode_hailo_yolo_output(raw_output, preprocess=preprocess, conf_threshold=conf)
    else:
        boxes, scores = _decode_nanodet_output(
            _flatten_hailo_nanodet_outputs(raw_output),
            imgsz=imgsz,
            original_h=image.shape[0],
            original_w=image.shape[1],
            conf_threshold=conf,
            iou_threshold=iou,
        )
    return boxes, scores, latency_ms


def _load_bundle_manifest(bundle_dir: Path) -> dict[str, Any]:
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Bundle manifest missing: {manifest_path}")
    return _read_json(manifest_path)


def _select_models(manifest: dict[str, Any], selected_ids: list[str] | None) -> list[dict[str, Any]]:
    models = manifest.get("models")
    if not isinstance(models, list):
        raise RuntimeError("Bundle manifest is missing models.")
    available = [model for model in models if isinstance(model, dict)]
    if not selected_ids:
        return available
    selected = [model for model in available if str(model.get("id")) in set(selected_ids)]
    if not selected:
        raise RuntimeError(f"No matching models found for {selected_ids}")
    return selected


def _system_summary(runtime: str) -> dict[str, Any]:
    return {
        "hostname": platform.node(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "cpu_model": _cpu_model(),
        "platform": platform.platform(),
        "release": platform.release(),
        "python": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
        "runtime": runtime,
    }


def _parse_hef_model_args(values: list[str] | None) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for raw_value in values or []:
        model_id, separator, path_value = raw_value.partition("=")
        if not separator or not model_id or not path_value:
            raise RuntimeError(
                f"Invalid --hef-model value {raw_value!r}. Expected the form model_id=/absolute/or/relative/path.hef"
            )
        mapping[model_id] = Path(path_value).expanduser().resolve()
    return mapping


def _parse_runtime_model_args(values: list[str] | None, option_name: str) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for raw_value in values or []:
        model_id, separator, path_value = raw_value.partition("=")
        if not separator or not model_id or not path_value:
            raise RuntimeError(
                f"Invalid {option_name} value {raw_value!r}. Expected the form model_id=/absolute/or/relative/path"
            )
        mapping[model_id] = Path(path_value).expanduser().resolve()
    return mapping


def _benchmark_model(
    *,
    bundle_dir: Path,
    model: dict[str, Any],
    samples: list[dict[str, Any]],
    runtime: str,
    threads: int,
    warmup: int,
    repeat: int,
    conf_override: float | None,
    iou_override: float | None,
    hef_paths: dict[str, Path] | None = None,
    rknn_paths: dict[str, Path] | None = None,
) -> dict[str, Any]:
    family = str(model.get("family") or "")
    imgsz = int(model.get("imgsz") or 320)
    conf = float(conf_override if conf_override is not None else model.get("default_conf") or 0.25)
    iou = float(iou_override if iou_override is not None else model.get("default_iou") or 0.45)

    model_path = None
    runner: Any = None
    if runtime == "onnx":
        onnx_rel = model.get("onnx_rel")
        if not isinstance(onnx_rel, str):
            raise RuntimeError(f"Model {model.get('id')} does not include an ONNX export in the bundle.")
        model_path = (bundle_dir / onnx_rel).resolve()
        runner = _make_onnx_session(model_path, threads)
    elif runtime == "coreml":
        onnx_rel = model.get("onnx_rel")
        if not isinstance(onnx_rel, str):
            raise RuntimeError(f"Model {model.get('id')} does not include an ONNX export in the bundle.")
        model_path = (bundle_dir / onnx_rel).resolve()
        runner = _make_coreml_session(model_path, threads)
    elif runtime == "ncnn":
        param_rel = model.get("ncnn_param_rel")
        bin_rel = model.get("ncnn_bin_rel")
        if not isinstance(param_rel, str) or not isinstance(bin_rel, str):
            raise RuntimeError(f"Model {model.get('id')} does not include NCNN files in the bundle.")
        model_path = (bundle_dir / param_rel).resolve()
        runner = _make_ncnn_net((bundle_dir / param_rel).resolve(), (bundle_dir / bin_rel).resolve(), threads)
    elif runtime == "rknn":
        model_id = str(model.get("id") or "")
        rknn_paths = rknn_paths or {}
        rknn_path = rknn_paths.get(model_id)
        if rknn_path is None:
            raise RuntimeError(
                f"Model {model_id!r} is missing an RKNN mapping. Pass --rknn-model {model_id}=/path/to/model.rknn"
            )
        if not rknn_path.exists():
            raise FileNotFoundError(f"RKNN file not found for model {model_id!r}: {rknn_path}")
        model_path = rknn_path
        runner = _RKNNRunner(rknn_path)
    elif runtime == "hailo":
        model_id = str(model.get("id") or "")
        hef_paths = hef_paths or {}
        hef_path = hef_paths.get(model_id)
        if hef_path is None:
            raise RuntimeError(
                f"Model {model_id!r} is missing a HEF mapping. Pass --hef-model {model_id}=/path/to/model.hef"
            )
        if not hef_path.exists():
            raise FileNotFoundError(f"HEF file not found for model {model_id!r}: {hef_path}")
        model_path = hef_path
        runner = _HailoRunner(hef_path, family)
    else:
        raise RuntimeError(f"Unsupported runtime: {runtime}")

    total = 0
    exact_count = 0
    decision_match = 0
    multi_samples = 0
    multi_detect = 0
    single_ious: list[float] = []
    latencies_ms: list[float] = []
    per_sample: list[dict[str, Any]] = []

    try:
        if samples and warmup > 0:
            warmup_image = cv2.imread(str(bundle_dir / "images" / str(samples[0]["image"])), cv2.IMREAD_COLOR)
            if warmup_image is not None:
                for _ in range(warmup):
                    if runtime == "onnx":
                        _infer_onnx(runner, family, warmup_image, imgsz, conf, iou, 1)
                    elif runtime == "coreml":
                        _infer_coreml(runner, family, warmup_image, imgsz, conf, iou, 1)
                    elif runtime == "ncnn":
                        _infer_ncnn(runner, family, warmup_image, imgsz, conf, iou, 1)
                    elif runtime == "rknn":
                        _infer_rknn(runner, family, warmup_image, imgsz, conf, iou, 1)
                    else:
                        _infer_hailo(runner, family, warmup_image, imgsz, conf, iou, 1)

        for sample in samples:
            image_path = bundle_dir / "images" / str(sample["image"])
            image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            if image is None:
                per_sample.append({"image": sample["image"], "ok": False, "error": "could_not_read_image"})
                continue

            if runtime == "onnx":
                pred_boxes, pred_scores, latency_ms = _infer_onnx(runner, family, image, imgsz, conf, iou, repeat)
            elif runtime == "coreml":
                pred_boxes, pred_scores, latency_ms = _infer_coreml(runner, family, image, imgsz, conf, iou, repeat)
            elif runtime == "ncnn":
                pred_boxes, pred_scores, latency_ms = _infer_ncnn(runner, family, image, imgsz, conf, iou, repeat)
            elif runtime == "rknn":
                pred_boxes, pred_scores, latency_ms = _infer_rknn(runner, family, image, imgsz, conf, iou, repeat)
            else:
                pred_boxes, pred_scores, latency_ms = _infer_hailo(runner, family, image, imgsz, conf, iou, repeat)
            pred_boxes_normalized = [_normalize_box(box, image.shape[1], image.shape[0]) for box in pred_boxes]
            gt_boxes_normalized = sample.get("gt_boxes_normalized") if isinstance(sample.get("gt_boxes_normalized"), list) else []
            gt_count = int(sample.get("detection_count") or len(gt_boxes_normalized))
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
            single_iou = None
            if gt_count == 1 and pred_count == 1 and gt_boxes_normalized:
                single_iou = _iou(pred_boxes_normalized[0], [float(value) for value in gt_boxes_normalized[0]])
                single_ious.append(single_iou)

            per_sample.append(
                {
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
                    "single_iou": round(single_iou, 5) if single_iou is not None else None,
                }
            )
    finally:
        if isinstance(runner, (_HailoRunner, _RKNNRunner)):
            runner.close()

    avg_latency_ms = float(sum(latencies_ms) / len(latencies_ms)) if latencies_ms else None
    payload = {
        "created_at": time.time(),
        "system": _system_summary(runtime),
        "model": {
            "id": model.get("id"),
            "label": model.get("label"),
            "family": family,
            "imgsz": imgsz,
            "runtime": runtime,
            "model_path": str(model_path) if model_path is not None else None,
        },
        "summary": {
            "model_id": model.get("id"),
            "model_label": model.get("label"),
            "model_family": family,
            "runtime": runtime,
            "imgsz": imgsz,
            "conf": conf,
            "iou": iou,
            "threads": threads,
            "repeat": repeat,
            "warmup": warmup,
            "sample_count": total,
            "avg_latency_ms": round(avg_latency_ms, 3) if avg_latency_ms is not None else None,
            "median_latency_ms": round(float(statistics.median(latencies_ms)), 3) if latencies_ms else None,
            "p95_latency_ms": round(_percentile(latencies_ms, 95) or 0.0, 3) if latencies_ms else None,
            "avg_fps": round(1000.0 / avg_latency_ms, 2) if avg_latency_ms and avg_latency_ms > 0 else None,
            "exact_count_match_rate": round(exact_count / total, 5) if total else None,
            "decision_match_rate": round(decision_match / total, 5) if total else None,
            "single_mean_iou": round(float(sum(single_ious) / len(single_ious)), 5) if single_ious else None,
            "multi_detect_rate": round(multi_detect / multi_samples, 5) if multi_samples else None,
        },
        "per_sample": per_sample,
    }
    return payload


def _run_bundle(args: argparse.Namespace) -> int:
    bundle_dir = Path(args.bundle).resolve()
    manifest = _load_bundle_manifest(bundle_dir)
    models = _select_models(manifest, args.model_id)
    samples_raw = manifest.get("samples")
    if not isinstance(samples_raw, list):
        raise RuntimeError("Bundle manifest is missing samples.")
    samples = [sample for sample in samples_raw if isinstance(sample, dict)]
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    tag = _slugify(args.tag or platform.node() or "device")
    result_paths: list[str] = []
    hef_paths = _parse_hef_model_args(args.hef_model)
    rknn_paths = _parse_runtime_model_args(args.rknn_model, "--rknn-model")

    for model in models:
        runtime = args.runtime
        if runtime == "auto":
            has_ncnn = isinstance(model.get("ncnn_param_rel"), str) and isinstance(model.get("ncnn_bin_rel"), str)
            has_onnx = isinstance(model.get("onnx_rel"), str)
            if has_ncnn and _module_available("ncnn"):
                runtime = "ncnn"
            elif has_onnx:
                runtime = "onnx"
            elif has_ncnn:
                runtime = "ncnn"
            else:
                raise RuntimeError(f"Model {model.get('id')} has neither ONNX nor NCNN bundle files.")
        payload = _benchmark_model(
            bundle_dir=bundle_dir,
            model=model,
            samples=samples,
            runtime=runtime,
            threads=max(1, args.threads),
            warmup=max(0, args.warmup),
            repeat=max(1, args.repeat),
            conf_override=args.conf,
            iou_override=args.iou,
            hef_paths=hef_paths,
            rknn_paths=rknn_paths,
        )
        output_path = output_dir / f"{tag}__{model['id']}__{runtime}.json"
        _write_json(output_path, payload)
        result_paths.append(str(output_path))

    print(json.dumps({"ok": True, "results": result_paths}, indent=2))
    return 0


def _fmt_float(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{digits}f}"


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def _confusion_rows(per_sample: list[dict[str, Any]]) -> list[tuple[str, int]]:
    counter: dict[str, int] = {}
    for row in per_sample:
        if not row.get("ok"):
            key = "error -> error"
        else:
            key = f"{row.get('gt_decision', 'unknown')} -> {row.get('pred_decision', 'unknown')}"
        counter[key] = counter.get(key, 0) + 1
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))


def _load_manifest_index(bundle_dir: Path) -> dict[str, dict[str, Any]]:
    manifest = _load_bundle_manifest(bundle_dir)
    samples = manifest.get("samples")
    if not isinstance(samples, list):
        raise RuntimeError(f"Bundle manifest is missing samples: {bundle_dir}")
    return {
        str(sample["image"]): sample
        for sample in samples
        if isinstance(sample, dict) and isinstance(sample.get("image"), str)
    }


def _normalized_to_xyxy(box: list[float], width: int, height: int) -> list[int]:
    x1 = int(round(max(0.0, min(1.0, float(box[0]))) * width))
    y1 = int(round(max(0.0, min(1.0, float(box[1]))) * height))
    x2 = int(round(max(0.0, min(1.0, float(box[2]))) * width))
    y2 = int(round(max(0.0, min(1.0, float(box[3]))) * height))
    return [x1, y1, x2, y2]


def _draw_overlay(
    image_path: Path,
    boxes: list[list[int]],
    *,
    title: str,
    color: tuple[int, int, int],
    label_prefix: str,
    scores: list[float] | None = None,
) -> Any:
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Could not read image: {image_path}")
    overlay = image.copy()
    for index, box in enumerate(boxes, start=1):
        x1, y1, x2, y2 = box
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 2)
        label = f"{label_prefix} {index}"
        if scores is not None and index - 1 < len(scores):
            label = f"{label} {float(scores[index - 1]):.2f}"
        cv2.putText(
            overlay,
            label,
            (x1, max(22, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            lineType=cv2.LINE_AA,
        )
    cv2.putText(
        overlay,
        title,
        (16, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.85,
        color,
        2,
        lineType=cv2.LINE_AA,
    )
    return overlay


def _write_sample_assets(
    *,
    asset_dir: Path,
    image_dir: Path,
    manifest_index: dict[str, dict[str, Any]],
    per_sample: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    ranked = sorted(
        per_sample,
        key=lambda row: (
            row.get("gt_decision") == row.get("pred_decision"),
            abs(int(row.get("pred_count", 0)) - int(row.get("gt_count", 0))),
            float(row.get("latency_ms", 0.0)),
        ),
    )
    cards: list[dict[str, Any]] = []
    for row in ranked[:limit]:
        image_name = str(row.get("image", ""))
        if not image_name:
            continue
        image_path = image_dir / image_name
        if not image_path.exists():
            continue
        manifest_sample = manifest_index.get(image_name, {})
        source = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if source is None:
            continue
        height, width = source.shape[:2]

        gt_boxes = []
        gt_boxes_normalized = manifest_sample.get("gt_boxes_normalized")
        if isinstance(gt_boxes_normalized, list):
            for box in gt_boxes_normalized:
                if isinstance(box, list) and len(box) >= 4:
                    gt_boxes.append(_normalized_to_xyxy([float(value) for value in box[:4]], width, height))

        pred_boxes = []
        if isinstance(row.get("candidate_bboxes"), list):
            pred_boxes = [
                [int(value) for value in box[:4]]
                for box in row["candidate_bboxes"]
                if isinstance(box, list) and len(box) >= 4
            ]
        pred_scores = [float(score) for score in row.get("scores", [])] if isinstance(row.get("scores"), list) else []

        stem = Path(image_name).stem
        pred_overlay_path = asset_dir / f"{stem}-device-overlay.jpg"
        ref_overlay_path = asset_dir / f"{stem}-reference-overlay.jpg"

        pred_overlay = _draw_overlay(
            image_path,
            pred_boxes,
            title="Device prediction",
            color=(0, 114, 255),
            label_prefix="Pred",
            scores=pred_scores,
        )
        ref_overlay = _draw_overlay(
            image_path,
            gt_boxes,
            title="Reference boxes",
            color=(0, 180, 90),
            label_prefix="GT",
        )
        pred_overlay_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(pred_overlay_path), pred_overlay)
        cv2.imwrite(str(ref_overlay_path), ref_overlay)

        cards.append(
            {
                "image": image_name,
                "pred_overlay": pred_overlay_path.name,
                "ref_overlay": ref_overlay_path.name,
                "gt_decision": row.get("gt_decision"),
                "pred_decision": row.get("pred_decision"),
                "gt_count": row.get("gt_count"),
                "pred_count": row.get("pred_count"),
                "latency_ms": row.get("latency_ms"),
                "fps": row.get("fps"),
            }
        )
    return cards


def _sample_table_rows(per_sample: list[dict[str, Any]], limit: int = 12) -> str:
    ranked = sorted(
        per_sample,
        key=lambda row: (
            row.get("gt_decision") == row.get("pred_decision"),
            float(row.get("latency_ms", 0.0)),
        ),
    )
    rows: list[str] = []
    for row in ranked[:limit]:
        rows.append(
            "<tr>"
            f"<td>{escape(str(row.get('image', 'unknown')))}</td>"
            f"<td>{escape(str(row.get('gt_decision', 'n/a')))}</td>"
            f"<td>{escape(str(row.get('pred_decision', 'n/a')))}</td>"
            f"<td>{escape(str(row.get('gt_count', 'n/a')))}</td>"
            f"<td>{escape(str(row.get('pred_count', 'n/a')))}</td>"
            f"<td>{_fmt_float(row.get('latency_ms'), 2)} ms</td>"
            f"<td>{_fmt_float(row.get('fps'), 2)}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _sample_cards_html(sample_cards: list[dict[str, Any]], assets_rel: str) -> str:
    blocks: list[str] = []
    for row in sample_cards:
        blocks.append(
            f"""
            <article class="sample-card">
              <div class="sample-head">
                <strong>{escape(str(row['image']))}</strong>
                <span>{escape(str(row['gt_decision']))} -> {escape(str(row['pred_decision']))}</span>
              </div>
              <div class="sample-meta">
                <span>GT count {escape(str(row['gt_count']))}</span>
                <span>Pred count {escape(str(row['pred_count']))}</span>
                <span>{_fmt_float(row['latency_ms'], 2)} ms</span>
                <span>{_fmt_float(row['fps'], 2)} FPS</span>
              </div>
              <div class="sample-images">
                <figure>
                  <img src="{assets_rel}/{escape(str(row['pred_overlay']))}" alt="Device overlay for {escape(str(row['image']))}" />
                  <figcaption>Device prediction</figcaption>
                </figure>
                <figure>
                  <img src="{assets_rel}/{escape(str(row['ref_overlay']))}" alt="Reference overlay for {escape(str(row['image']))}" />
                  <figcaption>Local reference boxes</figcaption>
                </figure>
              </div>
            </article>
            """
        )
    return "\n".join(blocks)


def _card(
    title: str,
    summary: dict[str, Any],
    system: dict[str, Any],
    per_sample: list[dict[str, Any]],
    sample_cards: list[dict[str, Any]],
    assets_rel: str,
) -> str:
    confusion_html = "".join(
        f"<tr><td>{escape(label)}</td><td>{count}</td></tr>"
        for label, count in _confusion_rows(per_sample)
    )
    return f"""
    <section class="card">
      <h2>{escape(title)}</h2>
      <p class="muted">{escape(str(system.get('hostname', 'unknown')))} · {escape(str(system.get('machine', 'unknown')))} · {escape(str(system.get('cpu_model') or system.get('processor') or 'unknown cpu'))}</p>
      <div class="metrics">
        <div><span>Samples</span><strong>{summary.get('sample_count', 'n/a')}</strong></div>
        <div><span>Avg Latency</span><strong>{_fmt_float(summary.get('avg_latency_ms'), 2)} ms</strong></div>
        <div><span>P95</span><strong>{_fmt_float(summary.get('p95_latency_ms'), 2)} ms</strong></div>
        <div><span>FPS</span><strong>{_fmt_float(summary.get('avg_fps'), 2)}</strong></div>
        <div><span>Exact Count</span><strong>{_fmt_pct(summary.get('exact_count_match_rate'))}</strong></div>
        <div><span>Decision Match</span><strong>{_fmt_pct(summary.get('decision_match_rate'))}</strong></div>
        <div><span>Single IoU</span><strong>{_fmt_float(summary.get('single_mean_iou'), 3)}</strong></div>
        <div><span>Multi Detect</span><strong>{_fmt_pct(summary.get('multi_detect_rate'))}</strong></div>
      </div>
      <div class="columns">
        <div>
          <h3>Confusion</h3>
          <table>
            <thead><tr><th>Bucket</th><th>Count</th></tr></thead>
            <tbody>{confusion_html}</tbody>
          </table>
        </div>
        <div>
          <h3>Interesting Samples</h3>
          <table>
            <thead><tr><th>Image</th><th>GT</th><th>Pred</th><th>GT #</th><th>Pred #</th><th>Latency</th><th>FPS</th></tr></thead>
            <tbody>{_sample_table_rows(per_sample)}</tbody>
          </table>
        </div>
      </div>
      <div class="gallery">
        <h3>Overlay Comparison</h3>
        {_sample_cards_html(sample_cards, assets_rel)}
      </div>
    </section>
    """


def _collect_result_paths(args: argparse.Namespace) -> list[Path]:
    result_paths = [Path(value).resolve() for value in args.result_json]
    if args.results_dir:
        result_paths.extend(sorted(Path(args.results_dir).resolve().glob("*.json")))
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in result_paths:
        if path.name == "manifest.json":
            continue
        if path not in seen:
            seen.add(path)
            deduped.append(path)
    if not deduped:
        raise RuntimeError("Please provide result JSON files or --results-dir.")
    return deduped


def _result_map_from_paths(paths: list[Path]) -> dict[str, dict[str, Any]]:
    result_map: dict[str, dict[str, Any]] = {}
    for path in paths:
        payload = _read_json(path)
        summary = payload.get("summary")
        if not isinstance(summary, dict):
            continue
        model_id = summary.get("model_id")
        if not isinstance(model_id, str) or not model_id:
            continue
        result_map[model_id] = payload
    return result_map


def _compare_result_sets(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_summary = left.get("summary") if isinstance(left.get("summary"), dict) else {}
    right_summary = right.get("summary") if isinstance(right.get("summary"), dict) else {}
    left_rows = {
        str(row["image"]): row
        for row in left.get("per_sample", [])
        if isinstance(row, dict) and row.get("ok") and isinstance(row.get("image"), str)
    }
    right_rows = {
        str(row["image"]): row
        for row in right.get("per_sample", [])
        if isinstance(row, dict) and row.get("ok") and isinstance(row.get("image"), str)
    }
    shared_images = sorted(set(left_rows) & set(right_rows))

    same_decision = 0
    same_count = 0
    identical_boxes = 0
    score_matches = 0
    top1_ious: list[float] = []
    differing_images: list[dict[str, Any]] = []

    for image in shared_images:
        left_row = left_rows[image]
        right_row = right_rows[image]
        left_decision = left_row.get("pred_decision")
        right_decision = right_row.get("pred_decision")
        left_count = int(left_row.get("pred_count", 0))
        right_count = int(right_row.get("pred_count", 0))
        left_boxes = left_row.get("candidate_bboxes")
        right_boxes = right_row.get("candidate_bboxes")
        left_scores = left_row.get("scores") if isinstance(left_row.get("scores"), list) else []
        right_scores = right_row.get("scores") if isinstance(right_row.get("scores"), list) else []

        if left_decision == right_decision:
            same_decision += 1
        if left_count == right_count:
            same_count += 1
        if left_boxes == right_boxes:
            identical_boxes += 1
        if len(left_scores) == len(right_scores) and all(
            abs(float(lhs) - float(rhs)) < 1e-4 for lhs, rhs in zip(left_scores, right_scores)
        ):
            score_matches += 1

        left_boxes_normalized = left_row.get("candidate_bboxes_normalized") if isinstance(left_row.get("candidate_bboxes_normalized"), list) else []
        right_boxes_normalized = right_row.get("candidate_bboxes_normalized") if isinstance(right_row.get("candidate_bboxes_normalized"), list) else []
        if left_boxes_normalized and right_boxes_normalized:
            top1_ious.append(
                _iou(
                    [float(value) for value in left_boxes_normalized[0]],
                    [float(value) for value in right_boxes_normalized[0]],
                )
            )

        if left_boxes != right_boxes or left_scores != right_scores:
            differing_images.append(
                {
                    "image": image,
                    "left_pred_count": left_count,
                    "right_pred_count": right_count,
                    "left_scores": left_scores[:8],
                    "right_scores": right_scores[:8],
                    "left_decision": left_decision,
                    "right_decision": right_decision,
                }
            )

    sample_count = len(shared_images)
    return {
        "model_id": left_summary.get("model_id"),
        "model_label": left_summary.get("model_label") or right_summary.get("model_label"),
        "samples_compared": sample_count,
        "same_decision_rate": round(same_decision / sample_count, 5) if sample_count else None,
        "same_pred_count_rate": round(same_count / sample_count, 5) if sample_count else None,
        "identical_candidate_boxes_rate": round(identical_boxes / sample_count, 5) if sample_count else None,
        "scores_match_rate": round(score_matches / sample_count, 5) if sample_count else None,
        "top1_left_vs_right_mean_iou": round(float(sum(top1_ious) / len(top1_ious)), 5) if top1_ious else None,
        "left_summary": left_summary,
        "right_summary": right_summary,
        "differing_images": differing_images[:20],
    }


def _compare_results(args: argparse.Namespace) -> int:
    left_paths = _collect_result_paths(
        argparse.Namespace(
            result_json=args.left_result_json,
            results_dir=args.left_results_dir,
        )
    )
    right_paths = _collect_result_paths(
        argparse.Namespace(
            result_json=args.right_result_json,
            results_dir=args.right_results_dir,
        )
    )
    left_map = _result_map_from_paths(left_paths)
    right_map = _result_map_from_paths(right_paths)
    shared_model_ids = sorted(set(left_map) & set(right_map))
    if not shared_model_ids:
        raise RuntimeError("No shared model_id values were found between the left and right result sets.")

    payload = {
        "created_at": time.time(),
        "left_models": sorted(left_map),
        "right_models": sorted(right_map),
        "shared_models": [
            _compare_result_sets(left_map[model_id], right_map[model_id])
            for model_id in shared_model_ids
        ],
    }
    if args.output:
        output_path = Path(args.output).resolve()
        _write_json(output_path, payload)
    print(json.dumps(payload, indent=2))
    return 0


def _render_report(args: argparse.Namespace) -> int:
    bundle_dir = Path(args.bundle).resolve()
    image_dir = bundle_dir / "images"
    manifest_index = _load_manifest_index(bundle_dir)
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    assets_dir = output_path.parent / f"{output_path.stem}_assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    assets_rel = assets_dir.name

    cards: list[str] = []
    for path in _collect_result_paths(args):
        payload = _read_json(path)
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        system = payload.get("system") if isinstance(payload.get("system"), dict) else {}
        per_sample = payload.get("per_sample") if isinstance(payload.get("per_sample"), list) else []
        model_payload = payload.get("model") if isinstance(payload.get("model"), dict) else {}
        title = f"{model_payload.get('label', path.stem)} · {summary.get('runtime', 'runtime')} · threads={summary.get('threads', 'n/a')}"
        sample_cards = _write_sample_assets(
            asset_dir=assets_dir / path.stem,
            image_dir=image_dir,
            manifest_index=manifest_index,
            per_sample=[row for row in per_sample if isinstance(row, dict)],
            limit=args.max_samples,
        )
        cards.append(_card(title, summary, system, [row for row in per_sample if isinstance(row, dict)], sample_cards, f"{assets_rel}/{path.stem}"))

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(args.title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f1e8;
      --panel: #fffdf8;
      --ink: #1f1c18;
      --muted: #6b655d;
      --line: #d9d0c5;
      --accent: #0f766e;
      --accent-soft: #d8f0ec;
    }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Avenir Next", sans-serif;
      background: linear-gradient(180deg, #f2ece0 0%, #f8f5ee 100%);
      color: var(--ink);
    }}
    main {{
      max-width: 1360px;
      margin: 0 auto;
      padding: 32px 24px 48px;
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: 2rem;
    }}
    h3 {{
      margin-top: 24px;
      margin-bottom: 10px;
    }}
    .intro {{
      margin: 0 0 24px;
      color: var(--muted);
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 22px;
      box-shadow: 0 18px 40px rgba(44, 32, 20, 0.06);
      margin-bottom: 24px;
    }}
    .muted {{
      color: var(--muted);
      margin-top: -6px;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px;
      margin: 20px 0 24px;
    }}
    .metrics div {{
      background: var(--accent-soft);
      border-radius: 14px;
      padding: 12px 14px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}
    .metrics span {{
      color: var(--muted);
      font-size: 0.82rem;
    }}
    .metrics strong {{
      font-size: 1.05rem;
    }}
    .columns {{
      display: grid;
      grid-template-columns: 260px 1fr;
      gap: 18px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.92rem;
    }}
    th, td {{
      text-align: left;
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--muted);
    }}
    .gallery {{
      margin-top: 28px;
    }}
    .sample-card {{
      border-top: 1px solid var(--line);
      padding-top: 18px;
      margin-top: 18px;
    }}
    .sample-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: baseline;
      margin-bottom: 6px;
    }}
    .sample-head span {{
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .sample-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      color: var(--muted);
      font-size: 0.88rem;
      margin-bottom: 12px;
    }}
    .sample-images {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    figure {{
      margin: 0;
      background: #f7f3ec;
      border: 1px solid var(--line);
      border-radius: 14px;
      overflow: hidden;
    }}
    figure img {{
      display: block;
      width: 100%;
      height: auto;
      background: #fff;
    }}
    figcaption {{
      padding: 10px 12px;
      font-size: 0.9rem;
      color: var(--muted);
      border-top: 1px solid var(--line);
    }}
    @media (max-width: 980px) {{
      .columns {{
        grid-template-columns: 1fr;
      }}
      .sample-images {{
        grid-template-columns: 1fr;
      }}
      .sample-head {{
        flex-direction: column;
        align-items: flex-start;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(args.title)}</h1>
    <p class="intro">Portable detector bundle report. Each card shows one device/runtime run against the same fixed local reference set.</p>
    {''.join(cards)}
  </main>
</body>
</html>
"""
    output_path.write_text(html)
    print(output_path)
    return 0


def _print_presets() -> int:
    payload = {
        name: {
            "label": preset["label"],
            "description": preset["description"],
            "model_runs": preset["model_runs"],
            "sample_ids_json": preset.get("sample_ids_json"),
            "split_source_run": preset.get("split_source_run"),
        }
        for name, preset in PRESETS.items()
    }
    print(json.dumps(payload, indent=2))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and run portable detector benchmarks across devices.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_presets = subparsers.add_parser("list-presets", help="Print available bundle presets.")
    list_presets.set_defaults(func=lambda args: _print_presets())

    bundle = subparsers.add_parser("bundle", help="Create a portable benchmark bundle with fixed images and model exports.")
    bundle.add_argument("--output", required=True, help="Output directory for the bundle.")
    bundle.add_argument("--preset", choices=sorted(PRESETS), help="Named model/sample preset.")
    bundle.add_argument("--model-run", action="append", help="Explicit run.json path. Can be passed multiple times.")
    bundle.add_argument("--sample-ids-json", help="JSON file with sample IDs, or {'samples': [...]} payload.")
    bundle.add_argument("--split", choices=("train", "val", "test"), help="Load sample IDs from the selected split of the first run.")
    bundle.add_argument("--sample-limit", type=int, default=0, help="Trim the sample set after loading it.")
    bundle.add_argument("--force", action="store_true", help="Replace an existing output directory.")
    bundle.add_argument("--archive", action="store_true", help="Additionally create a .tar.gz archive next to the bundle.")
    bundle.set_defaults(func=_build_bundle)

    run = subparsers.add_parser("run", help="Execute a benchmark bundle on the current machine.")
    run.add_argument("--bundle", required=True, help="Path to a bundle directory created by the bundle subcommand.")
    run.add_argument("--output-dir", required=True, help="Directory to write result JSON files into.")
    run.add_argument("--runtime", choices=("auto", "onnx", "coreml", "ncnn", "rknn", "hailo"), default="auto", help="Inference runtime to use.")
    run.add_argument("--model-id", action="append", help="Limit execution to one or more bundled model IDs.")
    run.add_argument(
        "--hef-model",
        action="append",
        default=[],
        help="Map a bundled model_id to a HEF path for --runtime hailo. Format: model_id=/path/to/model.hef",
    )
    run.add_argument(
        "--rknn-model",
        action="append",
        default=[],
        help="Map a bundled model_id to an RKNN path for --runtime rknn. Format: model_id=/path/to/model.rknn",
    )
    run.add_argument("--threads", type=int, default=max(1, os.cpu_count() or 1), help="Inference thread count.")
    run.add_argument("--warmup", type=int, default=3, help="Warmup iterations on the first sample.")
    run.add_argument("--repeat", type=int, default=1, help="Measured inferences per sample. The reported latency is averaged.")
    run.add_argument("--conf", type=float, help="Override confidence threshold.")
    run.add_argument("--iou", type=float, help="Override NMS IoU threshold.")
    run.add_argument("--tag", help="Short device tag used in output filenames. Defaults to the hostname.")
    run.set_defaults(func=_run_bundle)

    report = subparsers.add_parser("report", help="Render an HTML comparison report from result JSON files.")
    report.add_argument("--bundle", required=True, help="Path to the benchmark bundle directory.")
    report.add_argument("--output", required=True, help="HTML output file.")
    report.add_argument("--results-dir", help="Directory containing result JSON files.")
    report.add_argument("result_json", nargs="*", help="One or more result JSON files.")
    report.add_argument("--title", default="Device Detector Benchmark Report")
    report.add_argument("--max-samples", type=int, default=12, help="Number of overlay cards to render per result.")
    report.set_defaults(func=_render_report)

    compare = subparsers.add_parser("compare", help="Compare two result sets and report how closely they match.")
    compare.add_argument("--left-results-dir", help="Directory containing the left-side result JSON files.")
    compare.add_argument("--right-results-dir", help="Directory containing the right-side result JSON files.")
    compare.add_argument("--left-result-json", nargs="*", default=[], help="Explicit left-side result JSON files.")
    compare.add_argument("--right-result-json", nargs="*", default=[], help="Explicit right-side result JSON files.")
    compare.add_argument("--output", help="Optional JSON output path.")
    compare.set_defaults(func=_compare_results)

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
