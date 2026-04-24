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
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml
from PIL import Image

from training import DATASETS_DIR


DEFAULT_PIECE_COUNT_BINS = "0,1,2,3,4,5,6,7,8,9-12,13+"


@dataclass(frozen=True)
class _LabeledSample:
    sample_id: str
    image_path: Path
    width: int
    height: int
    boxes: tuple[tuple[float, float, float, float], ...]
    source_role: str | None
    detection_score: float | None


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
        detection_score=(
            float(entry["detection_score"])
            if isinstance(entry.get("detection_score"), (int, float))
            and not isinstance(entry.get("detection_score"), bool)
            else None
        ),
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


def _allocate_balanced_quotas(group_sizes: dict[str, int], target_size: int) -> dict[str, int]:
    """Allocate a near-even target across groups, capped by group availability."""
    quotas = {group: 0 for group in group_sizes}
    remaining_capacity = dict(group_sizes)
    remaining = min(target_size, sum(group_sizes.values()))

    while remaining > 0:
        available_groups = [
            group for group, capacity in remaining_capacity.items() if capacity > quotas[group]
        ]
        if not available_groups:
            break
        base, extra = divmod(remaining, len(available_groups))
        if base == 0:
            for group in sorted(available_groups)[:extra]:
                quotas[group] += 1
            break

        assigned = 0
        for group in sorted(available_groups):
            capacity_left = remaining_capacity[group] - quotas[group]
            take = min(capacity_left, base + (1 if extra > 0 else 0))
            if extra > 0:
                extra -= 1
            quotas[group] += take
            assigned += take

        if assigned == 0:
            break
        remaining -= assigned

    return quotas


def _strict_balance_shortages(group_sizes: dict[str, int], target_size: int) -> dict[str, int]:
    """Return the per-group sample shortage for a strict equal split."""
    if not group_sizes:
        return {}
    fair_quota = target_size // len(group_sizes)
    if target_size % len(group_sizes):
        fair_quota += 1
    return {
        group: fair_quota - size
        for group, size in sorted(group_sizes.items())
        if size < fair_quota
    }


def _piece_count_bucket(piece_count: int, bins: str) -> str:
    for raw_token in bins.split(","):
        token = raw_token.strip()
        if not token:
            continue
        if token.endswith("+"):
            lower = int(token[:-1])
            if piece_count >= lower:
                return token
            continue
        if "-" in token:
            lower_str, upper_str = token.split("-", 1)
            lower = int(lower_str)
            upper = int(upper_str)
            if lower <= piece_count <= upper:
                return token
            continue
        if piece_count == int(token):
            return token
    return str(piece_count)


def _balance_group_label(
    sample: _LabeledSample,
    *,
    balance_source_role: bool,
    balance_piece_count: bool,
    piece_count_bins: str,
) -> str:
    parts: list[str] = []
    if balance_source_role:
        parts.append(f"source_role={sample.source_role or 'unknown'}")
    if balance_piece_count:
        bucket = _piece_count_bucket(len(sample.boxes), piece_count_bins)
        parts.append(f"pieces={bucket}")
    return " | ".join(parts) if parts else "all"


def _select_group_subset(
    samples: list[_LabeledSample],
    *,
    target_size: int,
    model_weights: str,
    seed: int,
) -> tuple[list[_LabeledSample], dict[str, Any]]:
    if target_size <= 0:
        return [], {
            "applied": False,
            "reason": "target_size <= 0",
            "source_samples": len(samples),
            "target_size": target_size,
        }
    if target_size >= len(samples):
        return samples, {
            "applied": False,
            "reason": f"target_size={target_size} >= available samples ({len(samples)})",
        }

    from training.datasets.diversity import (
        MIN_FOR_FPS,
        embed_images,
        farthest_point_sample,
        summarize_selection,
    )

    if len(samples) < MIN_FOR_FPS:
        shuffled = list(samples)
        _deterministic_shuffle(shuffled, seed=seed)
        return shuffled[:target_size], {
            "applied": False,
            "reason": f"{len(samples)} < MIN_FOR_FPS ({MIN_FOR_FPS}); used deterministic shuffle",
            "source_samples": len(samples),
            "target_size": target_size,
        }

    image_paths = [s.image_path for s in samples]
    embeddings = embed_images(image_paths, model_weights=model_weights)
    selected_indices = farthest_point_sample(embeddings, target_size)
    stats = summarize_selection(embeddings, selected_indices)
    return [samples[i] for i in selected_indices], {
        "applied": True,
        "model_weights": model_weights,
        "source_samples": len(samples),
        "target_size": target_size,
        "spread_stats": stats,
    }


def _apply_balanced_diversity_sampling(
    samples: list[_LabeledSample],
    *,
    target_size: int,
    model_weights: str,
    seed: int,
    strict: bool,
    balance_source_role: bool,
    balance_piece_count: bool,
    piece_count_bins: str,
) -> tuple[list[_LabeledSample], dict[str, Any]]:
    grouped: dict[str, list[_LabeledSample]] = defaultdict(list)
    for sample in samples:
        grouped[
            _balance_group_label(
                sample,
                balance_source_role=balance_source_role,
                balance_piece_count=balance_piece_count,
                piece_count_bins=piece_count_bins,
            )
        ].append(sample)

    group_sizes = {group: len(group_samples) for group, group_samples in grouped.items()}
    shortages = _strict_balance_shortages(group_sizes, target_size)
    if strict and shortages:
        details = ", ".join(
            f"{group} needs {missing} more samples" for group, missing in shortages.items()
        )
        raise SystemExit(
            "Cannot build a strictly balanced dataset: "
            f"{details}. Add more accepted samples for those balance groups "
            "or lower --target-size."
        )

    quotas = _allocate_balanced_quotas(group_sizes, target_size)
    selected: list[_LabeledSample] = []
    group_info: dict[str, Any] = {}

    for group in sorted(grouped):
        quota = quotas.get(group, 0)
        group_samples = grouped[group]
        chosen, info = _select_group_subset(
            group_samples,
            target_size=quota,
            model_weights=model_weights,
            seed=seed,
        )
        selected.extend(chosen)
        group_info[group] = {
            "available": len(group_samples),
            "selected": len(chosen),
            "selection": info,
        }

    print(
        "  balance groups: "
        + ", ".join(
            f"{group}={group_info[group]['selected']}/{group_info[group]['available']}"
            for group in sorted(group_info)
        ),
        file=sys.stderr,
    )

    return selected, {
        "applied": True,
        "strategy": "equal_quota_by_balance_group_then_diversity",
        "balance_source_role": balance_source_role,
        "balance_piece_count": balance_piece_count,
        "piece_count_bins": piece_count_bins if balance_piece_count else None,
        "model_weights": model_weights,
        "source_samples": len(samples),
        "target_size": target_size,
        "selected": len(selected),
        "strict": strict,
        "strict_shortages": shortages,
        "groups": group_info,
    }


def _source_role_counts(samples: Iterable[_LabeledSample]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sample in samples:
        role = sample.source_role or "unknown"
        counts[role] = counts.get(role, 0) + 1
    return dict(sorted(counts.items()))


def _piece_count_counts(samples: Iterable[_LabeledSample], *, bins: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sample in samples:
        bucket = _piece_count_bucket(len(sample.boxes), bins)
        counts[bucket] = counts.get(bucket, 0) + 1
    return dict(sorted(counts.items()))


def _balance_group_counts(
    samples: Iterable[_LabeledSample],
    *,
    balance_source_role: bool,
    balance_piece_count: bool,
    piece_count_bins: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sample in samples:
        group = _balance_group_label(
            sample,
            balance_source_role=balance_source_role,
            balance_piece_count=balance_piece_count,
            piece_count_bins=piece_count_bins,
        )
        counts[group] = counts.get(group, 0) + 1
    return dict(sorted(counts.items()))


def _split_samples(
    samples: list[_LabeledSample],
    *,
    train_ratio: float,
    seed: int,
    stratify_balance_groups: bool,
    balance_source_role: bool,
    balance_piece_count: bool,
    piece_count_bins: str,
) -> tuple[list[_LabeledSample], list[_LabeledSample]]:
    if not stratify_balance_groups:
        shuffled = list(samples)
        _deterministic_shuffle(shuffled, seed=seed)
        split_idx = max(1, int(round(len(shuffled) * train_ratio)))
        if split_idx >= len(shuffled):
            split_idx = max(1, len(shuffled) - 1)
        return shuffled[:split_idx], shuffled[split_idx:]

    grouped: dict[str, list[_LabeledSample]] = defaultdict(list)
    for sample in samples:
        grouped[
            _balance_group_label(
                sample,
                balance_source_role=balance_source_role,
                balance_piece_count=balance_piece_count,
                piece_count_bins=piece_count_bins,
            )
        ].append(sample)

    train_samples: list[_LabeledSample] = []
    val_samples: list[_LabeledSample] = []
    for group_index, group in enumerate(sorted(grouped)):
        group_samples = list(grouped[group])
        _deterministic_shuffle(group_samples, seed=seed + group_index)
        if len(group_samples) == 1:
            train_samples.extend(group_samples)
            continue
        split_idx = max(1, int(round(len(group_samples) * train_ratio)))
        if split_idx >= len(group_samples):
            split_idx = max(1, len(group_samples) - 1)
        train_samples.extend(group_samples[:split_idx])
        val_samples.extend(group_samples[split_idx:])

    if not val_samples and len(train_samples) > 1:
        val_samples.append(train_samples.pop())

    _deterministic_shuffle(train_samples, seed=seed)
    _deterministic_shuffle(val_samples, seed=seed + 1)
    return train_samples, val_samples


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
    balance_source_role: bool = False,
    balance_piece_count: bool = False,
    piece_count_bins: str = DEFAULT_PIECE_COUNT_BINS,
    strict_source_role_balance: bool = False,
    min_detection_score: float | None = None,
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
    skipped_low_score = 0
    skipped_missing_score = 0
    for entry in manifest:
        sample = _load_sample(entry, raw_dir)
        if sample is None:
            continue
        if min_detection_score is not None and sample.boxes:
            if sample.detection_score is None:
                skipped_missing_score += 1
                continue
            if sample.detection_score < min_detection_score:
                skipped_low_score += 1
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
        if balance_source_role or balance_piece_count:
            samples, diversity_info = _apply_balanced_diversity_sampling(
                samples,
                target_size=target_size,
                model_weights=embed_model,
                seed=seed,
                strict=strict_source_role_balance,
                balance_source_role=balance_source_role,
                balance_piece_count=balance_piece_count,
                piece_count_bins=piece_count_bins,
            )
        else:
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

    train_samples, val_samples = _split_samples(
        samples,
        train_ratio=train_ratio,
        seed=seed,
        stratify_balance_groups=balance_source_role or balance_piece_count,
        balance_source_role=balance_source_role,
        balance_piece_count=balance_piece_count,
        piece_count_bins=piece_count_bins,
    )

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
        "skipped_low_score": skipped_low_score,
        "skipped_missing_score": skipped_missing_score,
        "min_detection_score": min_detection_score,
        "classes": ["piece"],
        "balance_source_role": balance_source_role,
        "balance_piece_count": balance_piece_count,
        "piece_count_bins": piece_count_bins if balance_piece_count else None,
        "strict_balance": strict_source_role_balance,
        "strict_source_role_balance": strict_source_role_balance,
        "source_role_counts": {
            "selected": _source_role_counts(samples),
            "train": _source_role_counts(train_samples),
            "val": _source_role_counts(val_samples),
        },
        "piece_count_counts": {
            "selected": _piece_count_counts(samples, bins=piece_count_bins),
            "train": _piece_count_counts(train_samples, bins=piece_count_bins),
            "val": _piece_count_counts(val_samples, bins=piece_count_bins),
        },
        "balance_group_counts": {
            "selected": _balance_group_counts(
                samples,
                balance_source_role=balance_source_role,
                balance_piece_count=balance_piece_count,
                piece_count_bins=piece_count_bins,
            ),
            "train": _balance_group_counts(
                train_samples,
                balance_source_role=balance_source_role,
                balance_piece_count=balance_piece_count,
                piece_count_bins=piece_count_bins,
            ),
            "val": _balance_group_counts(
                val_samples,
                balance_source_role=balance_source_role,
                balance_piece_count=balance_piece_count,
                piece_count_bins=piece_count_bins,
            ),
        },
        "sample_fingerprint": hashlib.sha256(
            (",".join(sorted(s.sample_id for s in samples))).encode()
        ).hexdigest()[:16],
        "diversity": diversity_info,
    }
    (out_dir / "build.json").write_text(json.dumps(build_metadata, indent=2, sort_keys=True))

    print(
        f"Built dataset {out_dir}\n"
        f"  train={len(train_samples)} val={len(val_samples)} "
        f"skipped_no_boxes={skipped_no_boxes} "
        f"skipped_low_score={skipped_low_score} "
        f"skipped_missing_score={skipped_missing_score}",
        file=sys.stderr,
    )
    return 0
