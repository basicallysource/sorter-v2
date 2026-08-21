#!/usr/bin/env python3
"""Verify every bucket URL the site ships actually serves the real bytes.

This exists because a broken asset is invisible to every other check we run.
The bucket is content-addressed, so a wrong URL is not a 404 -- it is a 200
with the wrong bytes. When slicer/images/** was briefly LFS-tracked, CI hashed
and uploaded 130-byte pointer stubs; every URL looked healthy, returned 200
with Content-Type: image/png, and rendered as a broken image on production.

So status codes alone prove nothing here. Images must return a real PNG/JPEG
magic number; STLs, plates, and the all-parts bundle must be reachable, larger
than a pointer stub, and not LFS pointer text. Since the repo no longer holds
any binary serving copies, this is also the check that catches "the generated
data references bytes nobody uploaded" -- e.g. a fork PR (no bucket
credentials in CI) adding a part.

    python scripts/check_bucket_urls.py

Checks src/lib/data/parts.generated.json and plates.generated.json. With a
file argument it instead regex-scans that file for image URLs, so an
`image_url` edit to slicer/parts.json can be checked without invoking the
slicer:

    python scripts/check_bucket_urls.py slicer/parts.json

Exits non-zero listing every URL that fails.
"""
import concurrent.futures
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PARTS = REPO / "src/lib/data/parts.generated.json"
PLATES = REPO / "src/lib/data/plates.generated.json"

# An asset smaller than this is not real; the LFS pointer stubs that broke
# production were 130 bytes.
MIN_BYTES = 1024
IMAGE_MAGIC = {b"\x89PNG\r\n\x1a\n": "png", b"\xff\xd8\xff": "jpeg"}
LFS_POINTER = b"version https://git-lfs"


def collect_urls() -> dict[str, str]:
    """Every http(s) bucket URL in the generated data -> its kind."""
    urls: dict[str, str] = {}

    def add(u, kind):
        if isinstance(u, str) and u.startswith("http"):
            urls[u] = kind

    parts = json.loads(PARTS.read_text())
    add(parts.get("settings", {}).get("all_parts_zip"), "binary")
    for p in parts.get("parts", []):
        add(p.get("stl"), "binary")
        add(p.get("render"), "image")
        for v in p.get("versions") or []:
            add(v.get("stl"), "binary")
            add(v.get("render"), "image")
    for h in parts.get("hardware", []):
        add(h.get("image"), "image")
    for f in parts.get("families", []):
        add(f.get("image"), "image")
    for c in parts.get("changes", []):
        for im in c.get("images") or []:
            add(im.get("url"), "image")

    if PLATES.exists():
        for plate in json.loads(PLATES.read_text()):
            add(plate.get("download"), "binary")
            for t in plate.get("thumbs") or []:
                add(t, "image")

    return urls


def check(item: tuple[str, str]) -> tuple[str, str | None]:
    """Return (url, error) -- error is None when the URL serves real bytes."""
    url, kind = item
    try:
        req = urllib.request.Request(url, headers={"Range": "bytes=0-1023"})
        with urllib.request.urlopen(req, timeout=30) as r:
            head = r.read()
            # 206 gives the range; a 200 means the whole (small) object came back.
            total = r.headers.get("Content-Range")
            size = int(total.split("/")[-1]) if total else len(head)
    except urllib.error.HTTPError as e:
        return url, f"HTTP {e.code}"
    except Exception as e:  # network/DNS/timeout
        return url, f"unreachable: {type(e).__name__}"

    if head.startswith(LFS_POINTER):
        return url, (
            "serves a Git LFS pointer, not real content -- something hashed "
            "and uploaded an unmaterialized LFS file"
        )
    if size < MIN_BYTES:
        return url, f"only {size} bytes -- not a real asset"
    if kind == "image" and not any(head.startswith(m) for m in IMAGE_MAGIC):
        return url, f"bad magic bytes {head[:8]!r} -- not a PNG or JPEG"
    return url, None


def main() -> None:
    if len(sys.argv) > 1:
        # lint one file's image URLs directly (works on slicer/parts.json)
        blob = Path(sys.argv[1]).read_text()
        found = re.findall(r'"image(?:_url)?":\s*"(https?://[^"]+)"', blob)
        urls = {u: "image" for u in found}
    else:
        urls = collect_urls()
    if not urls:
        sys.exit("no bucket URLs found -- the schema changed?")

    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        results = list(ex.map(check, sorted(urls.items())))

    bad = [(u, e) for u, e in results if e]
    kinds = {}
    for _, k in urls.items():
        kinds[k] = kinds.get(k, 0) + 1
    summary = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
    print(f"checked {len(urls)} bucket URLs ({summary})")
    if not bad:
        print("all serve real bytes")
        return

    print(f"\n{len(bad)} broken:", file=sys.stderr)
    for u, e in bad:
        print(f"  {u}\n    {e}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
