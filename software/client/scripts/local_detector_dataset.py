from __future__ import annotations

import json
import random
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


CLIENT_ROOT = Path(__file__).resolve().parents[1]
TRAINING_ROOT = CLIENT_ROOT / "blob" / "classification_training"


@dataclass(frozen=True)
class PreparedSample:
    session_id: str
    sample_id: str
    source: str
    capture_reason: str | None
    captured_at: float | None
    image_path: Path
    segmentation_label_path: Path
    detection_count: int
    metadata_path: Path


def slugify(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value.strip())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    cleaned = cleaned.strip("-")
    return cleaned or "detector-run"


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def parse_segmentation_label(path: Path) -> list[list[tuple[float, float]]]:
    polygons: list[list[tuple[float, float]]] = []
    raw = path.read_text().strip()
    if not raw:
        return polygons
    for line in raw.splitlines():
        tokens = line.strip().split()
        if len(tokens) < 7:
            raise ValueError(f"Malformed segmentation label line in {path.name}: '{line}'")
        coords = tokens[1:]
        if len(coords) % 2 != 0:
            raise ValueError(f"Odd coordinate count in {path.name}: '{line}'")
        polygon: list[tuple[float, float]] = []
        for idx in range(0, len(coords), 2):
            x = float(coords[idx])
            y = float(coords[idx + 1])
            polygon.append((x, y))
        if len(polygon) < 3:
            raise ValueError(f"Polygon in {path.name} has fewer than 3 points.")
        polygons.append(polygon)
    return polygons


def polygon_to_bbox(polygon: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    x_min = max(0.0, min(xs))
    y_min = max(0.0, min(ys))
    x_max = min(1.0, max(xs))
    y_max = min(1.0, max(ys))
    return x_min, y_min, x_max, y_max


def polygon_to_detect_label(polygon: list[tuple[float, float]]) -> str:
    x_min, y_min, x_max, y_max = polygon_to_bbox(polygon)
    width = max(0.0, x_max - x_min)
    height = max(0.0, y_max - y_min)
    x_center = x_min + width / 2.0
    y_center = y_min + height / 2.0
    return f"0 {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}"


def sample_from_metadata(metadata_path: Path) -> tuple[PreparedSample | None, str | None]:
    metadata = read_json(metadata_path)
    if metadata is None:
        return None, "invalid_metadata"
    if metadata.get("source_role") != "classification_chamber":
        return None, "wrong_source_role"
    if metadata.get("detection_scope") != "classification":
        return None, "wrong_scope"

    sample_id = metadata.get("sample_id")
    if not isinstance(sample_id, str) or not sample_id:
        return None, "missing_sample_id"

    distill_result = metadata.get("distill_result")
    if not isinstance(distill_result, dict):
        return None, "missing_distill_result"

    input_image = metadata.get("input_image")
    yolo_label = distill_result.get("yolo_label")
    if not isinstance(input_image, str) or not input_image:
        return None, "missing_input_image"
    if not isinstance(yolo_label, str) or not yolo_label:
        return None, "missing_yolo_label"

    image_path = Path(input_image)
    label_path = Path(yolo_label)
    if not image_path.exists() or not image_path.is_file():
        return None, "missing_image_file"
    if not label_path.exists() or not label_path.is_file():
        return None, "missing_label_file"

    try:
        polygons = parse_segmentation_label(label_path)
    except Exception:
        return None, "invalid_label_file"

    declared_detections = distill_result.get("detections")
    if isinstance(declared_detections, int) and declared_detections != len(polygons):
        return None, "detection_count_mismatch"

    session_id = metadata_path.parent.parent.name
    return (
        PreparedSample(
            session_id=session_id,
            sample_id=sample_id,
            source=metadata.get("source") if isinstance(metadata.get("source"), str) else "unknown",
            capture_reason=(
                metadata.get("capture_reason")
                if isinstance(metadata.get("capture_reason"), str)
                else None
            ),
            captured_at=(
                float(metadata["captured_at"])
                if isinstance(metadata.get("captured_at"), (int, float))
                else None
            ),
            image_path=image_path,
            segmentation_label_path=label_path,
            detection_count=len(polygons),
            metadata_path=metadata_path,
        ),
        None,
    )


def collect_samples(training_root: Path, *, limit: int, seed: int) -> tuple[list[PreparedSample], dict[str, int]]:
    accepted: list[PreparedSample] = []
    skipped: dict[str, int] = {}
    for metadata_path in sorted(training_root.glob("*/metadata/*.json")):
        sample, reason = sample_from_metadata(metadata_path)
        if sample is None:
            if reason is not None:
                skipped[reason] = skipped.get(reason, 0) + 1
            continue
        accepted.append(sample)

    rng = random.Random(seed)
    rng.shuffle(accepted)
    if limit > 0:
        accepted = accepted[:limit]
    accepted.sort(key=lambda sample: sample.captured_at or 0.0)
    return accepted, skipped


def bucket_key(sample: PreparedSample) -> str:
    if sample.detection_count <= 0:
        return "negative"
    if sample.detection_count == 1:
        return "single"
    return "multi"


def split_counts(count: int, val_fraction: float, test_fraction: float) -> tuple[int, int]:
    if count <= 1:
        return 0, 0
    val_count = int(round(count * val_fraction))
    test_count = int(round(count * test_fraction))
    if val_fraction > 0 and val_count == 0 and count >= 3:
        val_count = 1
    if test_fraction > 0 and test_count == 0 and count >= 5:
        test_count = 1
    while val_count + test_count >= count:
        if test_count > val_count and test_count > 0:
            test_count -= 1
        elif val_count > 0:
            val_count -= 1
        else:
            break
    return val_count, test_count


def split_samples(
    samples: list[PreparedSample],
    *,
    val_fraction: float,
    test_fraction: float,
    seed: int,
) -> dict[str, list[PreparedSample]]:
    buckets: dict[str, list[PreparedSample]] = {"negative": [], "single": [], "multi": []}
    for sample in samples:
        buckets[bucket_key(sample)].append(sample)

    rng = random.Random(seed)
    splits: dict[str, list[PreparedSample]] = {"train": [], "val": [], "test": []}
    for bucket_samples in buckets.values():
        rng.shuffle(bucket_samples)
        val_count, test_count = split_counts(len(bucket_samples), val_fraction, test_fraction)
        train_count = len(bucket_samples) - val_count - test_count
        splits["train"].extend(bucket_samples[:train_count])
        splits["val"].extend(bucket_samples[train_count:train_count + val_count])
        splits["test"].extend(bucket_samples[train_count + val_count:])

    for split_samples in splits.values():
        split_samples.sort(key=lambda sample: sample.captured_at or 0.0)
    return splits


def link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.hardlink_to(src)
    except Exception:
        shutil.copy2(src, dst)


def dataset_stats(samples: list[PreparedSample]) -> dict[str, int]:
    stats = {
        "samples": len(samples),
        "negative_samples": 0,
        "single_piece_samples": 0,
        "multi_piece_samples": 0,
        "total_objects": 0,
    }
    for sample in samples:
        stats["total_objects"] += sample.detection_count
        if sample.detection_count <= 0:
            stats["negative_samples"] += 1
        elif sample.detection_count == 1:
            stats["single_piece_samples"] += 1
        else:
            stats["multi_piece_samples"] += 1
    return stats


def prepare_run_dir(output_root: Path, name: str) -> Path:
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = output_root / f"{timestamp}-{slugify(name)}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def materialize_split_images(
    run_dir: Path,
    splits: dict[str, list[PreparedSample]],
    *,
    dataset_dir_name: str = "dataset",
) -> tuple[Path, list[dict[str, Any]]]:
    dataset_root = run_dir / dataset_dir_name
    manifest_records: list[dict[str, Any]] = []

    for split_name, samples in splits.items():
        images_dir = dataset_root / "images" / split_name
        images_dir.mkdir(parents=True, exist_ok=True)
        for sample in samples:
            extension = sample.image_path.suffix or ".jpg"
            base_name = f"{sample.session_id}__{sample.sample_id}"
            image_dst = images_dir / f"{base_name}{extension}"
            link_or_copy(sample.image_path, image_dst)
            manifest_records.append(
                {
                    **asdict(sample),
                    "split": split_name,
                    "image_path": str(sample.image_path),
                    "segmentation_label_path": str(sample.segmentation_label_path),
                    "metadata_path": str(sample.metadata_path),
                    "dataset_image": str(image_dst),
                }
            )
    return dataset_root, manifest_records


def write_manifest(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(record, sort_keys=True) for record in records))
