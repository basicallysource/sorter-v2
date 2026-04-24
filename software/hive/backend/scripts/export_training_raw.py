#!/usr/bin/env python3
"""Export local Hive samples into the training raw dataset layout.

This is intentionally local-only: it reads the Hive database through the backend
models and links/copies the already stored upload assets. It is useful when the
local machine token can upload samples, but the admin sample API key is not
available for ``train pull``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_ROLES = ("c_channel_2", "c_channel_3", "classification_channel")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _hive_backend_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _uploads_dir() -> Path:
    return _hive_backend_dir() / "data" / "uploads"


def _default_output_dir() -> Path:
    return _repo_root() / "software" / "training" / "datasets" / "c_channel" / "raw_hive_current"


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _resolve_upload_path(stored_path: str | None) -> Path | None:
    if not stored_path:
        return None
    root = _uploads_dir().resolve()
    candidate = (root / stored_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _link_or_copy(src: Path, dst: Path, *, copy: bool) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    if copy:
        shutil.copy2(src, dst)
        return
    try:
        dst.symlink_to(src)
    except OSError:
        shutil.copy2(src, dst)


def _load_hive_samples() -> list[Any]:
    sys.path.insert(0, str(_hive_backend_dir()))
    from app.database import SessionLocal
    from app.models.sample import Sample

    db = SessionLocal()
    try:
        return list(db.query(Sample).all())
    finally:
        db.close()


def _sample_to_manifest_entry(sample: Any, sample_dir: Path, target_dir: Path) -> dict[str, Any]:
    return {
        "id": str(sample.id),
        "local_sample_id": sample.local_sample_id,
        "source_role": sample.source_role,
        "capture_reason": sample.capture_reason,
        "review_status": sample.review_status,
        "detection_algorithm": sample.detection_algorithm,
        "detection_count": sample.detection_count,
        "detection_score": sample.detection_score,
        "detection_bboxes": sample.detection_bboxes,
        "image_width": sample.image_width,
        "image_height": sample.image_height,
        "uploaded_at": _iso(sample.uploaded_at),
        "captured_at": _iso(sample.captured_at),
        "resolved_at": _iso(sample.resolved_at),
        "has_full_frame": bool(sample.full_frame_path),
        "has_overlay": bool(sample.overlay_path),
        "dir": str(sample_dir.relative_to(target_dir.parent)),
    }


def run(
    *,
    output_dir: Path,
    roles: tuple[str, ...],
    status: str | None,
    copy: bool,
    clean: bool,
) -> int:
    output_dir = output_dir.resolve()
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, Any]] = []
    skipped_missing_image = 0
    skipped_status = 0
    skipped_role = 0

    for sample in _load_hive_samples():
        if roles and sample.source_role not in roles:
            skipped_role += 1
            continue
        if status and sample.review_status != status:
            skipped_status += 1
            continue

        image_src = _resolve_upload_path(sample.image_path)
        if image_src is None:
            skipped_missing_image += 1
            continue

        sample_id = str(sample.id)
        sample_dir = output_dir / sample_id
        sample_dir.mkdir(parents=True, exist_ok=True)
        _link_or_copy(image_src, sample_dir / "image.jpg", copy=copy)

        full_frame_src = _resolve_upload_path(sample.full_frame_path)
        if full_frame_src is not None:
            _link_or_copy(full_frame_src, sample_dir / "full_frame.jpg", copy=copy)

        overlay_src = _resolve_upload_path(sample.overlay_path)
        if overlay_src is not None:
            _link_or_copy(overlay_src, sample_dir / "overlay.jpg", copy=copy)

        metadata = {
            "id": sample_id,
            "sample_payload": sample.sample_payload,
            "extra_metadata": sample.extra_metadata,
            "image_path": sample.image_path,
            "full_frame_path": sample.full_frame_path,
            "overlay_path": sample.overlay_path,
        }
        (sample_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True))
        manifest.append(_sample_to_manifest_entry(sample, sample_dir, output_dir))

    manifest.sort(key=lambda item: item["id"])
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    (output_dir / "export.json").write_text(
        json.dumps(
            {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "roles": list(roles),
                "status": status,
                "samples": len(manifest),
                "skipped_missing_image": skipped_missing_image,
                "skipped_status": skipped_status,
                "skipped_role": skipped_role,
            },
            indent=2,
            sort_keys=True,
        )
    )

    print(
        f"Exported {len(manifest)} samples to {output_dir} "
        f"(missing_image={skipped_missing_image}, skipped_status={skipped_status}, skipped_role={skipped_role})",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=_default_output_dir())
    parser.add_argument("--role", action="append", dest="roles", help="Hive source_role to export. Repeatable.")
    parser.add_argument("--status", default="accepted", help="Review status filter; pass empty string for any.")
    parser.add_argument("--copy", action="store_true", help="Copy images instead of symlinking them.")
    parser.add_argument("--clean", action="store_true", help="Remove the output directory before exporting.")
    args = parser.parse_args()
    roles = tuple(args.roles) if args.roles else DEFAULT_ROLES
    return run(
        output_dir=args.output_dir,
        roles=roles,
        status=args.status or None,
        copy=args.copy,
        clean=args.clean,
    )


if __name__ == "__main__":
    raise SystemExit(main())
