"""Upload a docs image to the asset service and print the URLs to embed.

Every file the docs embed -- image or video -- lives in the asset service
(`assets.basically.website`, public repo `basicallysource/asset-service`).
This uploads the original; the service stores it under a content-addressed
name and builds a JPEG/PNG ladder (320-2048px wide) beside it in the
background. Docs pages embed the 1600px rung, which is the first URL this
prints.

Usage:

    python3 docs/scripts/upload_image.py ~/Downloads/IMG_1234.jpg [name]

`name` becomes the readable part of the URL (e.g. `top-interface-step1`); it
defaults to the file's own name. The service appends a hash of the bytes, so
a changed image is always a new URL that caches forever, and re-uploading the
same bytes is a no-op that prints the same URLs back.

Credentials are ASSET_SERVICE_URL / ASSET_SERVICE_TOKEN, from the environment
or ~/.config/asset-service/*.env -- the same pair video_embed.py reads.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = "sorter-v2-docs/1.0 (+https://github.com/basicallysource/sorter-v2)"
CONFIG_DIR = Path.home() / ".config" / "asset-service"
NAMESPACE = "sorter-docs"
EMBED_WIDTH = 1600

SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def load_creds() -> tuple[str, str]:
    env: dict[str, str] = {}
    for path in sorted(CONFIG_DIR.glob("*.env")) if CONFIG_DIR.is_dir() else []:
        for line in path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip())
    url = os.environ.get("ASSET_SERVICE_URL") or env.get("ASSET_SERVICE_URL")
    token = os.environ.get("ASSET_SERVICE_TOKEN") or env.get("ASSET_SERVICE_TOKEN")
    if not url or not token:
        sys.exit(f"missing ASSET_SERVICE_URL/ASSET_SERVICE_TOKEN (env or {CONFIG_DIR}/*.env)")
    return url.rstrip("/"), token


def prepare(src: Path) -> tuple[bytes, str]:
    """The bytes exactly as they are, and their content type. The service does
    the rest itself: it turns a photo the way its EXIF says to, and it never
    publishes the camera's own file -- pages get metadata-free copies."""
    return src.read_bytes(), CONTENT_TYPES[src.suffix.lower()]


def request(base: str, token: str, method: str, path: str, body: bytes | None = None,
            content_type: str | None = None) -> dict:
    req = urllib.request.Request(base + path, data=body, method=method)
    req.add_header("User-Agent", UA)
    req.add_header("Authorization", "Bearer " + token)
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        sys.exit(f"{method} {path}: HTTP {e.code}: {detail}")


def embed_url(manifest: dict) -> str:
    """The URL a docs page should reference: the widest rung <= 1600px."""
    rungs = [
        r for r in manifest.get("renditions", [])
        if r.get("name") != "original"
        and not r.get("url_expires")
        and r.get("content_type", "").startswith("image/")
        and (r.get("width") or 0) <= EMBED_WIDTH
    ]
    if rungs:
        return max(rungs, key=lambda r: r.get("width") or 0)["url"]
    # Too small to have a ladder: the original is already the right answer.
    return manifest["url"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path, help="path to the full-resolution image")
    parser.add_argument("name", nargs="?", default=None,
                        help="readable name for the URL (default: the file's own name)")
    args = parser.parse_args()

    src: Path = args.original
    if not src.is_file():
        sys.exit(f"no such file: {src}")
    if src.suffix.lower() not in SUFFIXES:
        sys.exit(f"unsupported image type: {src.suffix} (HEIC and the like: convert first)")

    base, token = load_creds()
    body, content_type = prepare(src)
    ext = ".jpg" if content_type == "image/jpeg" else src.suffix.lower()
    filename = (args.name or src.stem) + ext

    query = urllib.parse.urlencode({"namespace": NAMESPACE, "filename": filename})
    manifest = request(base, token, "POST", f"/v1/assets?{query}", body, content_type)
    key = manifest["key"]

    # The ladder is built in the background; for an image that is seconds.
    deadline = time.monotonic() + 120
    while manifest.get("renditions_status") == "pending":
        if time.monotonic() > deadline:
            print(f"ladder still pending; check later: {base}/v1/assets/{key}", file=sys.stderr)
            break
        time.sleep(2)
        manifest = request(base, token, "GET", f"/v1/assets/{key}")

    print(embed_url(manifest))
    print(manifest["url"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
