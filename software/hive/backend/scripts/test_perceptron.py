"""Standalone Perceptron adapter test — iterate without redeploying to Hive.

Usage:
    PERCEPTRON_API_KEY=pk_... uv run scripts/test_perceptron.py path/to/image.jpg \
        [--zone classification_channel] [--show-raw]

Prints the raw response, the parsed detections, and per-box pixel coordinates so we can
see exactly what Perceptron returns and what the adapter makes of it. Useful for prompt
tweaks, format-change adaptations, and parser regression checks — no Docker, no DB, no
session cookies.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Make the backend importable when the script runs from any cwd.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from app.services.teacher_adapters.perceptron import (  # noqa: E402
    PERCEPTRON_MODEL_ID,
    PerceptronAdapter,
    _extract_point_boxes,
    _zone_instruction,
)


SUPPORTED_ZONES = (
    "classification_channel",
    "c_channel",
    "classification_chamber",
    "carousel",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("image", type=Path, help="Path to a sample JPEG/PNG")
    parser.add_argument(
        "--zone",
        choices=SUPPORTED_ZONES,
        default="classification_channel",
        help="Which zone instruction + classes to send (default: classification_channel)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("PERCEPTRON_API_KEY"),
        help="Perceptron API key (or set PERCEPTRON_API_KEY env)",
    )
    parser.add_argument(
        "--show-raw",
        action="store_true",
        help="Print the raw assistant text in addition to the parsed detections",
    )
    parser.add_argument(
        "--parse-only",
        metavar="TEXT",
        help="Skip the API call; just parse the provided text (for regex debugging)",
    )
    args = parser.parse_args()

    if args.parse_only is not None:
        from PIL import Image
        with Image.open(args.image) as img:
            w, h = img.size
        print(f"image size: {w}x{h}")
        boxes = _extract_point_boxes(args.parse_only, w, h)
        print(f"parsed {len(boxes)} box(es):")
        for b in boxes:
            print(f"  {b}")
        return 0

    if not args.api_key:
        print("ERROR: --api-key or PERCEPTRON_API_KEY env var required", file=sys.stderr)
        return 2

    if not args.image.exists():
        print(f"ERROR: image not found: {args.image}", file=sys.stderr)
        return 2

    image_bytes = args.image.read_bytes()
    instruction = _zone_instruction(args.zone)

    print(f"model       : {PERCEPTRON_MODEL_ID}")
    print(f"zone        : {args.zone}")
    print(f"instruction : {instruction}")
    print(f"image       : {args.image} ({len(image_bytes):,} bytes)")
    print()

    adapter = PerceptronAdapter()
    try:
        result = adapter.detect(
            image_bytes=image_bytes,
            zone=args.zone,
            api_key=args.api_key,
            public_app_url="http://localhost",
        )
    except Exception as exc:
        print(f"detect() raised: {exc}", file=sys.stderr)
        return 1

    print(f"latency     : {result.elapsed_ms} ms")
    print(f"cost_usd    : {result.cost_usd}")
    print(f"tokens      : in={result.prompt_tokens} out={result.completion_tokens}")
    print(f"image_size  : {result.image_width}x{result.image_height}")
    print(f"detections  : {result.count}")
    for det in result.detections:
        print(f"  {det}")

    if args.show_raw or result.count == 0:
        raw = result.raw_response or {}
        text = raw.get("text") if isinstance(raw, dict) else None
        print()
        print("--- raw assistant text ---")
        print(text if text is not None else json.dumps(raw, indent=2, default=str))

    return 0 if result.count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
