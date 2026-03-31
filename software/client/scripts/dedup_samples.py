#!/usr/bin/env python3
"""Find and remove near-duplicate classification training samples using perceptual hashing.

Compares images within each detection_scope/source_role group.
Keeps the first sample in each cluster of duplicates, deletes the rest.

Usage:
    uv run python scripts/dedup_samples.py                  # dry-run: show duplicates
    uv run python scripts/dedup_samples.py --delete         # actually delete duplicates
    uv run python scripts/dedup_samples.py --threshold 8    # adjust similarity (lower = stricter)
    uv run python scripts/dedup_samples.py --scope feeder   # only check feeder samples
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import cv2
import numpy as np

CLIENT_ROOT = Path(__file__).resolve().parents[1]
TRAINING_ROOT = CLIENT_ROOT / "blob" / "classification_training"


def dhash(image: np.ndarray, hash_size: int = 16) -> int:
    """Compute a difference hash (dHash) for an image. Returns an integer."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    resized = cv2.resize(gray, (hash_size + 1, hash_size))
    diff = resized[:, 1:] > resized[:, :-1]
    bits = 0
    for val in diff.flatten():
        bits = (bits << 1) | int(val)
    return bits


def hamming_distance(h1: int, h2: int) -> int:
    return bin(h1 ^ h2).count("1")


def find_duplicates(
    samples: list[dict],
    threshold: int = 6,
) -> list[list[dict]]:
    """Find clusters of near-duplicate samples. Returns list of clusters (each cluster is a list of samples)."""
    n = len(samples)
    if n == 0:
        return []

    # Compute hashes
    for s in samples:
        img = cv2.imread(str(s["image_path"]))
        if img is None:
            s["hash"] = None
            continue
        s["hash"] = dhash(img)

    samples_with_hash = [s for s in samples if s["hash"] is not None]
    used = set()
    clusters: list[list[dict]] = []

    for i, s1 in enumerate(samples_with_hash):
        if i in used:
            continue
        cluster = [s1]
        used.add(i)
        for j in range(i + 1, len(samples_with_hash)):
            if j in used:
                continue
            if hamming_distance(s1["hash"], samples_with_hash[j]["hash"]) <= threshold:
                cluster.append(samples_with_hash[j])
                used.add(j)
        if len(cluster) > 1:
            clusters.append(cluster)

    return clusters


def load_samples(scope_filter: str | None = None) -> dict[str, list[dict]]:
    """Load all samples grouped by scope/role."""
    grouped: dict[str, list[dict]] = {}

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

            scope = metadata.get("detection_scope", "unknown")
            role = metadata.get("source_role", "unknown")
            key = f"{scope}/{role}"

            if scope_filter and scope != scope_filter:
                continue

            # Find the image path
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

            sample_id = metadata_path.stem
            grouped.setdefault(key, []).append({
                "sample_id": sample_id,
                "session_dir": session_dir,
                "metadata_path": metadata_path,
                "image_path": image_path,
                "metadata": metadata,
            })

    return grouped


def delete_sample(sample: dict) -> None:
    """Delete a sample's metadata and associated files."""
    metadata = sample["metadata"]
    session_dir = sample["session_dir"]
    metadata_path = sample["metadata_path"]

    # Collect files to delete
    files_to_delete = [metadata_path]
    for field in ("input_image", "top_zone", "bottom_zone", "top_frame", "bottom_frame"):
        val = metadata.get(field)
        if isinstance(val, str) and val:
            p = Path(val)
            if not p.is_absolute():
                p = session_dir / val
            if p.exists():
                files_to_delete.append(p)

    # Delete distill result files
    distill = metadata.get("distill_result")
    if isinstance(distill, dict):
        for field in ("overlay_image", "result_json", "yolo_label"):
            val = distill.get(field)
            if isinstance(val, str) and val:
                p = Path(val)
                if not p.is_absolute():
                    p = session_dir / val
                if p.exists():
                    files_to_delete.append(p)

    for f in files_to_delete:
        try:
            f.unlink()
        except Exception as e:
            print(f"  Warning: could not delete {f}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Deduplicate classification training samples")
    parser.add_argument("--delete", action="store_true", help="Actually delete duplicates (default: dry run)")
    parser.add_argument("--threshold", type=int, default=6, help="Hamming distance threshold (lower = stricter, default: 6)")
    parser.add_argument("--scope", type=str, default=None, help="Only process specific scope (e.g., feeder, carousel, classification)")
    args = parser.parse_args()

    print(f"Loading samples (scope={args.scope or 'all'})...")
    grouped = load_samples(scope_filter=args.scope)

    total_dupes = 0
    total_kept = 0

    for key, samples in sorted(grouped.items()):
        print(f"\n{'='*60}")
        print(f"  {key}: {len(samples)} samples")
        print(f"{'='*60}")

        clusters = find_duplicates(samples, threshold=args.threshold)
        if not clusters:
            print(f"  No duplicates found.")
            continue

        group_dupes = sum(len(c) - 1 for c in clusters)
        total_dupes += group_dupes
        total_kept += len(clusters)

        print(f"  Found {len(clusters)} duplicate clusters, {group_dupes} samples to remove")

        for ci, cluster in enumerate(clusters):
            keep = cluster[0]
            remove = cluster[1:]
            print(f"\n  Cluster {ci+1}: {len(cluster)} samples (keeping {keep['sample_id']})")
            for r in remove:
                dist = hamming_distance(keep["hash"], r["hash"])
                print(f"    - {r['sample_id']} (distance={dist})")
                if args.delete:
                    delete_sample(r)

    print(f"\n{'='*60}")
    print(f"Summary: {total_dupes} duplicates in {total_kept} clusters")
    if args.delete:
        print(f"Deleted {total_dupes} duplicate samples.")
    else:
        print(f"Dry run — re-run with --delete to remove them.")


if __name__ == "__main__":
    raise SystemExit(main() or 0)
