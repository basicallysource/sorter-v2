"""The asset service is the only home binary content has; this puts it there.

Every file is stored under a name that identifies itself. The service takes a
name and the bytes and builds the key from both:

    sorter-parts/<name>-<hash12>.<ext>

The hash fragment makes the address a function of the bytes (identical bytes
under the same name are never stored twice, and a revision stays downloadable
forever), and the human name makes a downloaded file readable. A part's master
is stored under the part's id, so its archived versions and candidates share
that name and are told apart by their hashes -- which are exactly the pins in
catalog/parts.json, so grepping the hash fragment of a file in your hand finds
the entry that produced it. An engraved download additionally carries the
`uid` of the part version stamped on it, because that name is cut into the
plastic: `<part>-<uid>-stamped-<face>-<hash12>.stl`.

Nothing binary is committed to git, anywhere, ever.

Two jobs:

  * as a library, for catalog/generate.py: publish() puts bytes in the service
    if they are not there yet and returns the URL the site may reference.
    pinned_url() answers the same question for content already pinned by hash
    in the catalog, without a network call at all.

  * --upload FILE...: author an asset -- an STL master, a plate 3mf, a product
    image, a picture of a part or assembly -- straight into the service,
    printing the pin line to paste into catalog/parts.json or
    catalog/plates.json.

An image is not published as the file that was uploaded: the service keeps
the original privately and publishes a copy of it with the camera's notes
(where you stood, when, what with) stripped out. So an image's URL is not a
function of the bytes on this machine and cannot be computed here -- it is
read back from the service. Everything else (STL, 3mf, zip, font) is served
exactly as uploaded.

Credentials are ASSET_SERVICE_URL / ASSET_SERVICE_TOKEN, from the environment
or ~/.config/asset-service/*.env. Only uploading needs them: an asset that is
already published is looked up anonymously, so a regeneration that changes
nothing runs without credentials.

Usage:
  python scripts/publish_assets.py --upload part.stl plate.3mf photo.jpg
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SERVICE = os.environ.get("ASSET_SERVICE_URL", "https://assets.basically.website").rstrip("/")
NAMESPACE = "sorter-parts"
# The service's assets.HashChars: how much digest rides in a key.
HASH_CHARS = 12
CONFIG_DIR = Path.home() / ".config" / "asset-service"
UA = "sorter-v2-parts/1.0 (+https://github.com/basicallysource/sorter-v2)"

CONTENT_TYPES = {".stl": "model/stl", ".3mf": "model/3mf", ".zip": "application/zip",
                 ".png": "image/png", ".jpg": "image/jpeg", ".ttf": "font/ttf"}
# What the service republishes rather than serving as uploaded.
STRIPPED = {".png", ".jpg"}

LFS_POINTER = b"version https://git-lfs"


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")[:64].strip("-")
    return s or "asset"


def asset_key(name: str, digest: str, suffix: str) -> str:
    """The key the service will store these bytes under, computed its way."""
    return f"{NAMESPACE}/{slug(name)}-{digest[:HASH_CHARS]}{suffix}"


def pinned_url(name: str, digest: str, suffix: str) -> str:
    """Where content already pinned by hash in the catalog is served.

    Deliberately does NOT consult the service: for everything that is served
    as uploaded, the address is a function of the pin, so the generator can
    emit correct URLs (and fetch a master it does not have) without asking
    anyone. Images are not pinned this way -- what is published for them is a
    copy this side cannot compute -- so this is only ever called for STLs,
    3mfs and the font.
    """
    if suffix in STRIPPED:
        raise ValueError(f"{suffix} is republished by the service; use publish()")
    return f"{SERVICE}/{asset_key(name, digest, suffix)}"


def stl_url(part_id: str, digest: str) -> str:
    """Where a part's STL is served, from the pin alone.

    Master, archived version and candidate all share the part's id -- one
    name, one per set of bytes -- so the hash in the key is what tells them
    apart, and it is the same hash catalog/parts.json pins."""
    return pinned_url(part_id, digest, ".stl")


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        first = True
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            # An unmaterialized LFS file hashes and uploads perfectly happily --
            # it is just 130 bytes of pointer text. The result is a valid-looking
            # content-addressed URL serving a stub, which the browser renders as
            # a broken image. Fail loudly instead of publishing the stub.
            if first and chunk[:40].startswith(LFS_POINTER):
                sys.exit(
                    f"{path} is an unmaterialized Git LFS pointer, not real content.\n"
                    "Run `git lfs pull` (or check out with lfs: true in CI) and retry."
                )
            first = False
            h.update(chunk)
    return h.hexdigest()


def load_token() -> str:
    env: dict[str, str] = {}
    for path in sorted(CONFIG_DIR.glob("*.env")) if CONFIG_DIR.is_dir() else []:
        for line in path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip())
    token = os.environ.get("ASSET_SERVICE_TOKEN") or env.get("ASSET_SERVICE_TOKEN")
    if not token:
        sys.exit(f"missing ASSET_SERVICE_TOKEN (env or {CONFIG_DIR}/*.env) -- "
                 "publishing new bytes needs credentials")
    return token


def api(method: str, path: str, token: str | None = None, body: bytes | None = None,
        ctype: str | None = None) -> dict | None:
    req = urllib.request.Request(SERVICE + path, data=body, method=method)
    req.add_header("User-Agent", UA)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        sys.exit(f"{method} {path}: HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")


def _settled(manifest: dict, key: str) -> dict:
    """Wait out the derivations, which is what an image's published copy is."""
    deadline = time.monotonic() + 600
    while manifest.get("renditions_status") == "pending":
        if time.monotonic() > deadline:
            sys.exit(f"{key}: the service has not finished with it after ten minutes")
        time.sleep(3)
        settled = api("GET", f"/v1/assets/{key}")
        if settled is None:
            sys.exit(f"{key}: vanished while waiting for its derived forms")
        manifest = settled
    if manifest.get("renditions_status") == "failed":
        sys.exit(f"{key}: the service could not derive anything from it")
    return manifest


def publish(path: str | Path, name: str | None = None) -> str:
    """Put these bytes in the service if they are not there, and return the
    URL the site may reference. `name` defaults to the file's own stem, which
    is already the part or plate id for everything the generator makes."""
    return _publish(path, name)[0]


def _publish(path: str | Path, name: str | None = None) -> tuple[str, bool]:
    """publish(), and whether this call is what put the bytes there."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix not in CONTENT_TYPES:
        sys.exit(f"{p}: nothing publishes a {suffix} file")
    name = name or p.stem
    key = asset_key(name, sha256(p), suffix)

    manifest = api("GET", f"/v1/assets/{key}")
    sent = manifest is None
    if sent:
        query = urllib.parse.urlencode({"namespace": NAMESPACE, "filename": name + suffix})
        manifest = api("POST", f"/v1/assets?{query}", load_token(),
                       p.read_bytes(), CONTENT_TYPES[suffix])
        if manifest is None or manifest["key"] != key:
            sys.exit(f"{p}: expected the service to store this as {key}, "
                     f"it said {manifest and manifest.get('key')}")
    if suffix in STRIPPED:
        manifest = _settled(manifest, key)
    url = manifest.get("url")
    if not url:
        sys.exit(f"{key}: the service has nothing publishable for it")
    return url, sent


def upload_loose(paths: list[str]) -> None:
    """Author an asset straight into the service and print the line to paste.

    This is the ONLY way binary content enters the system -- nothing binary is
    committed. The paste-line follows from the file type:

      .stl    "stl_hash": "<sha>"    (catalog/parts.json)
      .3mf    "hash": "<sha>"        (catalog/plates.json)
      .ttf    FONT_URL + FONT_SHA    (catalog/engrave.py)
      images  "image_url": "<url>"   (catalog/parts.json), or an entry in an
                                     `images` list: {url, alt}

    A master STL is named for its part, because the part's id is the name it
    is stored under; the hash tells its versions apart.
    """
    for raw in paths:
        p = Path(raw).resolve()
        if not p.is_file():
            sys.exit(f"not a file: {p}")
        digest = sha256(p)          # refuses LFS pointers, so no stub is ever published
        url, sent = _publish(p)
        what = "published" if sent else "already there"
        print(f"  {what:<14} {p.name}  ({p.stat().st_size / 1e6:.1f} MB)")
        suffix = p.suffix.lower()
        if suffix == ".stl":
            print(f'    "stl_hash": "{digest}"')
        elif suffix == ".3mf":
            print(f'    "hash": "{digest}"')
        elif suffix == ".ttf":
            print(f'    FONT_URL = "{url}"\n    FONT_SHA = "{digest}"')
        else:
            print(f'    "image_url": "{url}"')
            print(f'    or in an images list:  {{ "url": "{url}", "alt": "<what it shows>" }}')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--upload", nargs="+", metavar="FILE", required=True,
                    help="author asset(s) into the service and print the pin line to "
                         "paste (stl_hash for .stl, hash for .3mf, image_url for "
                         "images); files are never copied into the repo")
    args = ap.parse_args()
    upload_loose(args.upload)


if __name__ == "__main__":
    main()
