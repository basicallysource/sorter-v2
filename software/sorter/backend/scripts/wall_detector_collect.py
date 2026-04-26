#!/usr/bin/env python3
"""Batch-label C4 frames with Gemini for the wall-detector training set.

Produces a YOLO-formatted training tree from a directory of captured
C4 camera frames. For each input image the script:

* asks Gemini (via the project's ``llm_client`` facade) to locate the
  visible walls of the 5-wall C4 platter;
* writes a YOLO label file (``<stem>.txt``) with one bbox per wall;
* writes a JSON sample record (``<stem>.json``) with the raw model
  response, parsed walls, and image metadata for review;
* optionally renders a preview overlay (``<stem>.preview.jpg``) so an
  operator can spot-check a few labels before training.

The script is resumable — if the YOLO and JSON files already exist
for an image, it is skipped. Pass ``--force`` to re-label.

Usage::

    OPENROUTER_API_KEY=... uv run python scripts/wall_detector_collect.py \
        --input-dir captures/c4_frames \
        --output-dir datasets/c4_walls \
        --model google/gemini-3.1-flash-lite-preview \
        --preview

The output directory mirrors the YOLO convention::

    datasets/c4_walls/
      images/<stem>.jpg          # original copy or symlink
      labels/<stem>.txt          # YOLO bboxes (class 0 = wall)
      meta/<stem>.json           # rich teacher metadata
      previews/<stem>.preview.jpg
      classes.txt                # ``wall``
      run.json                   # batch-run summary
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import cv2

# Make ``server.*`` importable when running this from any cwd.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from server.wall_detector_teacher import (  # noqa: E402
    DEFAULT_WALL_TEACHER_OPENROUTER_MODEL,
    EXPECTED_WALL_COUNT,
    GeminiWallTeacher,
    WALL_DETECTOR_CLASS_NAME,
    WallTeacherResult,
)


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Use Gemini to label C4 wall positions for YOLO training."
        )
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Directory containing C4 camera frames (JPEG/PNG).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Destination root for the YOLO training tree.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_WALL_TEACHER_OPENROUTER_MODEL,
        help=(
            "OpenRouter Gemini model slug. Defaults to "
            f"{DEFAULT_WALL_TEACHER_OPENROUTER_MODEL}."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Stop after labeling this many images (0 = no limit).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-label images even when label/meta files already exist.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Write per-image preview JPEGs with the boxes drawn on.",
    )
    parser.add_argument(
        "--copy-images",
        action="store_true",
        help=(
            "Copy original images into ``<output>/images/`` instead of "
            "the default symlink (handy when the dataset will move "
            "across machines)."
        ),
    )
    parser.add_argument(
        "--min-walls",
        type=int,
        default=0,
        help=(
            "Skip writing labels for images where Gemini found fewer "
            "than this many walls. Default 0 (write every result)."
        ),
    )
    return parser.parse_args()


def _iter_images(root: Path) -> list[Path]:
    if not root.is_dir():
        raise SystemExit(f"input dir not found: {root}")
    found = sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in _IMAGE_EXTS
    )
    return found


def _ensure_dirs(root: Path, *, preview: bool) -> dict[str, Path]:
    paths = {
        "images": root / "images",
        "labels": root / "labels",
        "meta": root / "meta",
    }
    if preview:
        paths["previews"] = root / "previews"
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _write_classes_file(root: Path) -> None:
    """Standard YOLO ``classes.txt`` — one class per line, index = line number."""
    (root / "classes.txt").write_text(f"{WALL_DETECTOR_CLASS_NAME}\n", encoding="utf-8")


def _materialize_image(src: Path, dst: Path, *, copy: bool) -> None:
    if dst.exists():
        return
    if copy:
        shutil.copy2(src, dst)
    else:
        try:
            dst.symlink_to(src.resolve())
        except OSError:
            shutil.copy2(src, dst)


def _render_preview(result: WallTeacherResult, target: Path) -> None:
    image = cv2.imread(str(result.image_path), cv2.IMREAD_COLOR)
    if image is None:
        return
    for wall in result.walls:
        x1, y1, x2, y2 = (int(round(v)) for v in wall.bbox_xyxy)
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 200, 255), 2)
        label = f"{wall.confidence:.2f}"
        cv2.putText(
            image,
            label,
            (x1, max(0, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 200, 255),
            1,
            cv2.LINE_AA,
        )
    cv2.imwrite(str(target), image, [cv2.IMWRITE_JPEG_QUALITY, 90])


def _write_outputs(
    *,
    src_image: Path,
    result: WallTeacherResult,
    dirs: dict[str, Path],
    preview: bool,
    copy_images: bool,
    min_walls: int,
) -> tuple[bool, str]:
    if len(result.walls) < min_walls:
        return False, f"skipped (walls={len(result.walls)} < min={min_walls})"

    stem = src_image.stem
    image_target = dirs["images"] / f"{stem}{src_image.suffix.lower()}"
    label_target = dirs["labels"] / f"{stem}.txt"
    meta_target = dirs["meta"] / f"{stem}.json"

    _materialize_image(src_image, image_target, copy=copy_images)
    label_target.write_text(result.to_yolo_labels() + "\n", encoding="utf-8")
    meta_target.write_text(
        json.dumps(result.to_metadata(), indent=2) + "\n", encoding="utf-8"
    )
    if preview and "previews" in dirs:
        _render_preview(result, dirs["previews"] / f"{stem}.preview.jpg")
    return True, f"ok (walls={len(result.walls)})"


def main() -> int:
    args = _parse_args()
    images = _iter_images(args.input_dir)
    if not images:
        print(f"no images under {args.input_dir}", file=sys.stderr)
        return 1

    output_root = args.output_dir
    output_root.mkdir(parents=True, exist_ok=True)
    dirs = _ensure_dirs(output_root, preview=args.preview)
    _write_classes_file(output_root)

    teacher = GeminiWallTeacher()
    summary: dict[str, int] = {
        "input_count": len(images),
        "labeled": 0,
        "skipped_existing": 0,
        "skipped_min_walls": 0,
        "failed": 0,
    }
    started_at = time.time()

    for idx, image_path in enumerate(images, start=1):
        if args.limit and summary["labeled"] >= args.limit:
            break
        stem = image_path.stem
        label_target = dirs["labels"] / f"{stem}.txt"
        meta_target = dirs["meta"] / f"{stem}.json"
        if not args.force and label_target.exists() and meta_target.exists():
            summary["skipped_existing"] += 1
            print(f"[{idx:>4}/{len(images)}] skip-existing {image_path}")
            continue
        try:
            result = teacher.label_image(image_path, model=args.model)
        except Exception as exc:
            summary["failed"] += 1
            print(
                f"[{idx:>4}/{len(images)}] FAIL {image_path}: {exc}",
                file=sys.stderr,
            )
            continue
        wrote, status = _write_outputs(
            src_image=image_path,
            result=result,
            dirs=dirs,
            preview=args.preview,
            copy_images=args.copy_images,
            min_walls=args.min_walls,
        )
        if wrote:
            summary["labeled"] += 1
        else:
            summary["skipped_min_walls"] += 1
        print(
            f"[{idx:>4}/{len(images)}] {status:<28} {image_path} "
            f"(expected={EXPECTED_WALL_COUNT})"
        )

    summary["duration_s"] = round(time.time() - started_at, 2)
    summary["model"] = args.model
    (output_root / "run.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print()
    print(f"=== wall-detector collect summary ===")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
