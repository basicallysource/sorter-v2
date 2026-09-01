"""Verify every asset URL the site ships actually serves the real bytes.

This exists because a broken asset is invisible to every other check we run.
Assets are content-addressed, so a wrong URL is not a 404 -- it is a 200 with
the wrong bytes. When catalog/images/** was briefly LFS-tracked, CI hashed and
uploaded 130-byte pointer stubs; every URL looked healthy, returned 200 with
Content-Type: image/png, and rendered as a broken image on production.

So status codes alone prove nothing here. Images must return a real PNG/JPEG
magic number; STLs, plates and the all-parts bundle must be reachable, larger
than a pointer stub, and not LFS pointer text. Since the repo no longer holds
any binary serving copies, this is also the check that catches "the generated
data references bytes nobody published" -- e.g. a fork PR (no credentials in
CI) adding a part.

It also fails on any mention of the two places assets used to be served from:
img.basically.website, the domain the parts calculator was the last thing
using, and the DO Space behind it, which a few components addressed directly
and so hid from a sweep for the domain alone. Neither is being kept alive, so
a URL naming either is a URL that will stop resolving.

    python scripts/check_asset_urls.py

Checks src/lib/data/catalog.generated.json (parts and plates). With a file
argument it instead regex-scans that file for image URLs, so an `image_url`
edit to catalog/parts.json can be checked without invoking the slicer:

    python scripts/check_asset_urls.py catalog/parts.json

Exits non-zero listing every URL that fails. Needs no credentials: everything
it reads is public.
"""
import concurrent.futures
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# A real UA: the service's zone 403s urllib's default Python-urllib/x.y
# (Browser Integrity Check), which is exactly how CI runs this.
UA = "sorter-v2-parts-check/1.0 (+https://github.com/basicallysource/sorter-v2)"
CATALOG = REPO / "src/lib/data/catalog.generated.json"

SERVICE = "https://assets.basically.website/"
# Both halves of the old arrangement: the public domain, and the bucket it
# fronted -- which some components used to reach straight past it.
RETIRED = ("img.basically.website", "sorter-v2-parts.nyc3.cdn.digitaloceanspaces.com")

# An asset smaller than this is not real; the LFS pointer stubs that broke
# production were 130 bytes.
MIN_BYTES = 1024
IMAGE_MAGIC = {b"\x89PNG\r\n\x1a\n": "png", b"\xff\xd8\xff": "jpeg"}
LFS_POINTER = b"version https://git-lfs"

# Where a URL could hide. Everything else under parts-calculator/ is either
# generated from these or not shipped.
SCANNED = ("*.py", "*.json", "*.svelte", "*.ts", "*.js", "*.md", "*.html", "*.yml")
SKIP_DIRS = {"node_modules", "build", ".svelte-kit", ".git"}


def collect_urls() -> dict[str, str]:
    """Every http(s) asset URL in the generated data -> its kind."""
    urls: dict[str, str] = {}

    def add(u, kind):
        if isinstance(u, str) and u.startswith("http"):
            urls[u] = kind

    def add_images(item):
        # the extra pictures of a thing, and of its versions and candidates
        for im in item.get("images") or []:
            add(im.get("url"), "image")
        for extra in ("versions", "candidates"):
            for sub in item.get(extra) or []:
                add_images(sub)

    parts = json.loads(CATALOG.read_text())
    add(parts.get("settings", {}).get("all_parts_zip"), "binary")
    add(parts.get("settings", {}).get("all_parts_plain_zip"), "binary")
    for p in parts.get("parts", []):
        add(p.get("stl"), "binary")
        add(p.get("render"), "image")
        add_images(p)
        for s in p.get("stamped") or []:
            add(s.get("stl"), "binary")
        for v in p.get("versions") or []:
            add(v.get("stl"), "binary")
            add(v.get("render"), "image")
        for c in p.get("candidates") or []:
            add(c.get("stl"), "binary")
            add(c.get("render"), "image")
            for s in c.get("stamped") or []:
                add(s.get("stl"), "binary")
    for h in parts.get("hardware", []):
        add(h.get("image"), "image")
        add_images(h)
    for a in parts.get("assemblies", []):
        add_images(a)
    for lc in parts.get("lasercut", []):
        add(lc.get("photo"), "image")
    for f in parts.get("families", []):
        add(f.get("image"), "image")
    for c in parts.get("changes", []):
        add_images(c)

    for plate in parts.get("plates", []):
        add(plate.get("download"), "binary")
        for t in plate.get("thumbs") or []:
            add(t, "image")

    return urls


def retired_domain_mentions() -> list[str]:
    """Every file still naming the domain the calculator used to serve from.

    Except this one. Naming it is what this file is for, and a check that
    always fails on itself is a check nobody can keep green.
    """
    found = []
    me = Path(__file__).resolve()
    for pattern in SCANNED:
        for path in REPO.rglob(pattern):
            if SKIP_DIRS & set(path.relative_to(REPO).parts) or path.resolve() == me:
                continue
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            n = sum(text.count(r) for r in RETIRED)
            if n:
                found.append(f"{path.relative_to(REPO)} ({n})")
    return sorted(found)


def check(item: tuple[str, str]) -> tuple[str, str | None]:
    """Return (url, error) -- error is None when the URL serves real bytes."""
    url, kind = item
    if not url.startswith(SERVICE):
        return url, f"not an asset service URL -- everything is served from {SERVICE}"
    try:
        req = urllib.request.Request(
            url, headers={"Range": "bytes=0-1023", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            # Read a bounded head either way: the asset service answers 200
            # with the full body (its cache holds whole objects), so an
            # unbounded read here would download every STL and the bundle.
            head = r.read(1024)
            total = r.headers.get("Content-Range")
            if total:  # 206: the range tells us the true size
                size = int(total.split("/")[-1])
            else:
                size = int(r.headers.get("Content-Length") or len(head))
    except urllib.error.HTTPError as e:
        return url, f"HTTP {e.code}"
    except Exception as e:  # network/DNS/timeout
        return url, f"unreachable: {type(e).__name__}"

    # Nothing checks the download's filename any more, because nothing can get
    # it wrong: the service serves no Content-Disposition, so a browser names
    # a download after the URL's last segment -- which IS the key, the name
    # and the hash the service stored the bytes under. An engraved STL still
    # arrives as <part>-<uid>-stamped-<face>-<hash12>.stl, and the slicer
    # project made from it still inherits that name.
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
        # lint one file's image URLs directly (works on catalog/parts.json)
        blob = Path(sys.argv[1]).read_text()
        found = re.findall(r'"image(?:_url)?":\s*"(https?://[^"]+)"', blob)
        urls = {u: "image" for u in found}
        stale = []
    else:
        urls = collect_urls()
        stale = retired_domain_mentions()
    if not urls:
        sys.exit("no asset URLs found -- the schema changed?")

    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        results = list(ex.map(check, sorted(urls.items())))

    bad = [(u, e) for u, e in results if e]
    kinds = {}
    for _, k in urls.items():
        kinds[k] = kinds.get(k, 0) + 1
    summary = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
    print(f"checked {len(urls)} asset URLs ({summary})")
    if not bad and not stale:
        print("all serve real bytes")
        return

    if bad:
        print(f"\n{len(bad)} broken:", file=sys.stderr)
        for u, e in bad:
            print(f"  {u}\n    {e}", file=sys.stderr)
    if stale:
        print(f"\n{' and '.join(RETIRED)} are retired, and still named "
              f"in {len(stale)} file(s):", file=sys.stderr)
        for f in stale:
            print(f"  {f}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
