#!/usr/bin/env python3
"""Fetch product images for COTS parts and put them on the bucket.

Only touches parts that need it: a `kind: "cots"` part in slicer/parts.json
with a US Amazon vendor and no `image_url`/`image` yet. Re-running after
adding a new part fetches just that part -- everything already imaged is
skipped, so this is the normal way to onboard a new hardware link.

The image is scraped from the listing, uploaded content-addressed to
img/<sha256><ext> (same bucket + immutability rules as the STLs -- see
notes/UNIFIED-PARTS-SYSTEM.md section 7), and the resulting URL is written back
into the manifest as `image_url`. Product images deliberately never enter git:
the bucket is their only store, and the manifest just points at it.

Usage:
  python scripts/fetch_product_images.py --dry-run   # list what's missing
  python scripts/fetch_product_images.py             # fetch + upload + write back
  python scripts/fetch_product_images.py --only caster-wheel-m6
  python scripts/fetch_product_images.py --refetch caster-wheel-m6   # replace existing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from sync_bucket import BUCKET, ENDPOINT, PUBLIC_BASE, REGION, load_credentials  # noqa: E402

MANIFEST = REPO / "slicer" / "parts.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
AMAZON = re.compile(r"amazon\.com|amzn\.to|a\.co/")


def fetch(url: str, binary: bool = False):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "ignore")


def image_url_from_page(html: str) -> str | None:
    """Best available product image, preferring the highest resolution."""
    for pattern in (r'"hiRes":"(https://[^"]+)"',
                    r'"large":"(https://m\.media-amazon\.com[^"]+)"',
                    r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
                    r'id="landingImage"[^>]+src="([^"]+)"'):
        m = re.search(pattern, html)
        if m:
            return m.group(1).encode().decode("unicode_escape")
    return None


def listing_url(part: dict) -> str | None:
    for v in part.get("sourcing", {}).get("vendors", []):
        if v.get("region") == "US" and AMAZON.search(v.get("url", "")):
            return v["url"]
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only")
    ap.add_argument("--only", action="append", default=[], metavar="ID",
                    help="restrict to these part ids (repeatable)")
    ap.add_argument("--refetch", action="append", default=[], metavar="ID",
                    help="re-fetch these ids even though they already have an image")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text())
    todo = []
    for p in manifest["parts"]:
        if p.get("kind") != "cots":
            continue
        if args.only and p["id"] not in args.only:
            continue
        has_image = p.get("image_url") or p.get("image")
        if has_image and p["id"] not in args.refetch:
            continue
        url = listing_url(p)
        if not url:
            print(f"  - {p['id']}: no US Amazon listing, skipping")
            continue
        todo.append((p, url))

    if not todo:
        print("nothing to fetch -- every COTS part already has an image")
        return
    print(f"{len(todo)} part(s) need an image")
    if args.dry_run:
        for p, url in todo:
            print(f"  would fetch {p['id']:<26} {url}")
        return

    import boto3

    key, secret = load_credentials()
    s3 = boto3.client("s3", region_name=REGION, endpoint_url=ENDPOINT,
                      aws_access_key_id=key, aws_secret_access_key=secret)

    failures = []
    for i, (part, url) in enumerate(todo):
        pid = part["id"]
        try:
            img = image_url_from_page(fetch(url))
            if not img:
                raise RuntimeError("no product image found on the listing page")
            data = fetch(img, binary=True)
            if len(data) < 2000:
                raise RuntimeError(f"suspiciously small image ({len(data)} bytes)")
            ext = ".png" if img.lower().split("?")[0].endswith(".png") else ".jpg"
            digest = hashlib.sha256(data).hexdigest()
            obj_key = f"img/{digest}{ext}"
            s3.put_object(
                Bucket=BUCKET, Key=obj_key, Body=data,
                ACL="public-read",
                ContentType="image/png" if ext == ".png" else "image/jpeg",
                # inline so <img> and open-in-tab both behave
                ContentDisposition=f'inline; filename="{pid}{ext}"',
                CacheControl="public, max-age=31536000, immutable",
            )
            part["image_url"] = f"{PUBLIC_BASE}/{obj_key}"
            print(f"  + {pid:<26} {len(data)/1024:5.0f} KB  {obj_key}")
        except Exception as e:
            failures.append(pid)
            print(f"  ! {pid:<26} {e}")
        if i < len(todo) - 1:
            time.sleep(1.5)  # be polite to the listing host

    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {MANIFEST.relative_to(REPO)}")
    if failures:
        print(f"  ! {len(failures)} failed: {', '.join(failures)}")
    print("now re-run slicer/filament.py to regenerate the app's data")


if __name__ == "__main__":
    main()
