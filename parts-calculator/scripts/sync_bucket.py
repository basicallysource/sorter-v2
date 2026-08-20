#!/usr/bin/env python3
"""Sync build artifacts (STLs, 3MFs) to DigitalOcean Spaces, content-addressed.

Every file is stored at <prefix>/<sha256><ext> and uploaded only if absent, so
re-runs are cheap and identical bytes are never stored twice. Because the
address IS the content hash, every historical revision stays downloadable
forever with zero redundancy -- which is what lets parts.json pin an
`stl_hash` per revision (see notes/UNIFIED-PARTS-SYSTEM.md section 7).

Credentials, in order of precedence:
  1. env: DO_SPACES_KEY / DO_SPACES_SECRET
  2. file: ~/.config/do-spaces/sorter-v2-parts.env  (KEY=VALUE lines)

Usage:
  python scripts/sync_bucket.py --dry-run     # show what would upload
  python scripts/sync_bucket.py               # upload missing, write manifest
  python scripts/sync_bucket.py --upload a.png b.jpg
                                              # put product images on the bucket
                                              # and print the image_url to paste
                                              # into slicer/parts.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

BUCKET = "sorter-v2-parts"
REGION = "nyc3"
ENDPOINT = f"https://{REGION}.digitaloceanspaces.com"
# CDN endpoint (edge-cached). The origin hostname -- same URL without `.cdn.`
# -- also serves these objects permanently, so switching between the two is
# never a breaking change.
PUBLIC_BASE = os.environ.get(
    "DO_SPACES_PUBLIC_BASE", f"https://{BUCKET}.{REGION}.cdn.digitaloceanspaces.com"
)

# Directories whose contents get pushed. Keep this list narrow: only things
# the website serves or that pin a revision. Renders (1.4M total) stay as
# normal git blobs -- they are small and the site wants them at build time.
SOURCES = [
    ("slicer/parts", "*.stl", "stl"),
    ("slicer/plates", "*.3mf", "plate"),
    # The bundle is regenerated into gitignored build/ by filament.py; its
    # bytes must reach the bucket because settings.all_parts_zip points there.
    ("slicer/build/bundle", "all-parts.zip", "bundle"),
    # COTS/hardware product images are deliberately absent: they never enter
    # git. `--upload <file>` puts one on the bucket and prints the image_url to
    # paste into parts.json. Historical part-version STLs are absent too: their
    # bytes were uploaded by the regen that ran while that geometry was the
    # live master, and parts.json pins them by stl_hash.
]

CONTENT_TYPES = {".stl": "model/stl", ".3mf": "model/3mf", ".zip": "application/zip",
                 ".png": "image/png", ".jpg": "image/jpeg"}

# Images render in <img> tags; everything else is a download.
INLINE_SUFFIXES = {".png", ".jpg"}

MANIFEST = REPO / "slicer" / "artifacts.json"
CREDS_FILE = Path.home() / ".config" / "do-spaces" / "sorter-v2-parts.env"


def load_credentials() -> tuple[str, str]:
    key, secret = os.environ.get("DO_SPACES_KEY"), os.environ.get("DO_SPACES_SECRET")
    if key and secret:
        return key, secret

    if CREDS_FILE.exists():
        values = {}
        for line in CREDS_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
        key = key or values.get("DO_SPACES_KEY")
        secret = secret or values.get("DO_SPACES_SECRET")

    if not (key and secret):
        sys.exit(
            f"Missing credentials. Set DO_SPACES_KEY/DO_SPACES_SECRET, or put them in {CREDS_FILE}"
        )
    return key, secret


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        first = True
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            # An unmaterialized LFS file hashes and uploads perfectly happily --
            # it is just 130 bytes of pointer text. The result is a valid-looking
            # content-addressed URL serving a stub, which the browser renders as
            # a broken image. Fail loudly instead of publishing the stub.
            if first and chunk[:40].startswith(b"version https://git-lfs"):
                sys.exit(
                    f"{path} is an unmaterialized Git LFS pointer, not real content.\n"
                    "Run `git lfs pull` (or check out with lfs: true in CI) and retry."
                )
            first = False
            h.update(chunk)
    return h.hexdigest()


def artifact_url(path: str | Path, prefix: str = "stl") -> str:
    """Public URL for a local file, derived purely from its content hash.

    Deliberately does NOT consult the bucket or the manifest: the address is a
    function of the bytes, so the generator can emit correct URLs before an
    upload has happened. sync_bucket.py's only job is making sure the bytes are
    actually there.
    """
    p = Path(path)
    return f"{PUBLIC_BASE}/{prefix}/{sha256(p)}{p.suffix}"


def set_cors(s3) -> None:
    """Allow browsers on any origin to GET these objects.

    `*` is correct here rather than lax: the objects are public and
    unauthenticated (no cookies, no credentials), so CORS grants nothing that a
    plain curl doesn't already have. It keeps localhost on any port, Vercel
    preview deploys, and the docs site all working without maintenance.
    """
    s3.put_bucket_cors(
        Bucket=BUCKET,
        CORSConfiguration={
            "CORSRules": [
                {
                    "AllowedMethods": ["GET", "HEAD"],
                    "AllowedOrigins": ["*"],
                    "AllowedHeaders": ["*"],
                    "MaxAgeSeconds": 3600,
                }
            ]
        },
    )


def upload_args(name: str) -> dict:
    """ExtraArgs for a public, permanently-cached, content-addressed object."""
    return {
        "ACL": "public-read",
        "ContentType": CONTENT_TYPES.get(Path(name).suffix, "application/octet-stream"),
        # So a browser download lands as "chute-core.stl", not a hash.
        # Images stay inline so <img> and open-in-tab both behave.
        "ContentDisposition": (
            f'inline; filename="{name}"'
            if Path(name).suffix in INLINE_SUFFIXES
            else f'attachment; filename="{name}"'
        ),
        "CacheControl": "public, max-age=31536000, immutable",
    }


def s3_client():
    import boto3

    key, secret = load_credentials()
    return boto3.client(
        "s3", region_name=REGION, endpoint_url=ENDPOINT,
        aws_access_key_id=key, aws_secret_access_key=secret,
    )


def upload_loose(paths: list[str], prefix: str = "img") -> None:
    """Put image files on the bucket and print the image_url for each.

    This is how a product image gets onto the site: someone hands you a photo,
    you upload it, you paste the printed line into slicer/parts.json. The file
    itself is never copied into the repo.
    """
    s3 = s3_client()
    for raw in paths:
        p = Path(raw).resolve()
        if not p.is_file():
            sys.exit(f"not a file: {p}")
        # sha256() refuses LFS pointers, so a stub can't be published here either.
        key = f"{prefix}/{sha256(p)}{p.suffix}"
        try:
            s3.head_object(Bucket=BUCKET, Key=key)
            print(f"  already on the bucket  {p.name}")
        except Exception:
            s3.upload_file(str(p), BUCKET, key, ExtraArgs=upload_args(p.name))
            print(f"  uploaded  {p.name}  ({p.stat().st_size / 1e6:.1f} MB)")
        print(f'    "image_url": "{PUBLIC_BASE}/{key}"')


def collect() -> list[dict]:
    """Every syncable file, with its hash and object key."""
    found = []
    for subdir, glob, prefix in SOURCES:
        root = REPO / subdir
        if not root.exists():
            continue
        for path in sorted(root.rglob(glob)):
            digest = sha256(path)
            found.append(
                {
                    "path": str(path.relative_to(REPO)),
                    "name": path.name,
                    "sha256": digest,
                    "size": path.stat().st_size,
                    "key": f"{prefix}/{digest}{path.suffix}",
                }
            )
    return found


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only, upload nothing")
    ap.add_argument("--set-cors", action="store_true", help="apply the CORS policy and exit")
    ap.add_argument("--upload", nargs="+", metavar="FILE",
                    help="put product image(s) on the bucket and print the image_url "
                         "to paste into slicer/parts.json; the file is never copied "
                         "into the repo")
    args = ap.parse_args()

    if args.upload:
        upload_loose(args.upload)
        return

    if args.set_cors:
        set_cors(s3_client())
        print(f"CORS applied to {BUCKET}")
        return

    files = collect()
    if not files:
        sys.exit("No source files found -- are you running from the repo?")

    unique = {f["sha256"]: f for f in files}
    total_mb = sum(f["size"] for f in unique.values()) / 1e6
    dupes = len(files) - len(unique)
    print(f"{len(files)} files, {len(unique)} unique ({total_mb:.1f} MB), {dupes} duplicate bytes")

    import boto3
    from botocore.exceptions import ClientError

    key, secret = load_credentials()
    s3 = boto3.client(
        "s3",
        region_name=REGION,
        endpoint_url=ENDPOINT,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
    )

    uploaded = skipped = 0
    for f in unique.values():
        try:
            s3.head_object(Bucket=BUCKET, Key=f["key"])
            skipped += 1
            continue
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("404", "NoSuchKey", "403"):
                raise

        if args.dry_run:
            print(f"  would upload {f['name']:<44} {f['size']/1e6:6.1f} MB  {f['key']}")
            uploaded += 1
            continue

        s3.upload_file(
            str(REPO / f["path"]), BUCKET, f["key"], ExtraArgs=upload_args(f["name"])
        )
        print(f"  uploaded {f['name']:<44} {f['size']/1e6:6.1f} MB")
        uploaded += 1

    verb = "would upload" if args.dry_run else "uploaded"
    print(f"\n{verb} {uploaded}, already present {skipped}")

    if args.dry_run:
        return

    manifest = {
        "bucket": BUCKET,
        "public_base": PUBLIC_BASE,
        "artifacts": {
            f["path"]: {"sha256": f["sha256"], "size": f["size"],
                        "url": f"{PUBLIC_BASE}/{f['key']}"}
            for f in files
        },
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {MANIFEST.relative_to(REPO)} ({len(files)} entries)")


if __name__ == "__main__":
    main()
