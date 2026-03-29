from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local exported detector model on a saved classification sample.")
    parser.add_argument("--input", required=True, help="Input image path")
    parser.add_argument("--model", required=True, help="Exported detector model path (e.g. ONNX)")
    parser.add_argument("--result-json", required=True, help="Where to write the result JSON")
    parser.add_argument("--overlay-image", required=True, help="Where to write the overlay image")
    parser.add_argument("--imgsz", type=int, default=640, help="Inference image size")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold")
    parser.add_argument("--iou", type=float, default=0.45, help="NMS IoU threshold")
    return parser.parse_args()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def _load_model_metadata(model_path: Path) -> dict[str, Any]:
    run_json = model_path.parent.parent / "run.json"
    payload = _read_json(run_json)
    return payload if payload is not None else {}


def _resolve_anchor_boxes(metadata: dict[str, Any], model_path: Path) -> np.ndarray:
    inference = metadata.get("inference") if isinstance(metadata.get("inference"), dict) else {}
    anchor_boxes_value = inference.get("anchor_boxes")
    if not isinstance(anchor_boxes_value, str) or not anchor_boxes_value:
        training = metadata.get("training") if isinstance(metadata.get("training"), dict) else {}
        anchor_boxes_value = training.get("anchor_boxes")
    if not isinstance(anchor_boxes_value, str) or not anchor_boxes_value:
        raise RuntimeError("EfficientDet run metadata is missing anchor_boxes.")
    anchor_boxes_path = Path(anchor_boxes_value)
    if not anchor_boxes_path.is_absolute():
        anchor_boxes_path = (model_path.parent.parent / anchor_boxes_path).resolve()
    if not anchor_boxes_path.exists():
        raise RuntimeError(f"EfficientDet anchor_boxes file not found: {anchor_boxes_path}")
    return np.load(anchor_boxes_path)


def _draw_overlay(
    image: np.ndarray,
    candidate_bboxes: list[list[int]],
    scores: list[float],
    *,
    label_prefix: str,
) -> np.ndarray:
    overlay = image.copy()
    for index, bbox in enumerate(candidate_bboxes, start=1):
        x_min, y_min, x_max, y_max = bbox
        cv2.rectangle(overlay, (x_min, y_min), (x_max, y_max), (148, 87, 235), 2)
        score = scores[index - 1] if index - 1 < len(scores) else None
        label = f"{label_prefix} {index}"
        if score is not None:
            label = f"{label} {score:.2f}"
        cv2.putText(
            overlay,
            label,
            (x_min, max(18, y_min - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (148, 87, 235),
            2,
            lineType=cv2.LINE_AA,
        )
    return overlay


def _run_yolo(
    *,
    image_path: Path,
    model_path: Path,
    overlay_image: Path,
    imgsz: int,
    conf: float,
    iou: float,
) -> dict[str, Any]:
    from ultralytics import YOLO

    model = YOLO(str(model_path), task="detect")
    results = model.predict(
        source=str(image_path),
        imgsz=imgsz,
        conf=conf,
        iou=iou,
        device="cpu",
        verbose=False,
    )
    if not results:
        raise RuntimeError("Local detector produced no prediction result.")

    result = results[0]
    plotted = result.plot()
    overlay_image.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(overlay_image), plotted)

    candidate_bboxes: list[list[int]] = []
    scores: list[float] = []
    if result.boxes is not None and result.boxes.xyxy is not None:
        xyxy = result.boxes.xyxy.cpu().numpy().tolist()
        confs = result.boxes.conf.cpu().numpy().tolist() if result.boxes.conf is not None else []
        for index, bbox in enumerate(xyxy):
            candidate_bboxes.append([int(round(value)) for value in bbox[:4]])
            score = float(confs[index]) if index < len(confs) else 0.0
            scores.append(score)

    best_bbox = candidate_bboxes[0] if candidate_bboxes else None
    best_score = scores[0] if scores else None
    return {
        "ok": True,
        "model_path": str(model_path),
        "image": str(image_path),
        "bbox": best_bbox,
        "candidate_bboxes": candidate_bboxes,
        "bbox_count": len(candidate_bboxes),
        "found": bool(candidate_bboxes),
        "score": best_score,
        "scores": scores,
        "overlay_image": str(overlay_image),
    }


def _run_effdet(
    *,
    image_path: Path,
    model_path: Path,
    overlay_image: Path,
    metadata: dict[str, Any],
    imgsz: int,
    conf: float,
) -> dict[str, Any]:
    import onnxruntime as ort

    inference = metadata.get("inference") if isinstance(metadata.get("inference"), dict) else {}
    mean = inference.get("mean") if isinstance(inference.get("mean"), list) else [0.485, 0.456, 0.406]
    std = inference.get("std") if isinstance(inference.get("std"), list) else [0.229, 0.224, 0.225]
    anchors_meta = inference.get("anchors") if isinstance(inference.get("anchors"), dict) else {}
    nms_iou = float(anchors_meta.get("nms_iou_threshold", 0.5))
    max_det = int(anchors_meta.get("max_det_per_image", 100))
    anchor_boxes = _resolve_anchor_boxes(metadata, model_path)
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Could not read input image: {image_path}")

    original_h, original_w = image.shape[:2]
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb, (imgsz, imgsz), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
    normalized = (resized - np.asarray(mean, dtype=np.float32)) / np.asarray(std, dtype=np.float32)
    model_input = np.transpose(normalized, (2, 0, 1))[None, ...].astype(np.float32)

    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: model_input})
    if not outputs:
        raise RuntimeError("EfficientDet ONNX model returned no outputs.")
    if len(outputs) != 4:
        raise RuntimeError(f"Unexpected EfficientDet ONNX output count: {len(outputs)}")

    cls_topk, box_topk, anchor_indices, classes = outputs
    if cls_topk.ndim != 3 or box_topk.ndim != 3 or anchor_indices.ndim != 2 or classes.ndim != 2:
        raise RuntimeError(
            "Unexpected EfficientDet pre-NMS output shapes: "
            f"{cls_topk.shape}, {box_topk.shape}, {anchor_indices.shape}, {classes.shape}"
        )

    logits = cls_topk[0, :, 0].astype(np.float32)
    scores_all = 1.0 / (1.0 + np.exp(-logits))
    regressions = box_topk[0].astype(np.float32)
    selected_indices = anchor_indices[0].astype(np.int64)
    class_ids = classes[0].astype(np.int64)
    selected_anchors = anchor_boxes[selected_indices]

    ycenter_a = (selected_anchors[:, 0] + selected_anchors[:, 2]) / 2.0
    xcenter_a = (selected_anchors[:, 1] + selected_anchors[:, 3]) / 2.0
    ha = selected_anchors[:, 2] - selected_anchors[:, 0]
    wa = selected_anchors[:, 3] - selected_anchors[:, 1]

    ty = regressions[:, 0]
    tx = regressions[:, 1]
    th = regressions[:, 2]
    tw = regressions[:, 3]
    widths = np.exp(tw) * wa
    heights = np.exp(th) * ha
    ycenter = ty * ha + ycenter_a
    xcenter = tx * wa + xcenter_a
    x_min_all = np.clip(xcenter - widths / 2.0, 0.0, float(imgsz))
    y_min_all = np.clip(ycenter - heights / 2.0, 0.0, float(imgsz))
    x_max_all = np.clip(xcenter + widths / 2.0, 0.0, float(imgsz))
    y_max_all = np.clip(ycenter + heights / 2.0, 0.0, float(imgsz))
    boxes_xyxy = np.stack([x_min_all, y_min_all, x_max_all, y_max_all], axis=1)

    valid_mask = (scores_all >= conf) & (class_ids >= 0)
    boxes_xyxy = boxes_xyxy[valid_mask]
    scores_all = scores_all[valid_mask]
    class_ids = class_ids[valid_mask]

    def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
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
            inter_w = np.maximum(0.0, xx2 - xx1)
            inter_h = np.maximum(0.0, yy2 - yy1)
            inter = inter_w * inter_h
            area_i = np.maximum(0.0, boxes[i, 2] - boxes[i, 0]) * np.maximum(0.0, boxes[i, 3] - boxes[i, 1])
            area_rest = np.maximum(0.0, boxes[rest, 2] - boxes[rest, 0]) * np.maximum(0.0, boxes[rest, 3] - boxes[rest, 1])
            union = area_i + area_rest - inter
            ious = np.divide(inter, union, out=np.zeros_like(inter), where=union > 0.0)
            order = rest[ious <= iou_threshold]
        return keep

    kept_global: list[int] = []
    for class_id in sorted(set(int(value) for value in class_ids.tolist())):
        class_mask = class_ids == class_id
        class_indices = np.nonzero(class_mask)[0]
        kept_local = nms(boxes_xyxy[class_indices], scores_all[class_indices], nms_iou)
        kept_global.extend(class_indices[index] for index in kept_local)
    kept_global = sorted(kept_global, key=lambda index: float(scores_all[index]), reverse=True)[:max_det]

    scale_x = float(original_w) / float(imgsz)
    scale_y = float(original_h) / float(imgsz)
    candidate_bboxes: list[list[int]] = []
    scores: list[float] = []
    for index in kept_global:
        box = boxes_xyxy[index]
        x_min = max(0, min(original_w, int(round(float(box[0]) * scale_x))))
        y_min = max(0, min(original_h, int(round(float(box[1]) * scale_y))))
        x_max = max(0, min(original_w, int(round(float(box[2]) * scale_x))))
        y_max = max(0, min(original_h, int(round(float(box[3]) * scale_y))))
        if x_max <= x_min or y_max <= y_min:
            continue
        candidate_bboxes.append([x_min, y_min, x_max, y_max])
        scores.append(float(scores_all[index]))

    overlay = _draw_overlay(image, candidate_bboxes, scores, label_prefix="EffDet")
    overlay_image.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(overlay_image), overlay)

    best_bbox = candidate_bboxes[0] if candidate_bboxes else None
    best_score = scores[0] if scores else None
    return {
        "ok": True,
        "model_path": str(model_path),
        "image": str(image_path),
        "bbox": best_bbox,
        "candidate_bboxes": candidate_bboxes,
        "bbox_count": len(candidate_bboxes),
        "found": bool(candidate_bboxes),
        "score": best_score,
        "scores": scores,
        "overlay_image": str(overlay_image),
    }


def main() -> int:
    args = _parse_args()
    image_path = Path(args.input).resolve()
    model_path = Path(args.model).resolve()
    result_json = Path(args.result_json).resolve()
    overlay_image = Path(args.overlay_image).resolve()

    if not image_path.exists():
        raise FileNotFoundError(f"Input image not found: {image_path}")
    if not model_path.exists():
        raise FileNotFoundError(f"Local detector model not found: {model_path}")

    metadata = _load_model_metadata(model_path)
    model_family = metadata.get("model_family")
    if not isinstance(model_family, str):
        model_family = metadata.get("runtime")
    if model_family == "efficientdet":
        payload = _run_effdet(
            image_path=image_path,
            model_path=model_path,
            overlay_image=overlay_image,
            metadata=metadata,
            imgsz=args.imgsz,
            conf=args.conf,
        )
    else:
        payload = _run_yolo(
            image_path=image_path,
            model_path=model_path,
            overlay_image=overlay_image,
            imgsz=args.imgsz,
            conf=args.conf,
            iou=args.iou,
        )
    _write_json(result_json, payload)
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        raise
