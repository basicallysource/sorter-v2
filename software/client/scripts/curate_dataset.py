#!/usr/bin/env python3
"""Curate maximally diverse training datasets using neural embeddings + farthest point sampling.

Extracts MobileNetV3 embeddings for all sample images per zone, then selects the most
diverse subset using farthest point sampling (greedy k-center).

Usage:
    uv run python scripts/curate_dataset.py                          # analyze all zones
    uv run python scripts/curate_dataset.py --target 1500            # select 1500 per zone
    uv run python scripts/curate_dataset.py --scope feeder --target 800
    uv run python scripts/curate_dataset.py --target 1500 --export   # export curated dataset
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from torchvision import models, transforms

CLIENT_ROOT = Path(__file__).resolve().parents[1]
TRAINING_ROOT = CLIENT_ROOT / "blob" / "classification_training"
CURATED_ROOT = CLIENT_ROOT / "blob" / "curated_datasets"

# Zone mapping from detection_scope/source_role
ZONE_MAP = {
    ("classification", "classification_chamber"): "classification_chamber",
    ("carousel", "carousel"): "carousel",
    ("feeder", "c_channel_2"): "c_channel",
    ("feeder", "c_channel_3"): "c_channel",
}


def get_embedder():
    """Load MobileNetV3-Large as a feature extractor."""
    model = models.mobilenet_v3_large(weights=models.MobileNet_V3_Large_Weights.DEFAULT)
    # Remove classifier, keep feature extractor
    model.classifier = torch.nn.Identity()
    preprocess = transforms.Compose([
        transforms.ToPILImage(),
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    model.eval()
    return model, preprocess


def load_samples() -> dict[str, list[dict[str, Any]]]:
    """Load all completed samples grouped by zone."""
    grouped: dict[str, list[dict[str, Any]]] = {}

    for session_dir in sorted(TRAINING_ROOT.iterdir()):
        if not session_dir.is_dir():
            continue
        metadata_dir = session_dir / "metadata"
        if not metadata_dir.exists():
            continue

        for metadata_path in sorted(metadata_dir.glob("*.json")):
            try:
                metadata = json.loads(metadata_path.read_text())
            except Exception:
                continue
            if not isinstance(metadata, dict):
                continue

            # Only completed samples
            if not isinstance(metadata.get("distill_result"), dict):
                continue

            scope = metadata.get("detection_scope", "unknown")
            role = metadata.get("source_role", "unknown")
            zone = ZONE_MAP.get((scope, role))
            if zone is None:
                continue

            # Find image
            image_path = None
            for field in ("input_image", "top_zone", "bottom_zone"):
                val = metadata.get(field)
                if isinstance(val, str) and val:
                    candidate = Path(val)
                    if not candidate.is_absolute():
                        candidate = session_dir / val
                    if candidate.exists():
                        image_path = candidate
                        break
            if image_path is None:
                continue

            # Find YOLO label
            distill = metadata.get("distill_result", {})
            yolo_label = None
            if isinstance(distill, dict):
                val = distill.get("yolo_label")
                if isinstance(val, str) and val:
                    p = Path(val)
                    if not p.is_absolute():
                        p = session_dir / val
                    if p.exists():
                        yolo_label = p

            sample_id = metadata_path.stem
            grouped.setdefault(zone, []).append({
                "sample_id": sample_id,
                "session_dir": session_dir,
                "metadata_path": metadata_path,
                "image_path": image_path,
                "yolo_label_path": yolo_label,
                "metadata": metadata,
            })

    return grouped


@torch.no_grad()
def compute_embeddings(
    samples: list[dict[str, Any]],
    model: torch.nn.Module,
    preprocess: transforms.Compose,
    batch_size: int = 32,
) -> np.ndarray:
    """Compute normalized embeddings for all sample images."""
    embeddings = []
    total = len(samples)

    for batch_start in range(0, total, batch_size):
        batch_end = min(batch_start + batch_size, total)
        batch_tensors = []

        for i in range(batch_start, batch_end):
            img = cv2.imread(str(samples[i]["image_path"]))
            if img is None:
                batch_tensors.append(torch.zeros(3, 224, 224))
                continue
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            tensor = preprocess(img_rgb)
            batch_tensors.append(tensor)

        batch = torch.stack(batch_tensors)
        features = model(batch)
        features = F.normalize(features, p=2, dim=1)
        embeddings.append(features.cpu().numpy())

        done = batch_end
        print(f"\r  Embedding: {done}/{total}", end="", flush=True)

    print()
    return np.concatenate(embeddings, axis=0)


def farthest_point_sampling(
    embeddings: np.ndarray,
    target_size: int,
    seed: int = 42,
) -> list[int]:
    """Select target_size indices maximizing minimum pairwise distance (greedy k-center)."""
    n = embeddings.shape[0]
    if target_size >= n:
        return list(range(n))

    rng = np.random.RandomState(seed)
    selected: list[int] = [rng.randint(0, n)]

    # Distance from each point to nearest selected point (cosine distance = 1 - dot product)
    min_distances = 1.0 - embeddings @ embeddings[selected[0]]

    for k in range(1, target_size):
        next_idx = int(np.argmax(min_distances))
        selected.append(next_idx)

        new_distances = 1.0 - embeddings @ embeddings[next_idx]
        min_distances = np.minimum(min_distances, new_distances)

        if (k + 1) % 100 == 0 or k + 1 == target_size:
            print(f"\r  Sampling: {k+1}/{target_size}", end="", flush=True)

    print()
    return selected


def analyze_diversity(embeddings: np.ndarray, selected_indices: list[int] | None = None) -> dict[str, float]:
    """Compute diversity metrics for a set of embeddings."""
    if selected_indices is not None:
        emb = embeddings[selected_indices]
    else:
        emb = embeddings

    n = emb.shape[0]
    if n > 2000:
        rng = np.random.RandomState(0)
        idx = rng.choice(n, 2000, replace=False)
        emb_sample = emb[idx]
    else:
        emb_sample = emb

    sim_matrix = emb_sample @ emb_sample.T
    np.fill_diagonal(sim_matrix, 0)
    mask = np.triu(np.ones_like(sim_matrix, dtype=bool), k=1)
    pairwise_sims = sim_matrix[mask]

    return {
        "mean_similarity": float(np.mean(pairwise_sims)),
        "median_similarity": float(np.median(pairwise_sims)),
        "min_similarity": float(np.min(pairwise_sims)),
        "max_similarity": float(np.max(pairwise_sims)),
        "std_similarity": float(np.std(pairwise_sims)),
    }


def export_curated_dataset(
    zone: str,
    samples: list[dict[str, Any]],
    selected_indices: list[int],
    val_ratio: float = 0.1,
) -> Path:
    """Export curated dataset with train/val split."""
    out_dir = CURATED_ROOT / zone
    for sub in ["train/images", "train/labels", "val/images", "val/labels"]:
        (out_dir / sub).mkdir(parents=True, exist_ok=True)

    selected = [samples[i] for i in selected_indices]
    rng = np.random.RandomState(42)
    indices = list(range(len(selected)))
    rng.shuffle(indices)
    selected = [selected[i] for i in indices]

    n_val = max(1, int(len(selected) * val_ratio))
    val_set = selected[:n_val]
    train_set = selected[n_val:]

    for split_name, split_samples in [("train", train_set), ("val", val_set)]:
        for s in split_samples:
            img_src = s["image_path"]
            img_dst = out_dir / split_name / "images" / f"{s['sample_id']}.jpg"
            shutil.copy2(str(img_src), str(img_dst))

            label_src = s.get("yolo_label_path")
            label_dst = out_dir / split_name / "labels" / f"{s['sample_id']}.txt"
            if label_src is not None and label_src.exists():
                shutil.copy2(str(label_src), str(label_dst))
            else:
                label_dst.write_text("")

    (out_dir / "data.yaml").write_text(
        f"path: {out_dir}\ntrain: train/images\nval: val/images\nnames:\n  0: piece\n"
    )
    (out_dir / "classes.txt").write_text("piece\n")

    manifest = {
        "zone": zone,
        "total_available": len(samples),
        "selected": len(selected),
        "train": len(train_set),
        "val": len(val_set),
        "sample_ids": [s["sample_id"] for s in selected],
    }
    (out_dir / "curation_manifest.json").write_text(json.dumps(manifest, indent=2))

    return out_dir


def main():
    parser = argparse.ArgumentParser(description="Curate diverse training datasets")
    parser.add_argument("--target", type=int, default=None, help="Target samples per zone (default: analyze only)")
    parser.add_argument("--scope", type=str, default=None, help="Only process specific scope (feeder, carousel, classification)")
    parser.add_argument("--export", action="store_true", help="Export curated datasets to blob/curated_datasets/")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size for embedding (default: 32)")
    args = parser.parse_args()

    print("Loading samples...")
    grouped = load_samples()

    if args.scope:
        scope_zone_map = {
            "classification": "classification_chamber",
            "carousel": "carousel",
            "feeder": "c_channel",
        }
        target_zone = scope_zone_map.get(args.scope)
        if target_zone:
            grouped = {k: v for k, v in grouped.items() if k == target_zone}

    print(f"Found zones: {', '.join(f'{k} ({len(v)})' for k, v in sorted(grouped.items()))}\n")

    print("Loading MobileNetV3-Large embedder...")
    model, preprocess = get_embedder()

    for zone, samples in sorted(grouped.items()):
        print(f"\n{'='*60}")
        print(f"  Zone: {zone} -- {len(samples)} samples")
        print(f"{'='*60}")

        t0 = time.time()
        embeddings = compute_embeddings(samples, model, preprocess, batch_size=args.batch_size)
        embed_time = time.time() - t0
        print(f"  Embeddings computed in {embed_time:.1f}s ({embeddings.shape})")

        full_metrics = analyze_diversity(embeddings)
        print(f"  Full dataset diversity:")
        print(f"    Mean cosine similarity: {full_metrics['mean_similarity']:.3f}")
        print(f"    Std:  {full_metrics['std_similarity']:.3f}")
        print(f"    Range: [{full_metrics['min_similarity']:.3f}, {full_metrics['max_similarity']:.3f}]")

        if args.target is not None:
            target = min(args.target, len(samples))
            print(f"\n  Selecting {target} most diverse samples...")
            t0 = time.time()
            selected = farthest_point_sampling(embeddings, target)
            fps_time = time.time() - t0
            print(f"  Selection done in {fps_time:.1f}s")

            curated_metrics = analyze_diversity(embeddings, selected)
            print(f"  Curated subset diversity ({target} samples):")
            print(f"    Mean cosine similarity: {curated_metrics['mean_similarity']:.3f}")
            print(f"    Std:  {curated_metrics['std_similarity']:.3f}")
            print(f"    Range: [{curated_metrics['min_similarity']:.3f}, {curated_metrics['max_similarity']:.3f}]")

            improvement = full_metrics['mean_similarity'] - curated_metrics['mean_similarity']
            print(f"    Diversity improvement: {improvement:+.3f} mean similarity (lower = more diverse)")

            if args.export:
                print(f"\n  Exporting curated dataset...")
                out_dir = export_curated_dataset(zone, samples, selected)
                n_train = len(list((out_dir / "train" / "images").iterdir()))
                n_val = len(list((out_dir / "val" / "images").iterdir()))
                print(f"  Exported to {out_dir}")
                print(f"  Train: {n_train}, Val: {n_val}")

    if args.target is not None:
        print(f"\n{'='*60}")
        print(f"Target: {args.target} samples per zone")
        if args.export:
            print(f"Datasets exported to {CURATED_ROOT}")
        else:
            print(f"Re-run with --export to save curated datasets.")


if __name__ == "__main__":
    raise SystemExit(main() or 0)
