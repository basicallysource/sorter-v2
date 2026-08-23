"""Print the <video> block for a clip already in the asset service.

Video does not go in the images bucket. A phone clip is tens of megabytes of
the wrong codec at the wrong size, and no page should ask a reader to download
that to see two seconds of something clicking. It goes to the asset service
(`assets.basically.website`), which keeps the original and holds an MP4 ladder
plus a poster frame beside it.

Upload it with the asset-service CLI, not with a script here, because the
encoding rules live in that repo (`internal/derive`) and a second copy of them
would drift:

    asset-service upload --derive --namespace sorter-docs <file>

`--derive` matters. The service queues derivation rather than doing it, and
the queue is only worked while someone runs `asset-service work` somewhere
(hive-prod is pinned ASSET_RENDITIONS=false on purpose: ffmpeg next to prod
hive is what that flag exists to prevent). With no worker up, an upload sits
`renditions_status: pending` forever and you get no MP4 and no poster.
`--derive` does the encode on this machine and uploads the results, so it
never depends on a worker running.

Then run this to turn the manifest into markup:

    python3 docs/scripts/video_embed.py sorter-docs/pressing-the-plunger-f79347e59ff9.mov

Credentials are ASSET_SERVICE_URL / ASSET_SERVICE_TOKEN, from the environment
or ~/.config/asset-service/*.env.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

UA = "sorter-v2-docs/1.0 (+https://github.com/basicallysource/sorter-v2)"
CONFIG_DIR = Path.home() / ".config" / "asset-service"


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


def manifest(base: str, token: str, key: str) -> dict:
    req = urllib.request.Request(f"{base}/v1/assets/{key}")
    req.add_header("User-Agent", UA)
    req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def block(m: dict) -> str:
    rends = m.get("renditions", [])
    poster = next((r for r in rends if r.get("content_type", "").startswith("image/")), None)
    # Tell the poster from the encodes by content_type, not by name.
    mp4s = sorted(
        (r for r in rends if r.get("content_type") == "video/mp4"),
        key=lambda r: r.get("width") or 0,
    )
    if not mp4s:
        sys.exit("no mp4 renditions on this asset. Did you upload with --derive?")

    lines = ['<div class="video-embed-self">', '  <video controls preload="none" playsinline']
    if poster:
        lines.append(f'    poster="{poster["url"]}"')
        # Size the box from the POSTER, not from an encode. A phone shoots
        # portrait into a landscape frame plus a rotation flag: the MP4 reports
        # 1920x1080 and plays 1080x1920, while the poster is a still with the
        # rotation already applied. Reserving the encode's shape would leave a
        # landscape hole that the video then does not fill.
        if poster.get("width") and poster.get("height"):
            lines.append(f'    width="{poster["width"]}" height="{poster["height"]}"')
    lines.append("  >")
    for r in mp4s:
        lines.append(f'    <source src="{r["url"]}" type="video/mp4">')
    lines += ["  </video>", "</div>"]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("key", help="asset key, e.g. sorter-docs/name-<hash>.mov")
    args = ap.parse_args()
    base, token = load_creds()
    m = manifest(base, token, args.key)
    if m.get("renditions_status") != "ready":
        print(f"renditions_status is {m.get('renditions_status')!r}, not 'ready'.\n"
              "Nothing works the queue unless `asset-service work` is running; "
              "re-upload with --derive to encode locally.", file=sys.stderr)
    for r in m.get("renditions", []):
        print(f"  {r['name']:<10} {r.get('content_type'):<18} {r.get('width')}x{r.get('height')}", file=sys.stderr)
    print(block(m))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
