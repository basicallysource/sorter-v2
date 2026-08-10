"""Reject docs image URLs that are not immutable objects or cannot be fetched."""

import hashlib
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
URL = re.compile(r"https://img\.basically\.website/web/[^\s\"<>)]+")
CONTENT_ADDRESSED = re.compile(r"\.([0-9a-f]{10,})\.")

urls = {
    url
    for path in ROOT.rglob("*")
    if path.suffix in {".md", ".yml"}
    for url in URL.findall(path.read_text())
}
errors = []
for url in sorted(urls):
    match = CONTENT_ADDRESSED.search(url)
    if not match:
        errors.append(f"not content-addressed: {url}")
        continue
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status != 200:
                errors.append(f"HTTP {response.status}: {url}")
            elif not hashlib.sha256(response.read()).hexdigest().startswith(match.group(1)):
                errors.append(f"hash mismatch: {url}")
    except OSError as error:
        errors.append(f"unavailable ({error}): {url}")

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)

print(f"validated {len(urls)} immutable docs assets")
