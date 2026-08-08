"""Publish the rendered harness to the assets bucket under a git ref.

    ./electronics/wire_harness/build-harness.sh
    ./electronics/wire_harness/upload-harness.py --ref my-branch

Uploads everything in out/ to harness/<ref>/ in the basically-docs Space,
overwriting whatever that ref held before. The docs build derives the same
prefix from the ref it is building (docs/_plugins/harness.rb), so a branch's
Vercel preview shows that branch's drawings and production (main) shows main's.
Nothing rendered is ever committed to git.

Refs are mutable, like git branches, so objects are served with a short cache
TTL plus a per-deploy ?v= cache-buster on the docs side. Permanent
content-addressed copies are a release-time concern (the lockfile mechanism in
the unified parts plan), not a live-docs one.

CI runs this on every PR touching the harness sources, with SPACES_KEY /
SPACES_SECRET from repo secrets (a key scoped to the basically-docs bucket
only). Locally it reads ~/.config/basically/do-spaces.env like
docs/scripts/upload_image.py. Requires boto3.
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import sys
from pathlib import Path

import boto3

BUCKET = "basically-docs"
ENDPOINT = "https://nyc3.digitaloceanspaces.com"
PUBLIC_BASE = "https://img.basically.website"
PREFIX = "harness"
# Refs are mutable, so short TTL. The docs also append ?v=<commit> per deploy.
CACHE_CONTROL = "public, max-age=60"
CREDS_FILE = Path.home() / ".config" / "basically" / "do-spaces.env"
OUT = Path(__file__).resolve().parent / "out"

# A render is ~2.3 MB / 23 files. These caps exist so a runaway render (or a
# prompted-into-mischief CI run) can't stuff the bucket; raise them when a
# legitimate render actually grows past them.
MAX_TOTAL_BYTES = 25 * 1024 * 1024
MAX_FILES = 60


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


def rendered_files() -> list[Path]:
    if not OUT.is_dir():
        sys.exit(f"{OUT} does not exist: run build-harness.sh first")
    files = sorted(p for p in OUT.iterdir() if p.is_file() and not p.name.startswith("."))
    if not files:
        sys.exit(f"{OUT} is empty: run build-harness.sh first")
    if len(files) > MAX_FILES:
        sys.exit(f"refusing: {len(files)} files exceeds the {MAX_FILES}-file cap")
    total = sum(p.stat().st_size for p in files)
    if total > MAX_TOTAL_BYTES:
        sys.exit(f"refusing: {total} bytes exceeds the {MAX_TOTAL_BYTES}-byte cap")
    return files


def content_type(p: Path) -> str:
    if p.suffix == ".yml":
        return "text/yaml; charset=utf-8"
    if p.suffix == ".tsv":
        return "text/tab-separated-values; charset=utf-8"
    if p.suffix == ".gv":
        return "text/plain; charset=utf-8"
    guessed, _ = mimetypes.guess_type(p.name)
    return guessed or "application/octet-stream"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ref",
        required=True,
        help="git ref to publish under (branch name; CI passes github.head_ref or github.ref_name)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would upload, touch nothing"
    )
    args = parser.parse_args()

    ref = args.ref.strip().strip("/")
    if not ref or ref == "HEAD":
        sys.exit(f"--ref {args.ref!r} is not a usable ref")

    files = rendered_files()
    base = f"{PUBLIC_BASE}/{PREFIX}/{ref}"

    if args.dry_run:
        for p in files:
            print(f"  would upload {PREFIX}/{ref}/{p.name}")
        print(f"\nbase: {base}")
        return 0

    key_id, secret = load_creds()
    s3 = boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
    )

    for p in files:
        s3.put_object(
            Bucket=BUCKET,
            Key=f"{PREFIX}/{ref}/{p.name}",
            Body=p.read_bytes(),
            ACL="public-read",
            ContentType=content_type(p),
            CacheControl=CACHE_CONTROL,
        )

    print(f"uploaded {len(files)} files to {PREFIX}/{ref}/")
    print(f"base: {base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
