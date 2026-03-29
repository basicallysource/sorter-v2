from __future__ import annotations

import argparse
import json
import math
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

from local_detector_dataset import (
    TRAINING_ROOT,
    PreparedSample,
    collect_samples,
    dataset_stats,
    materialize_split_images,
    parse_segmentation_label,
    polygon_to_bbox,
    prepare_run_dir,
    split_samples,
    write_manifest,
)


CLIENT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = CLIENT_ROOT / "blob" / "local_detection_models"
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


@dataclass(frozen=True)
class DatasetItem:
    sample: PreparedSample
    dataset_image: Path
    split: str


class ChamberEffDetDataset(Dataset[tuple[torch.Tensor, dict[str, Any]]]):
    def __init__(
        self,
        items: list[DatasetItem],
        *,
        imgsz: int,
        mean: tuple[float, float, float],
        std: tuple[float, float, float],
    ) -> None:
        self._items = items
        self._imgsz = imgsz
        self._mean = torch.tensor(mean, dtype=torch.float32).view(3, 1, 1)
        self._std = torch.tensor(std, dtype=torch.float32).view(3, 1, 1)

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, dict[str, Any]]:
        item = self._items[index]
        image = cv2.imread(str(item.dataset_image), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Could not read dataset image: {item.dataset_image}")
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(image, (self._imgsz, self._imgsz), interpolation=cv2.INTER_LINEAR)
        image_tensor = torch.from_numpy(resized).permute(2, 0, 1).float() / 255.0
        image_tensor = (image_tensor - self._mean) / self._std

        polygons = parse_segmentation_label(item.sample.segmentation_label_path)
        boxes = []
        for polygon in polygons:
            x_min, y_min, x_max, y_max = polygon_to_bbox(polygon)
            boxes.append(
                [
                    x_min * self._imgsz,
                    y_min * self._imgsz,
                    x_max * self._imgsz,
                    y_max * self._imgsz,
                ]
            )
        bbox = torch.tensor(boxes, dtype=torch.float32) if boxes else torch.zeros((0, 4), dtype=torch.float32)
        cls = torch.ones((len(boxes),), dtype=torch.int64) if boxes else torch.zeros((0,), dtype=torch.int64)
        target = {
            "bbox": bbox,
            "cls": cls,
            "img_scale": torch.tensor(1.0, dtype=torch.float32),
            "img_size": torch.tensor([self._imgsz, self._imgsz], dtype=torch.float32),
            "sample_id": item.sample.sample_id,
        }
        return image_tensor, target


class EffDetExportWrapper(nn.Module):
    def __init__(
        self,
        model: nn.Module,
        *,
        num_levels: int,
        num_classes: int,
        max_detection_points: int,
    ) -> None:
        super().__init__()
        self.model = model
        self.num_levels = int(num_levels)
        self.num_classes = int(num_classes)
        self.max_detection_points = int(max_detection_points)

    def forward(self, images: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        from effdet.bench import _post_process

        class_out, box_out = self.model(images)
        cls_topk, box_topk, indices, classes = _post_process(
            class_out,
            box_out,
            num_levels=self.num_levels,
            num_classes=self.num_classes,
            max_detection_points=self.max_detection_points,
        )
        return cls_topk, box_topk, indices, classes


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Train an EfficientDet-Lite style local detector on classification-chamber samples and export "
            "it to ONNX for Raspberry Pi deployment."
        )
    )
    parser.add_argument("--training-root", default=str(TRAINING_ROOT))
    parser.add_argument("--output-root", default=str(OUTPUT_ROOT))
    parser.add_argument("--name", default="classification-chamber-effdet-lite-detector")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--val-fraction", type=float, default=0.15)
    parser.add_argument("--test-fraction", type=float, default=0.10)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--model-name", default="tf_efficientdet_lite0")
    parser.add_argument("--imgsz", type=int, default=320)
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--match-threshold", type=float, default=0.5)
    parser.add_argument("--no-export-onnx", action="store_true")
    parser.add_argument("--skip-onnx-verify", action="store_true")
    args = parser.parse_args()
    if args.val_fraction < 0 or args.test_fraction < 0:
        parser.error("Split fractions must be non-negative.")
    if (args.val_fraction + args.test_fraction) >= 1.0:
        parser.error("Validation + test fraction must be below 1.0.")
    if args.limit < 0:
        parser.error("--limit must be >= 0.")
    if args.imgsz <= 0:
        parser.error("--imgsz must be > 0.")
    if args.epochs <= 0:
        parser.error("--epochs must be > 0.")
    if args.batch_size <= 0:
        parser.error("--batch-size must be > 0.")
    if args.lr <= 0:
        parser.error("--lr must be > 0.")
    if args.workers < 0:
        parser.error("--workers must be >= 0.")
    return args


def _write_coco_annotations(
    dataset_root: Path,
    *,
    split_name: str,
    items: list[DatasetItem],
) -> dict[str, Any]:
    images_payload: list[dict[str, Any]] = []
    annotations_payload: list[dict[str, Any]] = []
    annotation_id = 1
    for image_id, item in enumerate(items, start=1):
        image = cv2.imread(str(item.dataset_image), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Could not read dataset image for COCO export: {item.dataset_image}")
        height, width = image.shape[:2]
        images_payload.append(
            {
                "id": image_id,
                "file_name": str(item.dataset_image.relative_to(dataset_root)),
                "width": width,
                "height": height,
            }
        )
        polygons = parse_segmentation_label(item.sample.segmentation_label_path)
        for polygon in polygons:
            x_min, y_min, x_max, y_max = polygon_to_bbox(polygon)
            x = x_min * width
            y = y_min * height
            w = max(0.0, (x_max - x_min) * width)
            h = max(0.0, (y_max - y_min) * height)
            annotations_payload.append(
                {
                    "id": annotation_id,
                    "image_id": image_id,
                    "category_id": 1,
                    "bbox": [x, y, w, h],
                    "area": w * h,
                    "iscrowd": 0,
                }
            )
            annotation_id += 1

    payload = {
        "images": images_payload,
        "annotations": annotations_payload,
        "categories": [{"id": 1, "name": "piece"}],
    }
    annotations_dir = dataset_root / "annotations"
    annotations_dir.mkdir(parents=True, exist_ok=True)
    path = annotations_dir / f"{split_name}.json"
    path.write_text(json.dumps(payload, indent=2))
    return {
        "path": str(path),
        "image_count": len(images_payload),
        "annotation_count": len(annotations_payload),
    }


def _prepare_dataset(run_dir: Path, splits: dict[str, list[PreparedSample]]) -> tuple[dict[str, Any], dict[str, list[DatasetItem]]]:
    manifest_path = run_dir / "manifest.jsonl"
    dataset_root, manifest_records = materialize_split_images(run_dir, splits)
    items_by_split: dict[str, list[DatasetItem]] = {"train": [], "val": [], "test": []}

    for record in manifest_records:
        split_name = str(record["split"])
        sample = PreparedSample(
            session_id=str(record["session_id"]),
            sample_id=str(record["sample_id"]),
            source=str(record["source"]),
            capture_reason=str(record["capture_reason"]) if record["capture_reason"] is not None else None,
            captured_at=float(record["captured_at"]) if record["captured_at"] is not None else None,
            image_path=Path(str(record["image_path"])),
            segmentation_label_path=Path(str(record["segmentation_label_path"])),
            detection_count=int(record["detection_count"]),
            metadata_path=Path(str(record["metadata_path"])),
        )
        item = DatasetItem(
            sample=sample,
            dataset_image=Path(str(record["dataset_image"])),
            split=split_name,
        )
        items_by_split[split_name].append(item)

    coco = {
        split_name: _write_coco_annotations(dataset_root, split_name=split_name, items=items)
        for split_name, items in items_by_split.items()
    }
    write_manifest(manifest_path, manifest_records)
    return (
        {
            "dataset_root": str(dataset_root),
            "manifest_path": str(manifest_path),
            "coco_annotations": coco,
        },
        items_by_split,
    )


def _collate_batch(batch: list[tuple[torch.Tensor, dict[str, Any]]]) -> tuple[torch.Tensor, dict[str, Any]]:
    images = torch.stack([image for image, _ in batch], dim=0)
    targets = {
        "bbox": [target["bbox"] for _, target in batch],
        "cls": [target["cls"] for _, target in batch],
        "img_scale": torch.stack([target["img_scale"] for _, target in batch]),
        "img_size": torch.stack([target["img_size"] for _, target in batch]),
        "sample_id": [target["sample_id"] for _, target in batch],
    }
    return images, targets


def _select_device(value: str) -> torch.device:
    if value != "auto":
        return torch.device(value)
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def _move_targets(targets: dict[str, Any], device: torch.device) -> dict[str, Any]:
    return {
        "bbox": [tensor.to(device) for tensor in targets["bbox"]],
        "cls": [tensor.to(device) for tensor in targets["cls"]],
        "img_scale": targets["img_scale"].to(device),
        "img_size": targets["img_size"].to(device),
        "sample_id": list(targets["sample_id"]),
    }


def _build_model(args: argparse.Namespace) -> tuple[nn.Module, Any]:
    from effdet import create_model
    from effdet.anchors import AnchorLabeler

    model = create_model(
        args.model_name,
        bench_task="train",
        num_classes=1,
        pretrained=True,
        image_size=(args.imgsz, args.imgsz),
    )
    model.anchor_labeler = AnchorLabeler(model.anchors, num_classes=1, match_threshold=args.match_threshold)
    return model, model.config


def _evaluate_loss(model: nn.Module, loader: DataLoader[Any], device: torch.device) -> dict[str, float]:
    model.eval()
    total_loss = 0.0
    total_class_loss = 0.0
    total_box_loss = 0.0
    batches = 0
    with torch.no_grad():
        for images, targets in loader:
            images = images.to(device)
            moved_targets = _move_targets(targets, device)
            output = model(images, moved_targets)
            total_loss += float(output["loss"].detach().cpu())
            total_class_loss += float(output["class_loss"].detach().cpu())
            total_box_loss += float(output["box_loss"].detach().cpu())
            batches += 1
    if batches == 0:
        return {"loss": math.inf, "class_loss": math.inf, "box_loss": math.inf}
    return {
        "loss": total_loss / batches,
        "class_loss": total_class_loss / batches,
        "box_loss": total_box_loss / batches,
    }


def _iou(box_a: np.ndarray, box_b: np.ndarray) -> float:
    x_min = max(box_a[0], box_b[0])
    y_min = max(box_a[1], box_b[1])
    x_max = min(box_a[2], box_b[2])
    y_max = min(box_a[3], box_b[3])
    inter_w = max(0.0, x_max - x_min)
    inter_h = max(0.0, y_max - y_min)
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    area_a = max(0.0, (box_a[2] - box_a[0])) * max(0.0, (box_a[3] - box_a[1]))
    area_b = max(0.0, (box_b[2] - box_b[0])) * max(0.0, (box_b[3] - box_b[1]))
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _count_metrics(model: nn.Module, loader: DataLoader[Any], *, device: torch.device, conf: float) -> dict[str, Any]:
    model.eval()
    samples = 0
    exact_count_match = 0
    empty_correct = 0
    single_correct = 0
    multi_correct = 0
    single_iou_values: list[float] = []

    with torch.no_grad():
        for images, targets in loader:
            images = images.to(device)
            moved_targets = _move_targets(targets, device)
            output = model(images, moved_targets)
            detections = output.get("detections")
            if detections is None:
                continue
            detections_np = detections.detach().cpu().numpy()
            gt_boxes_batch = [boxes.detach().cpu().numpy() for boxes in moved_targets["bbox"]]
            for predicted, gt_boxes in zip(detections_np, gt_boxes_batch):
                pred_boxes = [row[:4] for row in predicted if float(row[4]) >= conf and float(row[5]) >= 1.0]
                gt_count = int(len(gt_boxes))
                pred_count = int(len(pred_boxes))
                samples += 1
                if pred_count == gt_count:
                    exact_count_match += 1
                if gt_count == 0 and pred_count == 0:
                    empty_correct += 1
                elif gt_count == 1 and pred_count == 1:
                    single_correct += 1
                    single_iou_values.append(_iou(np.asarray(pred_boxes[0]), gt_boxes[0]))
                elif gt_count > 1 and pred_count == gt_count:
                    multi_correct += 1

    return {
        "samples": samples,
        "exact_count_match_rate": (exact_count_match / samples) if samples else 0.0,
        "empty_correct": empty_correct,
        "single_exact_count": single_correct,
        "multi_exact_count": multi_correct,
        "single_mean_iou": (sum(single_iou_values) / len(single_iou_values)) if single_iou_values else None,
        "confidence_threshold": conf,
    }


def _copy_if_exists(src: Path, dst: Path) -> str | None:
    if not src.exists() or not src.is_file():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return str(dst)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _save_anchor_boxes(run_dir: Path, anchor_boxes: torch.Tensor) -> str:
    exports_dir = run_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    path = exports_dir / "anchors.npy"
    np.save(path, anchor_boxes.detach().cpu().numpy())
    return str(path)


def _load_base_model(args: argparse.Namespace, weights_path: Path) -> nn.Module:
    from effdet import create_model

    base_model = create_model(
        args.model_name,
        bench_task="",
        num_classes=1,
        pretrained=False,
        image_size=(args.imgsz, args.imgsz),
    )
    state = torch.load(weights_path, map_location="cpu")
    raw_state_dict = state.get("state_dict") if isinstance(state, dict) and isinstance(state.get("state_dict"), dict) else state
    state_dict: dict[str, Any] = {}
    if not isinstance(raw_state_dict, dict):
        raise RuntimeError(f"Unexpected EfficientDet checkpoint format in {weights_path}")
    for key, value in raw_state_dict.items():
        if key == "anchors.boxes":
            continue
        if key.startswith("model."):
            state_dict[key[len("model."):]] = value
        else:
            state_dict[key] = value
    missing, unexpected = base_model.load_state_dict(state_dict, strict=False)
    if missing:
        print(f"Warning: missing state keys during base-model load: {missing}")
    if unexpected:
        print(f"Warning: unexpected state keys during base-model load: {unexpected}")
    base_model.eval()
    return base_model


def _verify_onnx(model_path: Path, *, imgsz: int) -> dict[str, Any]:
    import onnxruntime as ort

    session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    dummy = np.zeros((1, 3, imgsz, imgsz), dtype=np.float32)
    outputs = session.run(None, {input_name: dummy})
    return {
        "input_name": input_name,
        "output_shapes": [list(output.shape) for output in outputs],
        "output_names": [output.name for output in session.get_outputs()],
    }


def _train_model(
    run_dir: Path,
    args: argparse.Namespace,
    dataset_items: dict[str, list[DatasetItem]],
) -> dict[str, Any]:
    train_dataset = ChamberEffDetDataset(dataset_items["train"], imgsz=args.imgsz, mean=IMAGENET_MEAN, std=IMAGENET_STD)
    val_dataset = ChamberEffDetDataset(dataset_items["val"], imgsz=args.imgsz, mean=IMAGENET_MEAN, std=IMAGENET_STD)
    test_dataset = ChamberEffDetDataset(dataset_items["test"], imgsz=args.imgsz, mean=IMAGENET_MEAN, std=IMAGENET_STD)
    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, num_workers=args.workers, collate_fn=_collate_batch)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False, num_workers=args.workers, collate_fn=_collate_batch)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size, shuffle=False, num_workers=args.workers, collate_fn=_collate_batch)

    device = _select_device(args.device)
    model, config = _build_model(args)
    model.to(device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(args.epochs, 1))
    exports_dir = run_dir / "exports"
    checkpoints_dir = run_dir / "train"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    best_loss = math.inf
    history: list[dict[str, Any]] = []

    for epoch in range(1, args.epochs + 1):
        model.train()
        train_loss = 0.0
        train_class_loss = 0.0
        train_box_loss = 0.0
        batches = 0
        for images, targets in train_loader:
            images = images.to(device)
            moved_targets = _move_targets(targets, device)
            optimizer.zero_grad(set_to_none=True)
            output = model(images, moved_targets)
            loss = output["loss"]
            loss.backward()
            optimizer.step()
            train_loss += float(loss.detach().cpu())
            train_class_loss += float(output["class_loss"].detach().cpu())
            train_box_loss += float(output["box_loss"].detach().cpu())
            batches += 1

        scheduler.step()
        val_metrics = _evaluate_loss(model, val_loader, device)
        epoch_summary = {
            "epoch": epoch,
            "train_loss": train_loss / batches if batches else math.inf,
            "train_class_loss": train_class_loss / batches if batches else math.inf,
            "train_box_loss": train_box_loss / batches if batches else math.inf,
            "val_loss": val_metrics["loss"],
            "val_class_loss": val_metrics["class_loss"],
            "val_box_loss": val_metrics["box_loss"],
            "lr": float(optimizer.param_groups[0]["lr"]),
        }
        history.append(epoch_summary)
        print(json.dumps(epoch_summary))

        checkpoint_path = checkpoints_dir / f"epoch-{epoch:03d}.pth"
        torch.save({"state_dict": model.state_dict(), "epoch": epoch, "summary": epoch_summary}, checkpoint_path)
        if val_metrics["loss"] <= best_loss:
            best_loss = val_metrics["loss"]
            _copy_if_exists(checkpoint_path, exports_dir / "best.pth")
        _copy_if_exists(checkpoint_path, exports_dir / "last.pth")

    best_weights = exports_dir / "best.pth"
    last_weights = exports_dir / "last.pth"
    if not best_weights.exists():
        raise RuntimeError("EfficientDet training finished without producing best.pth.")

    test_loss = _evaluate_loss(model, test_loader, device)
    count_metrics = _count_metrics(model, test_loader, device=device, conf=args.conf)
    training_summary: dict[str, Any] = {
        "framework": "effdet_pytorch",
        "model_family": "efficientdet",
        "model_name": args.model_name,
        "device": str(device),
        "config_image_size": list(config.image_size),
        "anchor_boxes": _save_anchor_boxes(run_dir, model.anchors.boxes),
        "anchor_config": {
            "min_level": int(config.min_level),
            "max_level": int(config.max_level),
            "num_scales": int(config.num_scales),
            "aspect_ratios": [list(ratio) for ratio in config.aspect_ratios],
            "anchor_scale": float(config.anchor_scale),
            "max_detection_points": int(config.max_detection_points),
            "max_det_per_image": int(config.max_det_per_image),
            "nms_iou_threshold": 0.5,
        },
        "history": history,
        "best_weights": str(best_weights),
        "last_weights": str(last_weights) if last_weights.exists() else None,
        "test_loss": test_loss,
        "test_count_metrics": count_metrics,
        "onnx_model": None,
        "onnx_verification": None,
    }

    if not args.no_export_onnx:
        base_model = _load_base_model(args, best_weights)
        wrapper = EffDetExportWrapper(
            base_model,
            num_levels=(config.max_level - config.min_level + 1),
            num_classes=1,
            max_detection_points=int(config.max_detection_points),
        )
        wrapper.eval()
        dummy = torch.zeros((1, 3, args.imgsz, args.imgsz), dtype=torch.float32)
        onnx_path = exports_dir / "best.onnx"
        torch.onnx.export(
            wrapper,
            dummy,
            str(onnx_path),
            input_names=["images"],
            output_names=["cls_topk", "box_topk", "anchor_indices", "classes"],
            opset_version=17,
            dynamo=False,
        )
        training_summary["onnx_model"] = str(onnx_path)
        if not args.skip_onnx_verify:
            training_summary["onnx_verification"] = _verify_onnx(onnx_path, imgsz=args.imgsz)

    return training_summary


def _write_run_summary(
    summary_path: Path,
    *,
    args: argparse.Namespace,
    sample_count: int,
    skipped: dict[str, int],
    splits: dict[str, list[PreparedSample]],
    dataset_paths: dict[str, Any],
    training: dict[str, Any] | None,
) -> None:
    training_anchor_config = training.get("anchor_config") if isinstance(training, dict) and isinstance(training.get("anchor_config"), dict) else None
    training_anchor_boxes = training.get("anchor_boxes") if isinstance(training, dict) and isinstance(training.get("anchor_boxes"), str) else None
    payload = {
        "created_at": time.time(),
        "run_name": args.name,
        "runtime": "onnx",
        "model_family": "efficientdet",
        "training_root": str(Path(args.training_root).resolve()),
        "sample_count": sample_count,
        "skipped_samples": skipped,
        "splits": {name: dataset_stats(items) for name, items in splits.items()},
        "dataset": dataset_paths,
        "train_args": {
            "prepare_only": args.prepare_only,
            "model_name": args.model_name,
            "imgsz": args.imgsz,
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "lr": args.lr,
            "weight_decay": args.weight_decay,
            "workers": args.workers,
            "device": args.device,
            "seed": args.seed,
            "val_fraction": args.val_fraction,
            "test_fraction": args.test_fraction,
            "limit": args.limit,
            "conf": args.conf,
            "match_threshold": args.match_threshold,
            "export_onnx": not args.no_export_onnx,
        },
        "inference": {
            "backend": "onnxruntime",
            "family": "efficientdet",
            "imgsz": args.imgsz,
            "mean": list(IMAGENET_MEAN),
            "std": list(IMAGENET_STD),
            "score_threshold": args.conf,
            "output_format": "pre_nms_topk",
            "anchors": training_anchor_config,
            "anchor_boxes": training_anchor_boxes,
        },
        "training": training,
    }
    summary_path.write_text(json.dumps(_jsonable(payload), indent=2))


def main() -> int:
    args = _parse_args()
    training_root = Path(args.training_root).resolve()
    output_root = Path(args.output_root).resolve()
    if not training_root.exists():
        raise SystemExit(f"Training root does not exist: {training_root}")

    accepted, skipped = collect_samples(training_root, limit=args.limit, seed=args.seed)
    if not accepted:
        raise SystemExit("No valid classification-chamber samples with completed pseudo-labels were found.")

    run_dir = prepare_run_dir(output_root, args.name)
    splits = split_samples(
        accepted,
        val_fraction=args.val_fraction,
        test_fraction=args.test_fraction,
        seed=args.seed,
    )
    dataset_paths, dataset_items = _prepare_dataset(run_dir, splits)

    summary_path = run_dir / "run.json"
    training_summary: dict[str, Any] | None = None
    training_error: str | None = None
    if not args.prepare_only:
        try:
            training_summary = _train_model(run_dir, args, dataset_items)
        except Exception as exc:
            training_error = str(exc)

    _write_run_summary(
        summary_path,
        args=args,
        sample_count=len(accepted),
        skipped=skipped,
        splits=splits,
        dataset_paths=dataset_paths,
        training=(
            training_summary
            if training_error is None
            else {
                "error": training_error,
                "partial": training_summary,
            }
        ),
    )

    if training_error is not None:
        raise SystemExit(
            f"Dataset prepared at {run_dir}, but EfficientDet training failed: {training_error}. "
            f"See {summary_path} for the run manifest."
        )

    output = {
        "ok": True,
        "run_dir": str(run_dir),
        "run_summary": str(summary_path),
        "sample_count": len(accepted),
        "prepared_only": bool(args.prepare_only),
        "training": training_summary,
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
