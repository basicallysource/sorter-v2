"""Generate web-friendly images from the full-resolution originals.

Full-res originals live in docs/_img-src/ (kept in Git LFS, never deployed —
Jekyll ignores underscore-prefixed dirs). This script mirrors that tree into
docs/assets/img/, downscaling each image and picking a web format:

  - long side capped at MAX_PX (only ever downscaled, never upscaled)
  - images with real transparency  -> optimized PNG
  - everything else                -> progressive JPEG (quality JPEG_Q)

The output extension follows that rule, so a page referencing
/assets/img/foo.jpg expects an opaque source and /assets/img/foo.png a
transparent one. Run before pushing/deploying whenever _img-src changes:

    python3 docs/scripts/optimize_images.py

Requires Pillow.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

MAX_PX = 1600
JPEG_Q = 82
SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "_img-src"
OUT_DIR = ROOT / "assets" / "img"


def has_transparency(img: Image.Image) -> bool:
    if img.mode in ("RGBA", "LA"):
        alpha = img.getchannel("A")
        return alpha.getextrema()[0] < 255
    return img.mode == "P" and "transparency" in img.info


def downscale(img: Image.Image) -> Image.Image:
    long_side = max(img.size)
    if long_side <= MAX_PX:
        return img
    scale = MAX_PX / long_side
    new_size = (round(img.width * scale), round(img.height * scale))
    return img.resize(new_size, Image.LANCZOS)


def main() -> int:
    if not SRC_DIR.is_dir():
        print(f"no originals directory at {SRC_DIR}")
        return 0
    count = 0
    for src in sorted(SRC_DIR.rglob("*")):
        if not src.is_file() or src.suffix.lower() not in SUFFIXES:
            continue
        rel = src.relative_to(SRC_DIR)
        with Image.open(src) as img:
            img.load()
            transparent = has_transparency(img)
            img = downscale(img)
            if transparent:
                out = OUT_DIR / rel.with_suffix(".png")
                out.parent.mkdir(parents=True, exist_ok=True)
                img.save(out, optimize=True)
            else:
                out = OUT_DIR / rel.with_suffix(".jpg")
                out.parent.mkdir(parents=True, exist_ok=True)
                img.convert("RGB").save(
                    out, quality=JPEG_Q, optimize=True, progressive=True
                )
        print(f"{rel} -> {out.relative_to(ROOT)}")
        count += 1
    print(f"optimized {count} image(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
