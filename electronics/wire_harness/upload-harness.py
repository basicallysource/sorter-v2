"""Publish the rendered harness to the assets bucket and print the URLs to paste.

    ./electronics/wire_harness/build-harness.sh
    ./electronics/wire_harness/upload-harness.py

Same contract as docs/scripts/upload_image.py, which is the convention every
other asset in this bucket already follows: the tool puts bytes in the bucket
and hands back URLs, and those URLs are pasted into the content as literal
strings. A drawing's URL changes in the commit that changes the drawing, right
next to it, and reviewing a harness change shows the new URLs in the diff.

Nothing is ever overwritten. Every object's name carries a hash of its own
bytes:

    harness/power.a1b2c3d4e5.png

so a re-render of an unchanged drawing lands on the name it already has (and
uploads nothing), and a changed drawing gets a name nothing has ever served.
That is what makes the year-long `immutable` cache header on these objects
true, and it is what the previous scheme got wrong: it wrote every render to
harness/<ref>/power.png, overwriting in place, and left the docs to invent a
?v=<docs build sha> query that named bytes which might not exist yet. A reader
who loaded a page inside that window pinned a stale or half-uploaded drawing
in their browser cache for a year.

Renders are not reproducible across graphviz versions -- the version shifts
glyph positions, so it is part of the output -- which makes CI the canonical
renderer (it pins graphviz 2.42.2 and WireViz 0.4.1). Publishing from a local
render on a different graphviz produces correct but non-canonical bytes, and
the hash will disagree with what CI would have produced. Use
`gh workflow run harness.yml` and paste from the job log unless you know why
you want otherwise.

Credentials come from ~/.config/basically/do-spaces.env (SPACES_KEY /
SPACES_SECRET) or the environment. Requires boto3.
"""

from __future__ import annotations

import argparse
import hashlib
import mimetypes
import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

BUCKET = "basically-docs"
ENDPOINT = "https://nyc3.digitaloceanspaces.com"
PUBLIC_BASE = "https://img.basically.website"
PREFIX = "harness"
# Honest now: the name contains a hash of the bytes, so the bytes behind a URL
# can never change. Nothing else in this pipeline may reintroduce a mutable
# name under this cache header.
CACHE_CONTROL = "public, max-age=31536000, immutable"
HASH_CHARS = 10
CREDS_FILE = Path.home() / ".config" / "basically" / "do-spaces.env"
OUT = Path(__file__).resolve().parent / "out"

# A render is ~2.3 MB / 23 files. These caps exist so a runaway render (or a
# prompted-into-mischief CI run) can't stuff the bucket; raise them when a
# legitimate render actually grows past them.
MAX_TOTAL_BYTES = 25 * 1024 * 1024
MAX_FILES = 60

# The zip is the only artifact not named after a drawing.
ZIP_NAME = "sorter-v2-harness-rfq.zip"


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


def hashed_key(name: str, body: bytes) -> str:
    """harness/power.bom.tsv + bytes -> harness/power.<hash>.bom.tsv

    The hash goes after the first dot rather than before the last one so that
    the whole suffix chain stays intact: `.bom.tsv` is how the docs page finds
    a BOM and how a vendor knows what they were sent.
    """
    stem, _, rest = name.partition(".")
    digest = hashlib.sha256(body).hexdigest()[:HASH_CHARS]
    return f"{PREFIX}/{stem}.{digest}.{rest}" if rest else f"{PREFIX}/{stem}.{digest}"


# What the docs page links per drawing. `.gv` is uploaded too (it is what the
# PDF is rendered from and it is occasionally worth diffing) but nothing links
# it, and rfq.txt is a hand-written source that ships inside the zip rather
# than a drawing of its own. Neither belongs in the data file.
LINKED = ("png", "svg", "pdf", "html", "bom.tsv", "yml")


def by_drawing(urls: dict[str, str]) -> dict[str, dict[str, str]]:
    """Group the rendered URLs by drawing, keeping only what the docs link.

    A stem counts as a drawing only if it produced a PNG, which is what makes
    rfq.txt fall out: WireViz renders a drawing to the whole set at once, so
    anything without one is not a drawing.
    """
    grouped: dict[str, dict[str, str]] = {}
    for name, url in urls.items():
        if name == ZIP_NAME:
            continue
        stem, _, rest = name.partition(".")
        if rest in LINKED:
            grouped.setdefault(stem, {})[rest] = url
    return {stem: exts for stem, exts in grouped.items() if "png" in exts}


def paste_block(urls: dict[str, str]) -> str:
    """The YAML to paste into docs/src/liquid/_data/harness.yml.

    Printed rather than written: the data file also carries titles, captions
    and `of:` relationships that only a person edits, and a script that
    rewrote it in place would be one more derived-file-in-git to keep honest.
    """
    drawings = by_drawing(urls)
    lines = [f"zip: {urls[ZIP_NAME]}", "", "# Paste each drawing's block under its entry in `drawings:`."]
    for stem in sorted(drawings):
        lines.append(f"  - name: {stem}")
        for ext in LINKED:
            url = drawings[stem].get(ext)
            if url:
                lines.append(f"    {ext.replace('.', '_')}: {url}")
    return "\n".join(lines)


def check(data_file: Path, urls: dict[str, str]) -> int:
    """Fail unless the data file's literal URLs are the ones this render produced.

    Without this the paste is optional, and a drawing change that forgot it
    would publish new objects while the page kept serving the old ones -- the
    same silent staleness the overwrite scheme had, just with a different
    shape. CI runs it on every harness change.
    """
    import yaml  # a wireviz dependency; CI has it wherever this runs

    doc = yaml.safe_load(data_file.read_text()) or {}
    drawings = by_drawing(urls)
    want = {ZIP_NAME: urls[ZIP_NAME]}
    have = {ZIP_NAME: doc.get("zip")}
    listed: set[str] = set()
    for entry in doc.get("drawings") or []:
        stem = entry.get("name")
        listed.add(stem)
        for ext, url in drawings.get(stem, {}).items():
            want[f"{stem}.{ext}"] = url
            have[f"{stem}.{ext}"] = entry.get(ext.replace(".", "_"))

    wrong = sorted(n for n in want if have.get(n) != want[n])
    missing = sorted(set(drawings) - listed)
    if not wrong and not missing:
        print(f"{data_file} matches this render ({len(want)} URLs)")
        return 0

    if wrong:
        print(f"::error::{data_file} does not point at this render", file=sys.stderr)
        for n in wrong:
            print(f"  {n}\n    in the data file: {have.get(n)}\n    this render:      {want[n]}", file=sys.stderr)
    if missing:
        print(f"::error::rendered but not listed in {data_file}: {', '.join(missing)}", file=sys.stderr)
    print("\nPaste this into docs/src/liquid/_data/harness.yml:\n", file=sys.stderr)
    print(paste_block(urls), file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would upload, touch nothing"
    )
    parser.add_argument(
        "--check",
        type=Path,
        metavar="HARNESS_YML",
        help="upload nothing; fail unless this data file's URLs match the render in out/",
    )
    args = parser.parse_args()

    files = rendered_files()
    bodies = {p.name: p.read_bytes() for p in files}
    keys = {name: hashed_key(name, body) for name, body in bodies.items()}
    urls = {name: f"{PUBLIC_BASE}/{key}" for name, key in keys.items()}

    if ZIP_NAME not in bodies:
        sys.exit(f"refusing: {ZIP_NAME} missing from {OUT}; run build-harness.sh first")

    if args.check:
        return check(args.check, urls)

    if args.dry_run:
        for name in sorted(keys):
            print(f"  would upload {keys[name]}")
        print()
        print(paste_block(urls))
        return 0

    key_id, secret = load_creds()
    s3 = boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
    )

    uploaded = 0
    for name in sorted(bodies):
        key = keys[name]
        # A name already in the bucket holds these exact bytes -- the name is a
        # hash of them. Skipping keeps a re-render of an unchanged drawing free
        # and makes it structurally impossible for this script to overwrite.
        try:
            s3.head_object(Bucket=BUCKET, Key=key)
            continue
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
                raise
        s3.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=bodies[name],
            ACL="public-read",
            ContentType=content_type(Path(name)),
            CacheControl=CACHE_CONTROL,
        )
        uploaded += 1

    print(f"uploaded {uploaded} new object(s); {len(bodies) - uploaded} already present\n")
    print(paste_block(urls))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
