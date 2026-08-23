"""Upload a docs video to the asset service and print the block to paste.

Photos go to the basically-docs bucket via upload_image.py. Video does not:
a phone clip is tens of megabytes of the wrong codec at the wrong size, and
serving that as-is is not an option. The asset service takes the original,
keeps it, and derives what a browser should actually download -- an MP4
ladder plus a poster frame -- so a page shows a still and fetches nothing
until someone presses play.

Usage:

    python3 docs/scripts/upload_video.py ~/Downloads/IMG_7204.MOV \\
        assembly/control-board-housing/pressing-the-plunger

Every URL it prints carries a content hash, exactly like an image URL, so it
can be cached forever and a re-encode is always a new URL.

Transcoding takes minutes and the service runs one job at a time, so this
waits. Interrupting it is safe: the upload is content-addressed, so running
it again picks up the same asset rather than making a second one.

Credentials come from ~/.config/asset-service/*.env or the environment
(ASSET_SERVICE_URL / ASSET_SERVICE_TOKEN).
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.request
from pathlib import Path

NAMESPACE = "sorter-docs"
UA = "sorter-v2-docs/1.0 (+https://github.com/basicallysource/sorter-v2)"
CONFIG_DIR = Path.home() / ".config" / "asset-service"
POLL_LIMIT_S = 1800


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
        sys.exit(f"missing ASSET_SERVICE_URL/ASSET_SERVICE_TOKEN (set env vars or {CONFIG_DIR}/*.env)")
    return url.rstrip("/"), token


def api(base: str, token: str, path: str, body: bytes | None = None, ctype: str | None = None):
    req = urllib.request.Request(base + path, data=body, method="POST" if body else "GET")
    req.add_header("User-Agent", UA)
    req.add_header("Authorization", "Bearer " + token)
    if ctype:
        req.add_header("Content-Type", ctype)
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def paste_block(manifest: dict) -> str:
    """The <video> element for a docs page. Sources smallest-first so a phone
    takes the small encode; the poster is what the page actually downloads."""
    rends = manifest.get("renditions", [])
    poster = next((r for r in rends if r["name"] == "poster"), None)
    mp4s = sorted(
        (r for r in rends if (r.get("content_type") == "video/mp4" and r["name"] != "original")),
        key=lambda r: r.get("width") or 0,
    )
    if not mp4s:
        return "(no mp4 renditions came back -- check the service)"
    lines = ['<div class="video-embed-self">', "  <video controls preload=\"none\" playsinline"]
    if poster:
        lines[-1] += f'\n    poster="{poster["url"]}"'
    w, h = mp4s[-1].get("width"), mp4s[-1].get("height")
    if w and h:
        lines[-1] += f'\n    width="{w}" height="{h}"'
    lines[-1] += ">"
    for r in mp4s:
        lines.append(f'    <source src="{r["url"]}" type="video/mp4">')
    lines += ["  </video>", "</div>"]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("original", type=Path, help="path to the full-resolution video")
    ap.add_argument("dest", help="path to refer to it by, e.g. assembly/<page>/<name>")
    args = ap.parse_args()

    if not args.original.is_file():
        sys.exit(f"not a file: {args.original}")
    base, token = load_creds()
    data = args.original.read_bytes()
    ctype = mimetypes.guess_type(args.original.name)[0] or "video/mp4"
    name = args.dest.replace("/", "-") + args.original.suffix.lower()

    print(f"uploading {len(data) / 1e6:.1f} MB as {name} ...")
    m = api(base, token, f"/v1/assets?namespace={NAMESPACE}&filename={name}", body=data, ctype=ctype)
    key = m["key"]

    waited = 0
    while m.get("renditions_status") == "pending":
        if waited >= POLL_LIMIT_S:
            sys.exit(f"no renditions after {POLL_LIMIT_S}s. Re-run to keep waiting; the upload is already done.")
        step = 10 if waited < 120 else 30
        time.sleep(step)
        waited += step
        print(f"  transcoding ... {waited}s", end="\r", flush=True)
        m = api(base, token, "/v1/assets/" + key)
    print(f"  renditions ready after {waited}s      ")

    for r in m.get("renditions", []):
        print(f"  {r['name']:<12} {r.get('width')}x{r.get('height')}  {r['url']}")
    print("\nPaste this into the page:\n")
    print(paste_block(m))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
