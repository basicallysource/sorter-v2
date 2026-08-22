#!/usr/bin/env python
"""Mint a uid: the 4-character id every part carries for its current version.

A uid names a design revision, not bytes. It is the exact thing in your hand
(and what a print gets engraved with), so it exists before the STL does: mint,
write it on the entry in parts.json, then upload the STL and sync_bucket.py
keys the file under it. A human bumping `version` mints a new uid; a re-export
of the same design is new bytes (a new stl_hash) under the same uid. Screws and
laser-cut parts carry one too -- one scheme for everything on the machine.

  /opt/homebrew/opt/python@3.11/libexec/bin/python catalog/mint_uid.py [N]

prints N (default 1) fresh uids, none of them anywhere in parts.json.
generate.py refuses a parts.json with a duplicate or missing uid.
"""
import json
import os
import random
import re
import string
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "parts.json")

ALPHABET = string.ascii_lowercase + string.digits
UID = re.compile(r"[a-z0-9]{4}")


def taken_uids(manifest):
    """Every uid in use: each part's and assembly's current one, their superseded
    versions' and their candidates'."""
    return {u for item in manifest["parts"] + manifest.get("assemblies", [])
            for u in [item.get("uid")] + [v.get("uid") for v in item.get("versions") or []]
                     + [c.get("uid") for c in item.get("candidates") or []]
            if u}


def mint(taken):
    """4 chars of base36, never all digits, not in `taken`."""
    rng = random.SystemRandom()
    while True:
        uid = "".join(rng.choice(ALPHABET) for _ in range(4))
        if not uid.isdigit() and uid not in taken:
            return uid


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    taken = taken_uids(json.load(open(MANIFEST)))
    for _ in range(n):
        uid = mint(taken)
        taken.add(uid)
        print(uid)


if __name__ == "__main__":
    main()
