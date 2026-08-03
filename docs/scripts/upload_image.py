"""Upload a docs image to the basically-docs bucket and print its URLs.

Takes a full-resolution original and a destination path, generates the
web-friendly version (long side capped at
1600px, transparent -> PNG, opaque -> progressive JPEG), and uploads both:

  originals/<dest-path>.<original-ext>   full quality, archival
  web/<dest-path>.<jpg|png>              what pages embed

Pages reference the web version via the CDN domain:

  https://img.basically.website/web/<dest-path>.<jpg|png>

Usage:

    python3 docs/scripts/upload_image.py ~/Downloads/IMG_1234.jpg assembly/top-interface/step1

Names are immutable by convention: if an image's content changes, upload it
under a new name (the CDN caches aggressively). Re-uploading an existing name
requires --force.

Credentials come from ~/.config/basically/do-spaces.env (SPACES_KEY /
SPACES_SECRET) or the environment. Requires Pillow and boto3.
"""

from __future__ import annotations

import argparse
import io
import mimetypes
import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from PIL import Image

MAX_PX = 1600
JPEG_Q = 82
SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}

BUCKET = "basically-docs"
ENDPOINT = "https://nyc3.digitaloceanspaces.com"
PUBLIC_BASE = "https://img.basically.website"
CACHE_CONTROL = "public, max-age=2592000"
CREDS_FILE = Path.home() / ".config" / "basically" / "do-spaces.env"


def load_creds() -> tuple[str, str]:
    env: dict[str, str] = {}
    if CREDS_FILE.is_file():
        for line in CREDS_FILE.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    key = os.environ.get("SPACES_KEY") or env.get("SPACES_KEY")
    secret = os.environ.get("SPACES_SECRET") or env.get("SPACES_SECRET")
    if not key or not secret:
        sys.exit(f"missing SPACES_KEY/SPACES_SECRET (set env vars or {CREDS_FILE})")
    return key, secret


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


def make_web_version(src: Path) -> tuple[bytes, str]:
    with Image.open(src) as img:
        img.load()
        transparent = has_transparency(img)
        img = downscale(img)
        buf = io.BytesIO()
        if transparent:
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue(), ".png"
        img.convert("RGB").save(
            buf, format="JPEG", quality=JPEG_Q, optimize=True, progressive=True
        )
        return buf.getvalue(), ".jpg"


def key_exists(s3, key: str) -> bool:
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
        return True
    except ClientError:
        return False


def upload(s3, key: str, body: bytes, content_type: str, force: bool) -> None:
    if not force and key_exists(s3, key):
        sys.exit(
            f"refusing to overwrite existing {key} — names are immutable by "
            "convention (pick a new name, or pass --force if you really mean it)"
        )
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=body,
        ACL="public-read",
        ContentType=content_type,
        CacheControl=CACHE_CONTROL,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path, help="path to the full-resolution image")
    parser.add_argument(
        "dest",
        help="destination path in the bucket, no extension (e.g. assembly/top-interface/step1)",
    )
    parser.add_argument("--force", action="store_true", help="overwrite existing keys")
    parser.add_argument(
        "--skip-original", action="store_true", help="only upload the web version"
    )
    args = parser.parse_args()

    src: Path = args.original
    if not src.is_file():
        sys.exit(f"no such file: {src}")
    if src.suffix.lower() not in SUFFIXES:
        sys.exit(f"unsupported image type: {src.suffix}")
    dest = args.dest.strip("/")
    dest = str(Path(dest).with_suffix(""))

    key, secret = load_creds()
    s3 = boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
    )

    web_bytes, web_ext = make_web_version(src)
    web_key = f"web/{dest}{web_ext}"
    web_type = "image/png" if web_ext == ".png" else "image/jpeg"
    upload(s3, web_key, web_bytes, web_type, args.force)
    print(f"{PUBLIC_BASE}/{web_key}")

    if not args.skip_original:
        orig_ext = ".jpg" if src.suffix.lower() == ".jpeg" else src.suffix.lower()
        orig_key = f"originals/{dest}{orig_ext}"
        orig_type = mimetypes.guess_type(str(src))[0] or "application/octet-stream"
        upload(s3, orig_key, src.read_bytes(), orig_type, args.force)
        print(f"{PUBLIC_BASE}/{orig_key}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
