"""Publish the rendered harness to the asset service and print the URLs to paste.

    ./electronics/wire_harness/build-harness.sh
    ./electronics/wire_harness/upload-harness.py

Same contract as docs/scripts/upload_image.py, which is the convention every
asset follows now: the tool puts bytes in the asset service
(`assets.basically.website`, namespace `sorter-harness`) and hands back URLs,
and those URLs are pasted into the content as literal strings. A drawing's URL
changes in the commit that changes the drawing, right next to it, and
reviewing a harness change shows the new URLs in the diff.

Nothing is ever overwritten: the service names every object after a hash of
its own bytes, so a re-render of an unchanged drawing lands on the name it
already has (a free no-op), and a changed drawing gets a name nothing has ever
served. That is what makes the year-long `immutable` cache header true.

One nuance the service adds: a PNG is an image, and the service never
publishes an image's uploaded file directly -- pages get a metadata-free copy
under its own name. So the pasteable URL for a PNG is not derivable from the
bytes here; it is read off the asset's manifest. Everything else (svg, pdf,
html, tsv, yml, zip) is served as uploaded.

Renders are not reproducible across graphviz versions -- the version shifts
glyph positions, so it is part of the output -- which makes CI the canonical
renderer (it pins graphviz 2.42.2 and WireViz 0.4.1). Publishing from a local
render on a different graphviz produces correct but non-canonical bytes, and
the URLs will disagree with what CI would have produced. Use
`gh workflow run harness.yml` and paste from the job log unless you know why
you want otherwise.

Credentials are ASSET_SERVICE_URL / ASSET_SERVICE_TOKEN, from the environment
or ~/.config/asset-service/*.env. `--check` needs no credentials at all: it
reads public manifests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SERVICE = os.environ.get("ASSET_SERVICE_URL", "https://assets.basically.website").rstrip("/")
NAMESPACE = "sorter-harness"
HASH_CHARS = 12  # the service's assets.HashChars; how much digest is in a key
CONFIG_DIR = Path.home() / ".config" / "asset-service"
UA = "sorter-v2-harness/1.0 (+https://github.com/basicallysource/sorter-v2)"
OUT = Path(__file__).resolve().parent / "out"

# A render is ~2.3 MB / 23 files. These caps exist so a runaway render (or a
# prompted-into-mischief CI run) can't stuff the store; raise them when a
# legitimate render actually grows past them.
MAX_TOTAL_BYTES = 25 * 1024 * 1024
MAX_FILES = 60

# The zip is the only artifact not named after a drawing.
ZIP_NAME = "sorter-v2-harness-rfq.zip"


def load_token() -> str:
    env: dict[str, str] = {}
    for path in sorted(CONFIG_DIR.glob("*.env")) if CONFIG_DIR.is_dir() else []:
        for line in path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip())
    token = os.environ.get("ASSET_SERVICE_TOKEN") or env.get("ASSET_SERVICE_TOKEN")
    if not token:
        sys.exit(f"missing ASSET_SERVICE_TOKEN (env or {CONFIG_DIR}/*.env)")
    return token


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


def asset_key(name: str, body: bytes) -> str:
    """The key the service will store these bytes under, computed its way:
    the filename minus its last extension, slugged, then twelve hex characters
    of the SHA-256, then the extension. `power.bom.tsv` becomes
    `power-bom-<hash>.tsv`."""
    ext = Path(name).suffix.lower()
    stem = name[: -len(ext)] if ext else name
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:64].strip("-")
    digest = hashlib.sha256(body).hexdigest()[:HASH_CHARS]
    return f"{NAMESPACE}/{slug}-{digest}{ext}"


def api(method: str, path: str, token: str | None = None, body: bytes | None = None,
        content_type_header: str | None = None) -> dict | None:
    req = urllib.request.Request(SERVICE + path, data=body, method=method)
    req.add_header("User-Agent", UA)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if content_type_header:
        req.add_header("Content-Type", content_type_header)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        detail = e.read().decode(errors="replace")[:300]
        sys.exit(f"{method} {path}: HTTP {e.code}: {detail}")


def published_url(manifest: dict, key: str) -> str:
    """What a page may reference: the manifest's own url, which for a PNG is
    the metadata-free copy and for everything else the file as uploaded."""
    url = manifest.get("url")
    if not url:
        sys.exit(f"{key}: no published form yet (renditions {manifest.get('renditions_status')})")
    return url


def wait_ready(key: str, token: str | None, manifest: dict) -> dict:
    deadline = time.monotonic() + 300
    while manifest.get("renditions_status") == "pending":
        if time.monotonic() > deadline:
            sys.exit(f"{key}: still pending after five minutes")
        time.sleep(2)
        manifest = api("GET", f"/v1/assets/{key}", token)
        if manifest is None:
            sys.exit(f"{key}: vanished while waiting for its renditions")
    return manifest


# What the docs page links per drawing. `.gv` is uploaded too (it is what the
# PDF is rendered from and it is occasionally worth diffing) but nothing links
# it, and rfq.txt is a hand-written source that ships inside the zip rather
# than a drawing of its own. Neither belongs in the data file.
LINKED = ("png", "svg", "pdf", "html", "bom.tsv", "yml")


def by_drawing(urls: dict[str, str]) -> dict[str, dict[str, str]]:
    """Group the published URLs by drawing, keeping only what the docs link.

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
    would publish new objects while the page kept serving the old ones. CI
    runs it on every harness change.
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
    keys = {name: asset_key(name, body) for name, body in bodies.items()}

    if ZIP_NAME not in bodies:
        sys.exit(f"refusing: {ZIP_NAME} missing from {OUT}; run build-harness.sh first")

    if args.dry_run:
        for name in sorted(keys):
            print(f"  would upload {keys[name]}")
        return 0

    if args.check:
        # Manifests are public; the render must already be uploaded (CI checks
        # right after publishing, so it always is).
        urls = {}
        for name in sorted(keys):
            manifest = api("GET", f"/v1/assets/{keys[name]}")
            if manifest is None:
                sys.exit(f"{keys[name]} is not in the asset service; run the upload first")
            urls[name] = published_url(wait_ready(keys[name], None, manifest), keys[name])
        return check(args.check, urls)

    token = load_token()
    urls = {}
    for name in sorted(bodies):
        query = urllib.parse.urlencode({"namespace": NAMESPACE, "filename": name})
        manifest = api("POST", f"/v1/assets?{query}", token, bodies[name], content_type(Path(name)))
        if manifest is None:
            sys.exit(f"{name}: upload returned nothing")
        manifest = wait_ready(manifest["key"], token, manifest)
        urls[name] = published_url(manifest, manifest["key"])
        print(f"  {manifest['key']}")

    print()
    print(paste_block(urls))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
