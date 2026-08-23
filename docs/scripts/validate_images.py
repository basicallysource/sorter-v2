"""Reject docs asset URLs that are not immutable objects or cannot be fetched.

Two URL shapes are checked, both content-addressed:

  https://assets.basically.website/<ns>/<name>-<hash12>.<ext>   the asset service
  https://img.basically.website/web/<path>.<hash16>.<ext>       legacy; no new ones

Either way the hash in the name must be a prefix of the SHA-256 of the bytes
the URL actually serves, so a URL can never drift from its content.
"""

import hashlib
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"

# (url pattern, pattern extracting the claimed hash from a matched url)
SHAPES = [
    (
        re.compile(r"https://assets\.basically\.website/[a-z0-9-]+/[^\s\"<>)]+"),
        re.compile(r"-([0-9a-f]{12})\.[A-Za-z0-9]+$"),
    ),
    (
        re.compile(r"https://img\.basically\.website/web/[^\s\"<>)]+"),
        re.compile(r"\.([0-9a-f]{10,})\."),
    ),
]

urls: dict[str, re.Pattern] = {}
for path in ROOT.rglob("*"):
    if path.suffix not in {".md", ".yml"}:
        continue
    text = path.read_text()
    for url_pattern, hash_pattern in SHAPES:
        for url in url_pattern.findall(text):
            urls[url] = hash_pattern

errors = []
for url, hash_pattern in sorted(urls.items()):
    match = hash_pattern.search(url)
    if not match:
        errors.append(f"not content-addressed: {url}")
        continue
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
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
