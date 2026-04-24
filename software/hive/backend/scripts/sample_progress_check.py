#!/usr/bin/env python3
"""Incremental local Hive dataset progress check.

Reads samples from the local Hive database, updates a small per-sample cache,
and writes a timestamped progress snapshot plus an append-only history file.
The intent is a cheap repeated "are we ready yet?" check while collecting data.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ROLES = ("c_channel_2", "c_channel_3", "classification_channel")
DEFAULT_BUCKETS = ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9-12", "13+")
DEFAULT_TARGET_SIZES = (900, 1200, 1500, 1800)
DEFAULT_BUCKET_TARGET = 50
DEFAULT_IMAGE_BUCKET_TARGET = 100


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _default_output_dir() -> Path:
    return _repo_root() / "software" / "training" / "datasets" / "_progress"


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _boxes(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _piece_bucket(piece_count: int) -> str:
    if piece_count <= 8:
        return str(piece_count)
    if piece_count <= 12:
        return "9-12"
    return "13+"


def _image_signature(sample: Any) -> str:
    return "|".join(str(part) for part in (sample.id, sample.image_path))


def _row_signature(sample: Any) -> str:
    return "|".join(
        str(part)
        for part in (
            sample.id,
            sample.review_status,
            sample.review_count,
            sample.accepted_count,
            sample.rejected_count,
            _iso(sample.uploaded_at),
            _iso(sample.resolved_at),
            sample.detection_count,
            sample.detection_score,
            len(_boxes(sample.detection_bboxes)),
            _image_signature(sample),
        )
    )


def _hive_backend_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _image_path(stored_path: str | None) -> Path | None:
    if not stored_path:
        return None
    candidate = (_hive_backend_dir() / "data" / "uploads" / stored_path).resolve()
    try:
        candidate.relative_to((_hive_backend_dir() / "data" / "uploads").resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _image_bucket(value: float, thresholds: tuple[float, float], labels: tuple[str, str, str]) -> str:
    if value < thresholds[0]:
        return labels[0]
    if value < thresholds[1]:
        return labels[1]
    return labels[2]


def _compute_image_metrics(stored_path: str | None) -> dict[str, Any] | None:
    path = _image_path(stored_path)
    if path is None:
        return None

    try:
        from PIL import Image, ImageStat
    except ImportError:
        return None

    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((160, 160))
            gray = img.convert("L")
            stat = ImageStat.Stat(gray)
            mean_gray = float(stat.mean[0])
            std_gray = float(stat.stddev[0])
            gray_hist = gray.histogram()
            total = max(1, sum(gray_hist))
            dark_ratio = sum(gray_hist[:32]) / total
            bright_ratio = sum(gray_hist[225:]) / total
            hsv = img.convert("HSV")
            sat_hist = hsv.getchannel("S").histogram()
            saturated_ratio = sum(sat_hist[97:]) / max(1, sum(sat_hist))
    except Exception:
        return None

    return {
        "mean_gray": round(mean_gray, 3),
        "std_gray": round(std_gray, 3),
        "dark_ratio": round(dark_ratio, 5),
        "bright_ratio": round(bright_ratio, 5),
        "saturated_ratio": round(saturated_ratio, 5),
        "mean_gray_bucket": _image_bucket(
            mean_gray,
            (85.0, 170.0),
            ("dark", "mid", "bright"),
        ),
        "contrast_bucket": _image_bucket(
            std_gray,
            (32.0, 72.0),
            ("low", "mid", "high"),
        ),
        "saturation_bucket": _image_bucket(
            saturated_ratio,
            (0.08, 0.24),
            ("low", "mid", "high"),
        ),
    }


def _normalize_sample(
    sample: Any,
    signature: str,
    *,
    image_metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    bboxes = _boxes(sample.detection_bboxes)
    invalid_boxes: list[dict[str, Any]] = []
    for bbox in bboxes:
        try:
            x1, y1, x2, y2 = map(float, bbox[:4])
            if x2 <= x1 or y2 <= y1:
                invalid_boxes.append({"bbox": bbox, "reason": "non_positive"})
        except Exception:
            invalid_boxes.append({"bbox": bbox, "reason": "bad_shape"})

    return {
        "id": str(sample.id),
        "signature": signature,
        "source_role": sample.source_role,
        "review_status": sample.review_status,
        "capture_reason": sample.capture_reason,
        "captured_at": _iso(sample.captured_at),
        "uploaded_at": _iso(sample.uploaded_at),
        "resolved_at": _iso(sample.resolved_at),
        "image_width": sample.image_width,
        "image_height": sample.image_height,
        "detection_algorithm": sample.detection_algorithm,
        "detection_count": sample.detection_count,
        "detection_score": sample.detection_score,
        "piece_count": len(bboxes),
        "piece_bucket": _piece_bucket(len(bboxes)),
        "invalid_boxes": invalid_boxes,
        "image_metrics": image_metrics,
    }


def _load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"samples": {}}
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return {"samples": {}}
    return payload if isinstance(payload, dict) else {"samples": {}}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _count_by(items: Iterable[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(item.get(key) or "<missing>") for item in items)
    return dict(sorted(counts.items()))


def _image_metric_bucket_counts(
    samples: Iterable[dict[str, Any]],
    *,
    roles: tuple[str, ...],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for role in roles:
        role_samples = [s for s in samples if s.get("source_role") == role]
        metrics_samples = [
            s for s in role_samples if isinstance(s.get("image_metrics"), dict)
        ]
        result[role] = {
            "with_metrics": len(metrics_samples),
            "missing_metrics": len(role_samples) - len(metrics_samples),
            "mean_gray_bucket": _count_by(
                (s["image_metrics"] for s in metrics_samples),
                "mean_gray_bucket",
            ),
            "contrast_bucket": _count_by(
                (s["image_metrics"] for s in metrics_samples),
                "contrast_bucket",
            ),
            "saturation_bucket": _count_by(
                (s["image_metrics"] for s in metrics_samples),
                "saturation_bucket",
            ),
        }
    return result


def _bucket_score(counts: dict[str, int], labels: tuple[str, ...], target: int) -> dict[str, Any]:
    buckets: dict[str, Any] = {}
    score_sum = 0.0
    for label in labels:
        count = counts.get(label, 0)
        coverage = min(1.0, count / target) if target > 0 else 1.0
        score_sum += coverage
        buckets[label] = {
            "accepted_samples": count,
            "target_samples": target,
            "coverage_percent": round(coverage * 100, 1),
            "missing_to_target": max(0, target - count),
        }
    return {
        "score_percent": round((score_sum / len(labels)) * 100, 1),
        "buckets": buckets,
        "missing_buckets": [label for label in labels if counts.get(label, 0) == 0],
    }


def _image_coverage_by_role(
    samples: Iterable[dict[str, Any]],
    *,
    roles: tuple[str, ...],
    target: int,
) -> dict[str, Any]:
    samples_by_role = defaultdict(list)
    for sample in samples:
        if sample.get("review_status") == "accepted" and sample.get("source_role") in roles:
            samples_by_role[str(sample.get("source_role"))].append(sample)

    result: dict[str, Any] = {}
    for role in roles:
        role_samples = samples_by_role[role]
        metric_samples = [
            s for s in role_samples if isinstance(s.get("image_metrics"), dict)
        ]
        mean_counts = Counter(s["image_metrics"].get("mean_gray_bucket") for s in metric_samples)
        contrast_counts = Counter(s["image_metrics"].get("contrast_bucket") for s in metric_samples)
        saturation_counts = Counter(s["image_metrics"].get("saturation_bucket") for s in metric_samples)
        components = {
            "mean_gray": _bucket_score(mean_counts, ("dark", "mid", "bright"), target),
            "contrast": _bucket_score(contrast_counts, ("low", "mid", "high"), target),
            "saturation": _bucket_score(saturation_counts, ("low", "mid", "high"), target),
        }
        result[role] = {
            "score_percent": round(
                sum(component["score_percent"] for component in components.values())
                / len(components),
                1,
            ),
            "bucket_target_samples": target,
            "with_metrics": len(metric_samples),
            "missing_metrics": len(role_samples) - len(metric_samples),
            "components": components,
        }
    return result


def _summarize(
    samples: list[dict[str, Any]],
    *,
    roles: tuple[str, ...],
    target_sizes: tuple[int, ...],
    bucket_target: int,
    image_bucket_target: int,
    min_detection_score: float | None,
) -> dict[str, Any]:
    accepted_unfiltered = [s for s in samples if s.get("review_status") == "accepted"]
    score_filtered_positive = 0
    score_filtered_missing = 0
    accepted: list[dict[str, Any]] = []
    for sample in accepted_unfiltered:
        piece_count = int(sample.get("piece_count") or 0)
        if min_detection_score is not None and piece_count > 0:
            score = sample.get("detection_score")
            if score is None:
                score_filtered_missing += 1
                continue
            try:
                if float(score) < min_detection_score:
                    score_filtered_positive += 1
                    continue
            except Exception:
                score_filtered_missing += 1
                continue
        accepted.append(sample)
    relevant = [s for s in accepted if s.get("source_role") in roles]
    relevant_positive = [s for s in relevant if int(s.get("piece_count") or 0) > 0]
    relevant_empty = [s for s in relevant if int(s.get("piece_count") or 0) == 0]

    role_status: dict[str, Counter[str]] = defaultdict(Counter)
    role_buckets: dict[str, Counter[str]] = defaultdict(Counter)
    role_algorithms: dict[str, Counter[str]] = defaultdict(Counter)
    role_reasons: dict[str, Counter[str]] = defaultdict(Counter)
    invalid_count = 0
    for sample in samples:
        role = str(sample.get("source_role") or "<missing>")
        status = str(sample.get("review_status") or "<missing>")
        role_status[role][status] += 1
        invalid_count += len(sample.get("invalid_boxes") or [])

    for sample in accepted:
        role = str(sample.get("source_role") or "<missing>")
        if role in roles:
            role_buckets[role][str(sample.get("piece_bucket") or "<missing>")] += 1
            role_algorithms[role][str(sample.get("detection_algorithm") or "<missing>")] += 1
            role_reasons[role][str(sample.get("capture_reason") or "<missing>")] += 1

    positive_by_role = {
        role: sum(count for bucket, count in role_buckets[role].items() if bucket != "0")
        for role in roles
    }
    empty_by_role = {role: role_buckets[role].get("0", 0) for role in roles}
    strict_capacity = min(positive_by_role.values()) * len(roles) if roles else 0

    missing_by_target: dict[str, dict[str, int]] = {}
    for target in target_sizes:
        fair_quota = target // len(roles) + (1 if target % len(roles) else 0)
        missing_by_target[str(target)] = {
            role: max(0, fair_quota - positive_by_role.get(role, 0))
            for role in roles
        }

    weak_under_30: list[dict[str, Any]] = []
    weak_under_50: list[dict[str, Any]] = []
    bucket_coverage_by_role: dict[str, Any] = {}
    for role in roles:
        bucket_scores: dict[str, Any] = {}
        score_sum = 0.0
        for bucket in DEFAULT_BUCKETS:
            count = role_buckets[role].get(bucket, 0)
            coverage = min(1.0, count / bucket_target) if bucket_target > 0 else 1.0
            score_sum += coverage
            bucket_scores[bucket] = {
                "accepted_samples": count,
                "target_samples": bucket_target,
                "coverage_percent": round(coverage * 100, 1),
                "missing_to_target": max(0, bucket_target - count),
            }
            entry = {"role": role, "bucket": bucket, "accepted_samples": count}
            if count < 30:
                weak_under_30.append(entry)
            if count < 50:
                weak_under_50.append(entry)
        bucket_coverage_by_role[role] = {
            "score_percent": round((score_sum / len(DEFAULT_BUCKETS)) * 100, 1),
            "bucket_target_samples": bucket_target,
            "buckets": bucket_scores,
            "missing_buckets": [
                bucket
                for bucket in DEFAULT_BUCKETS
                if role_buckets[role].get(bucket, 0) == 0
            ],
        }

    return {
        "totals": {
            "all_samples": len(samples),
            "accepted_all_roles_unfiltered": len(accepted_unfiltered),
            "accepted_all_roles": len(accepted),
            "accepted_evaluated_roles": len(relevant),
            "accepted_positive_evaluated_roles": len(relevant_positive),
            "accepted_empty_evaluated_roles": len(relevant_empty),
            "invalid_box_count": invalid_count,
            "score_filtered_positive": score_filtered_positive,
            "score_filtered_missing": score_filtered_missing,
        },
        "min_detection_score": min_detection_score,
        "roles_evaluated": list(roles),
        "role_status": {
            role: dict(sorted(role_status[role].items()))
            for role in roles
        },
        "accepted_positive_by_role": positive_by_role,
        "accepted_empty_by_role": empty_by_role,
        "accepted_piece_buckets_by_role": {
            role: {bucket: role_buckets[role].get(bucket, 0) for bucket in DEFAULT_BUCKETS}
            for role in roles
        },
        "accepted_piece_bucket_totals": {
            bucket: sum(role_buckets[role].get(bucket, 0) for role in roles)
            for bucket in DEFAULT_BUCKETS
        },
        "strict_positive_role_balanced_capacity": strict_capacity,
        "bucket_coverage_by_role": bucket_coverage_by_role,
        "image_metric_bucket_counts_by_role": _image_metric_bucket_counts(
            relevant,
            roles=roles,
        ),
        "image_coverage_by_role": _image_coverage_by_role(
            samples,
            roles=roles,
            target=image_bucket_target,
        ),
        "missing_by_target": missing_by_target,
        "weak_role_piece_buckets_under_30": weak_under_30,
        "weak_role_piece_buckets_under_50": weak_under_50,
        "algorithms_by_role": {
            role: dict(sorted(role_algorithms[role].items()))
            for role in roles
        },
        "capture_reasons_by_role": {
            role: role_reasons[role].most_common()
            for role in roles
        },
        "all_role_counts": _count_by(samples, "source_role"),
        "all_status_counts": _count_by(samples, "review_status"),
    }


def _load_hive_samples() -> list[Any]:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.database import SessionLocal
    from app.models.sample import Sample

    db = SessionLocal()
    try:
        return list(db.query(Sample).all())
    finally:
        db.close()


def run(
    *,
    output_dir: Path,
    roles: tuple[str, ...],
    target_sizes: tuple[int, ...],
    bucket_target: int,
    image_bucket_target: int,
    min_detection_score: float | None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = output_dir / "sample_cache.json"
    history_path = output_dir / "history.jsonl"
    cache = _load_cache(cache_path)
    cached_samples = cache.setdefault("samples", {})
    if not isinstance(cached_samples, dict):
        cached_samples = {}
        cache["samples"] = cached_samples

    rows = _load_hive_samples()
    seen_ids: set[str] = set()
    added = 0
    updated = 0
    unchanged = 0
    for row in rows:
        sample_id = str(row.id)
        seen_ids.add(sample_id)
        signature = _row_signature(row)
        cached = cached_samples.get(sample_id)
        if isinstance(cached, dict) and cached.get("signature") == signature:
            if cached.get("image_metrics") is None:
                cached["image_metrics"] = _compute_image_metrics(row.image_path)
                updated += 1
            else:
                unchanged += 1
            continue
        image_metrics = (
            cached.get("image_metrics")
            if isinstance(cached, dict)
            and cached.get("signature") == signature
            and isinstance(cached.get("image_metrics"), dict)
            else _compute_image_metrics(row.image_path)
        )
        cached_samples[sample_id] = _normalize_sample(
            row,
            signature,
            image_metrics=image_metrics,
        )
        if cached is None:
            added += 1
        else:
            updated += 1

    removed = 0
    for sample_id in list(cached_samples):
        if sample_id not in seen_ids:
            del cached_samples[sample_id]
            removed += 1

    now = datetime.now(timezone.utc)
    samples = list(cached_samples.values())
    summary = _summarize(
        samples,
        roles=roles,
        target_sizes=target_sizes,
        bucket_target=bucket_target,
        image_bucket_target=image_bucket_target,
        min_detection_score=min_detection_score,
    )
    snapshot = {
        "schema_version": 1,
        "source": "local Hive database",
        "created_at": now.isoformat(),
        "cache_delta": {
            "added": added,
            "updated": updated,
            "unchanged": unchanged,
            "removed": removed,
            "cached_total": len(cached_samples),
        },
        **summary,
    }

    snapshot_path = output_dir / "snapshots" / f"{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    latest_path = output_dir / "latest.json"
    _write_json(snapshot_path, snapshot)
    _write_json(latest_path, snapshot)

    cache["updated_at"] = now.isoformat()
    cache["source"] = "local Hive database"
    _write_json(cache_path, cache)

    history_entry = {
        "created_at": snapshot["created_at"],
        "cache_delta": snapshot["cache_delta"],
        "totals": snapshot["totals"],
        "accepted_positive_by_role": snapshot["accepted_positive_by_role"],
        "accepted_empty_by_role": snapshot["accepted_empty_by_role"],
        "strict_positive_role_balanced_capacity": snapshot["strict_positive_role_balanced_capacity"],
        "min_detection_score": snapshot["min_detection_score"],
        "bucket_coverage_by_role": {
            role: data.get("score_percent")
            for role, data in snapshot["bucket_coverage_by_role"].items()
        },
        "image_coverage_by_role": {
            role: data.get("score_percent")
            for role, data in snapshot["image_coverage_by_role"].items()
        },
        "missing_by_target": snapshot["missing_by_target"],
    }
    with history_path.open("a") as fh:
        fh.write(json.dumps(history_entry, sort_keys=True) + "\n")

    return snapshot


def _parse_csv_tuple(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _parse_int_csv_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part.strip()) for part in value.split(",") if part.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=_default_output_dir())
    parser.add_argument("--roles", default=",".join(DEFAULT_ROLES))
    parser.add_argument("--targets", default=",".join(str(v) for v in DEFAULT_TARGET_SIZES))
    parser.add_argument(
        "--bucket-target",
        type=int,
        default=DEFAULT_BUCKET_TARGET,
        help="Accepted samples per role+piece-count bucket that count as full coverage.",
    )
    parser.add_argument(
        "--image-bucket-target",
        type=int,
        default=DEFAULT_IMAGE_BUCKET_TARGET,
        help="Accepted samples per role+image-metric bucket that count as full image coverage.",
    )
    parser.add_argument(
        "--min-detection-score",
        type=float,
        default=None,
        help="Apply score threshold to positive samples in the precheck; empty samples stay included.",
    )
    args = parser.parse_args()

    snapshot = run(
        output_dir=args.output_dir,
        roles=_parse_csv_tuple(args.roles),
        target_sizes=_parse_int_csv_tuple(args.targets),
        bucket_target=args.bucket_target,
        image_bucket_target=args.image_bucket_target,
        min_detection_score=args.min_detection_score,
    )
    print(json.dumps(snapshot, indent=2, sort_keys=True))
    print(f"\nWrote latest snapshot to {args.output_dir / 'latest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
