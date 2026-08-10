"""Reject docs image URLs that are not immutable objects or cannot be fetched."""

import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
URL = re.compile(r"https://img\.basically\.website/web/[^\s\"<>)]+")
CONTENT_ADDRESSED = re.compile(r"\.[0-9a-f]{10,}\.")

urls = {
    url
    for path in ROOT.rglob("*")
    if path.suffix in {".md", ".yml"}
    for url in URL.findall(path.read_text())
}
errors = []
for url in sorted(urls):
    if not CONTENT_ADDRESSED.search(url):
        errors.append(f"not content-addressed: {url}")
        continue
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-0"})
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status != 200:
                errors.append(f"HTTP {response.status}: {url}")
    except OSError as error:
        errors.append(f"unavailable ({error}): {url}")

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)

print(f"validated {len(urls)} immutable docs assets")
