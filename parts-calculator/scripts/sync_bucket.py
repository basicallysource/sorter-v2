#!/usr/bin/env python3
"""The bucket is the only home binary content has; this script feeds it.

Every file is stored under a name that identifies itself:

    stl/<part>-<uid>-<hash8>.stl         render/<part>-<hash8>.png
    img/<name>-<hash8>.<ext>             plate/<name>-<hash8>.3mf   ...

The hash fragment makes the address a function of the bytes (identical bytes
are never stored twice; a revision stays downloadable forever), the human name
makes a downloaded file readable, and an STL additionally carries the `uid` of
the part version it is -- grep that uid (or the hash fragment) in
catalog/parts.json and you have the exact version of the thing in your hand.
The uid is never minted here: it names the design revision, it is on the
part's entry before the STL exists (catalog/mint_uid.py), and a re-export of
the same design is new bytes under the same uid. Uploads happen only if the
key is absent. Nothing binary is committed to git, anywhere, ever. (Keys were
bare <sha256><ext> before 2026-08-21; those objects stay on the bucket so URLs
in old commits keep serving.)

Two jobs:
  * sync (no args): upload what generate.py freshly produced under build/
    (renders, plate thumbnails, the all-parts zip).
  * --upload FILE...: author an asset -- an STL master, a plate 3mf, a product
    image, a picture of a part or assembly -- straight onto the bucket, printing the pin line to paste into
    catalog/parts.json or catalog/plates.json.

Credentials, in order of precedence:
  1. env: DO_SPACES_KEY / DO_SPACES_SECRET
  2. file: ~/.config/do-spaces/sorter-v2-parts.env  (KEY=VALUE lines)

Usage:
  python scripts/sync_bucket.py --dry-run     # show what would upload
  python scripts/sync_bucket.py               # upload missing
  python scripts/sync_bucket.py --upload part.stl plate.3mf photo.jpg
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

BUCKET = "sorter-v2-parts"
REGION = "nyc3"
ENDPOINT = f"https://{REGION}.digitaloceanspaces.com"
# CDN endpoint (edge-cached). The origin hostname -- same URL without `.cdn.`
# -- also serves these objects permanently, so switching between the two is
# never a breaking change.
# Public URLs go through the docs img worker (img.basically.website,
# docs/scripts/img-worker/), which mounts this bucket at /parts/* -- one public
# hostname for every asset, the whole prefix cached immutable since every
# filename carries a hash of the bytes. (Not the asset service -- that does not
# exist yet; this is its precursor.) The bucket's own CDN endpoint still
# serves, so URLs in old commits never break.
PUBLIC_BASE = os.environ.get("DO_SPACES_PUBLIC_BASE", "https://img.basically.website/parts")

# Directories whose contents get pushed. Keep this list narrow: only things
# the website serves or that pin a revision. Renders (1.4M total) stay as
# normal git blobs -- they are small and the site wants them at build time.
# Everything here lives in gitignored build/, freshly produced by generate.py:
# renders and plate thumbnails it generated this run, the uid-stamped STL
# variants (catalog/engrave.py), and the all-parts zip.
# Files that were memoized (already uploaded by an earlier run) are not on
# disk, so a sync only pushes new bytes. Masters and plates never appear:
# they are authored straight onto the bucket with `--upload` and pinned by
# hash in catalog/parts.json / plates.json, so their bytes exist before any
# regen needs them.
SOURCES = [
    ("catalog/build/renders", "*.png", "render"),
    ("catalog/build/plate-thumbs", "*.png", "thumb"),
    ("catalog/build/stamped", "*.stl", "stl"),
    ("catalog/build/bundle", "all-parts*.zip", "bundle"),
]

CONTENT_TYPES = {".stl": "model/stl", ".3mf": "model/3mf", ".zip": "application/zip",
                 ".png": "image/png", ".jpg": "image/jpeg", ".ttf": "font/ttf"}

# How much of the sha256 rides in a filename. Enough to never collide across
# a few hundred objects and to be uniquely greppable in parts.json.
HASH_CHARS = 8


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return s or "asset"


def named_key(prefix: str, name: str, digest: str, suffix: str) -> str:
    return f"{prefix}/{slug(name)}-{digest[:HASH_CHARS]}{suffix}"


def stl_url(name: str, uid: str, digest: str) -> str:
    """stl/<name>-<uid>-<hash8>.stl -- the uid is the parts.json lookup key."""
    return f"{PUBLIC_BASE}/stl/{slug(name)}-{uid}-{digest[:HASH_CHARS]}.stl"


def uid_for(part_id: str) -> str:
    """The uid of a part's current version, read off its catalog/parts.json entry."""
    manifest = json.loads((REPO / "catalog" / "parts.json").read_text())
    for part in manifest["parts"]:
        if part["id"] == part_id:
            if not part.get("uid"):
                sys.exit(f"{part_id} has no uid in catalog/parts.json -- "
                         "mint one (catalog/mint_uid.py) before uploading")
            return part["uid"]
    sys.exit(f"no part {part_id!r} in catalog/parts.json -- write its entry (with a "
             "minted uid) before uploading, or pass --uid to key the file explicitly")

# Images render in <img> tags; everything else is a download.
INLINE_SUFFIXES = {".png", ".jpg"}

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


def artifact_url(path: str | Path, prefix: str = "stl", name: str | None = None) -> str:
    """Public URL for a local file: <prefix>/<name>-<hash8><ext>.

    Deliberately does NOT consult the bucket or the manifest: the address is a
    function of the bytes (plus the human name), so the generator can emit
    correct URLs before an upload has happened. sync_bucket.py's only job is
    making sure the bytes are actually there. `name` defaults to the file's
    own stem, which is already the part/plate id for everything under build/.
    """
    p = Path(path)
    return f"{PUBLIC_BASE}/{named_key(prefix, name or p.stem, sha256(p), p.suffix)}"


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
        # The browser names a download after this header, not the URL, so it
        # is always the KEY's basename: a downloaded STL must read
        # <part>-<uid>-<hash8>.stl, and the slicer project made from it
        # inherits that name. Images stay inline so <img> and open-in-tab
        # both behave.
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


def upload_loose(paths: list[str], uid: str | None = None) -> None:
    """Author an asset straight onto the bucket and print the line to paste.

    This is the ONLY way binary content enters the system -- nothing binary is
    committed. The prefix and the paste-line follow from the file type:

      .stl    -> stl/<part>-<uid>-<hash8>.stl  "stl_hash": "<sha>"    (parts.json)
      .3mf    -> plate/<name>-<hash8>.3mf      "hash": "<sha>"        (plates.json)
      .ttf    -> font/<name>-<hash8>.ttf       FONT_URL + FONT_SHA    (catalog/engrave.py)
      images  -> img/<name>-<hash8>.<ext>      "image_url": "<url>"   (parts.json),
                                               or an `images` entry {url, alt}

    An STL is named <part-id>.stl and keyed under that part's uid from
    parts.json, so the entry exists before the upload; `uid` overrides the
    lookup (a file not named for its part, or a superseded version).
    """
    s3 = s3_client()
    for raw in paths:
        p = Path(raw).resolve()
        if not p.is_file():
            sys.exit(f"not a file: {p}")
        # sha256() refuses LFS pointers, so a stub can't be published here either.
        digest = sha256(p)
        suffix = p.suffix.lower()
        prefix = {".stl": "stl", ".3mf": "plate", ".ttf": "font"}.get(suffix, "img")
        if prefix == "stl":
            key = f"stl/{slug(p.stem)}-{uid or uid_for(slug(p.stem))}-{digest[:HASH_CHARS]}{suffix}"
        else:
            key = named_key(prefix, p.stem, digest, suffix)
        try:
            s3.head_object(Bucket=BUCKET, Key=key)
            print(f"  already on the bucket  {p.name}")
        except Exception:
            s3.upload_file(str(p), BUCKET, key, ExtraArgs=upload_args(Path(key).name))
            print(f"  uploaded  {p.name}  ({p.stat().st_size / 1e6:.1f} MB)")
        if prefix == "stl":
            print(f'    "stl_hash": "{digest}"')
        elif prefix == "plate":
            print(f'    "hash": "{digest}"')
        elif prefix == "font":
            print(f'    FONT_URL = "{PUBLIC_BASE}/{key}"\n    FONT_SHA = "{digest}"')
        else:
            url = f"{PUBLIC_BASE}/{key}"
            print(f'    "image_url": "{url}"')
            print(f'    or in an images list:  {{ "url": "{url}", "alt": "<what it shows>" }}')


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
                    "key": named_key(prefix, path.stem, digest, path.suffix),
                }
            )
    return found


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only, upload nothing")
    ap.add_argument("--set-cors", action="store_true", help="apply the CORS policy and exit")
    ap.add_argument("--upload", nargs="+", metavar="FILE",
                    help="author asset(s) straight onto the bucket and print the "
                         "pin line to paste (stl_hash for .stl, hash for .3mf, "
                         "image_url for images); files are never copied into the repo")
    ap.add_argument("--uid", metavar="UID",
                    help="with --upload: key an STL under this uid instead of looking "
                         "it up by the file's name in catalog/parts.json")
    args = ap.parse_args()

    if args.upload:
        upload_loose(args.upload, uid=args.uid)
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
            str(REPO / f["path"]), BUCKET, f["key"], ExtraArgs=upload_args(Path(f["key"]).name)
        )
        print(f"  uploaded {f['name']:<44} {f['size']/1e6:6.1f} MB")
        uploaded += 1

    verb = "would upload" if args.dry_run else "uploaded"
    print(f"\n{verb} {uploaded}, already present {skipped}")


if __name__ == "__main__":
    main()
