"""Turn a pulled Hive dump into a YOLO-format detection dataset.

Input:  ``datasets/<zone>/raw/`` — produced by ``train pull``.
Output: ``datasets/<zone>/<name>/`` with:

    data.yaml
    images/train/<sample_id>.jpg
    images/val/<sample_id>.jpg
    labels/train/<sample_id>.txt        # one YOLO line per bbox
    labels/val/<sample_id>.txt

YOLO label format per line: ``<class_idx> <cx_norm> <cy_norm> <w_norm> <h_norm>``
with coordinates normalized to [0, 1] against the image's own width/height.

Detection bboxes come from the Hive sample's ``detection_bboxes`` list. Accepted
samples without bboxes are skipped. Negative samples (no pieces) can be included
by passing ``--keep-empty`` — their label file stays empty.

Single-class ``piece`` for now; multi-class can be layered on later by mapping
the per-bbox class label from manual annotations.
"""

from __future__ import annotations

import hashlib
import json
import random
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml
from PIL import Image

from training import DATASETS_DIR


@dataclass(frozen=True)
class _LabeledSample:
    sample_id: str
    image_path: Path
    width: int
    height: int
    boxes: tuple[tuple[float, float, float, float], ...]
    source_role: str | None


def _read_manifest(raw_dir: Path) -> list[dict[str, Any]]:
    manifest_path = raw_dir / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit(f"manifest not found at {manifest_path}. Run `train pull` first.")
    return json.loads(manifest_path.read_text())


def _load_sample(entry: dict[str, Any], raw_dir: Path) -> _LabeledSample | None:
    sample_id = entry["id"]
    sample_dir = raw_dir / sample_id
    image_path = sample_dir / "image.jpg"
    if not image_path.exists():
        return None
    try:
        with Image.open(image_path) as img:
            width, height = img.size
    except Exception as exc:
        print(f"  skip {sample_id}: image unreadable ({exc})", file=sys.stderr)
        return None

    boxes: list[tuple[float, float, float, float]] = []
    for bbox in entry.get("detection_bboxes") or []:
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            continue
        try:
            x1, y1, x2, y2 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        except (TypeError, ValueError):
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        x1 = max(0.0, min(float(width), x1))
        y1 = max(0.0, min(float(height), y1))
        x2 = max(0.0, min(float(width), x2))
        y2 = max(0.0, min(float(height), y2))
        if x2 <= x1 or y2 <= y1:
            continue
        boxes.append((x1, y1, x2, y2))

    return _LabeledSample(
        sample_id=sample_id,
        image_path=image_path,
        width=width,
        height=height,
        boxes=tuple(boxes),
        source_role=entry.get("source_role"),
    )


def _write_yolo_label(label_path: Path, sample: _LabeledSample) -> None:
    lines: list[str] = []
    for x1, y1, x2, y2 in sample.boxes:
        cx = ((x1 + x2) / 2.0) / sample.width
        cy = ((y1 + y2) / 2.0) / sample.height
        w = (x2 - x1) / sample.width
        h = (y2 - y1) / sample.height
        lines.append(f"0 {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    label_path.parent.mkdir(parents=True, exist_ok=True)
    label_path.write_text("\n".join(lines) + ("\n" if lines else ""))


def _copy_image(src: Path, dst: Path, *, link: bool) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    if link:
        try:
            dst.symlink_to(src.resolve())
            return
        except OSError:
            pass
    shutil.copy2(src, dst)


def _deterministic_shuffle(items: list[Any], *, seed: int) -> None:
    rng = random.Random(seed)
    rng.shuffle(items)


def _apply_diversity_sampling(
    samples: list[_LabeledSample],
    *,
    target_size: int,
    model_weights: str,
) -> tuple[list[_LabeledSample], dict[str, Any]]:
    """Select ``target_size`` most-diverse samples via YOLO-embedding FPS."""
    from training.datasets.diversity import (
        MIN_FOR_FPS,
        embed_images,
        farthest_point_sample,
        summarize_selection,
    )

    n_total = len(samples)
    if n_total < MIN_FOR_FPS:
        return samples, {
            "applied": False,
            "reason": f"{n_total} < MIN_FOR_FPS ({MIN_FOR_FPS})",
        }

    image_paths = [s.image_path for s in samples]
    embeddings = embed_images(image_paths, model_weights=model_weights)
    selected_indices = farthest_point_sample(embeddings, target_size)
    stats = summarize_selection(embeddings, selected_indices)

    selected_samples = [samples[i] for i in selected_indices]
    print(
        f"  diversity: kept {len(selected_samples)}/{n_total} "
        f"(min_pairwise={stats.get('min_pairwise'):.3f} "
        f"mean_pairwise={stats.get('mean_pairwise'):.3f})"
        if stats.get("min_pairwise") is not None
        else f"  diversity: kept {len(selected_samples)}/{n_total}",
        file=sys.stderr,
    )
    return selected_samples, {
        "applied": True,
        "model_weights": model_weights,
        "source_samples": n_total,
        "target_size": target_size,
        "spread_stats": stats,
    }


def run(
    *,
    zone: str,
    train_ratio: float = 0.85,
    name: str | None = None,
    keep_empty: bool = False,
    seed: int = 42,
    symlink_images: bool = True,
    target_size: int | None = None,
    embed_model: str = "yolo11n.pt",
    raw_dir: Path | None = None,
    output_dir: Path | None = None,
) -> int:
    """Entry called from the CLI."""
    if not 0.5 <= train_ratio <= 0.99:
        raise SystemExit("--split must be between 0.5 and 0.99")

    raw_dir = (raw_dir or (DATASETS_DIR / zone / "raw")).resolve()
    if not raw_dir.exists():
        raise SystemExit(f"{raw_dir} is missing. Run `train pull --zone {zone}` first.")

    dataset_name = name or "v1"
    out_dir = (output_dir or (DATASETS_DIR / zone / dataset_name)).resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)

    manifest = _read_manifest(raw_dir)
    samples: list[_LabeledSample] = []
    skipped_no_boxes = 0
    for entry in manifest:
        sample = _load_sample(entry, raw_dir)
        if sample is None:
            continue
        if not sample.boxes and not keep_empty:
            skipped_no_boxes += 1
            continue
        samples.append(sample)

    if not samples:
        raise SystemExit(
            f"No usable samples found in {raw_dir}. "
            f"(skipped {skipped_no_boxes} without bboxes; pass --keep-empty to include them.)"
        )

    diversity_info: dict[str, Any] = {"applied": False}
    if target_size is not None and target_size < len(samples):
        samples, diversity_info = _apply_diversity_sampling(
            samples,
            target_size=target_size,
            model_weights=embed_model,
        )
    elif target_size is not None and target_size >= len(samples):
        diversity_info = {
            "applied": False,
            "reason": f"target_size={target_size} >= available samples ({len(samples)})",
        }

    _deterministic_shuffle(samples, seed=seed)
    split_idx = max(1, int(round(len(samples) * train_ratio)))
    if split_idx >= len(samples):
        split_idx = max(1, len(samples) - 1)
    train_samples = samples[:split_idx]
    val_samples = samples[split_idx:]

    for split_name, split_samples in (("train", train_samples), ("val", val_samples)):
        images_dir = out_dir / "images" / split_name
        labels_dir = out_dir / "labels" / split_name
        images_dir.mkdir(parents=True, exist_ok=True)
        labels_dir.mkdir(parents=True, exist_ok=True)
        for sample in split_samples:
            _copy_image(
                sample.image_path,
                images_dir / f"{sample.sample_id}.jpg",
                link=symlink_images,
            )
            _write_yolo_label(labels_dir / f"{sample.sample_id}.txt", sample)

    data_yaml = {
        "path": str(out_dir),
        "train": "images/train",
        "val": "images/val",
        "names": ["piece"],
        "nc": 1,
    }
    (out_dir / "data.yaml").write_text(yaml.safe_dump(data_yaml, sort_keys=False))

    build_metadata = {
        "zone": zone,
        "dataset_name": dataset_name,
        "source_manifest": str(raw_dir.relative_to(out_dir.parent)),
        "seed": seed,
        "train_ratio": train_ratio,
        "train_samples": len(train_samples),
        "val_samples": len(val_samples),
        "skipped_no_boxes": skipped_no_boxes,
        "classes": ["piece"],
        "sample_fingerprint": hashlib.sha256(
            (",".join(sorted(s.sample_id for s in samples))).encode()
        ).hexdigest()[:16],
        "diversity": diversity_info,
    }
    (out_dir / "build.json").write_text(json.dumps(build_metadata, indent=2, sort_keys=True))

    print(
        f"Built dataset {out_dir}\n"
        f"  train={len(train_samples)} val={len(val_samples)} "
        f"skipped_no_boxes={skipped_no_boxes}",
        file=sys.stderr,
    )
    return 0
