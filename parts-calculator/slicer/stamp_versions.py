#!/usr/bin/env python
"""Backfill `commit: null` version entries in parts.json with real git commit hashes.

The workflow the version system assumes:
  1. Author a new version entry in parts.json with `"commit": null` (pending).
  2. Commit ONLY that part's files, with a clear message (the version's changelog).
  3. Run this script. For each part it looks at the git history of the part's STL,
     finds the newest commit not already referenced by an older version entry, and
     stamps it onto the part's newest pending (null-commit) version.
  4. Commit the resulting parts.json (+ re-run filament.py) as a small "stamp" commit.

Stamping also pins the SUPERSEDED version's geometry: the previous version's
final bytes are whatever the STL was right before the stamped commit, so their
sha256 is written onto that version as `stl_hash`. That hash is how
filament.py's archive_versions() retrieves old geometry -- from the
content-addressed bucket, never from git history. The bytes are guaranteed to
be on the bucket already: they were the live master during the previous regen,
and every regen uploads the masters content-addressed.

Unchanged parts are left alone (their newest STL commit is already recorded), so
this is safe to run repeatedly. Run:
  /opt/homebrew/opt/python@3.11/libexec/bin/python stamp_versions.py [--dry-run]
"""
import argparse
import collections
import hashlib
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "parts.json")


def stl_commits(stl_rel):
    """Newest-first list of short commit hashes that touched this STL."""
    out = subprocess.run(
        ["git", "-C", HERE, "log", "--follow", "--format=%h", "--", stl_rel],
        capture_output=True, text=True).stdout
    return [h for h in out.splitlines() if h.strip()]


def stl_hash_before(commit, stl_rel):
    """sha256 of the STL's bytes just before `commit` changed it, or None."""
    r = subprocess.run(["git", "-C", HERE, "show", f"{commit}~1:./{stl_rel}"],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return None
    return hashlib.sha256(r.stdout).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report, don't write")
    args = ap.parse_args()

    d = json.load(open(MANIFEST), object_pairs_hook=collections.OrderedDict)
    stamped = []
    for p in d["parts"]:
        versions = p.get("versions")
        stl = p.get("stl")
        if not versions or not stl:
            continue
        used = {v.get("commit") for v in versions if v.get("commit")}
        # git logs the short hash; compare on the same short form the manifest uses.
        commits = stl_commits(stl)
        fresh = next((c for c in commits if not any(c.startswith(u) or u.startswith(c)
                                                    for u in used)), None)
        if not fresh:
            continue
        # stamp the newest pending version, and pin the geometry the stamped
        # commit replaced onto the version it superseded
        for i in range(len(versions) - 1, -1, -1):
            v = versions[i]
            if not v.get("commit"):
                v["commit"] = fresh
                stamped.append((p["id"], v.get("version"), fresh))
                if i > 0 and not versions[i - 1].get("stl_hash"):
                    prev_hash = stl_hash_before(fresh, stl)
                    if prev_hash:
                        versions[i - 1]["stl_hash"] = prev_hash
                    else:
                        print(f"  ! {p['id']}: could not derive superseded "
                              f"geometry for v{versions[i - 1].get('version')} "
                              f"(no {stl} at {fresh}~1); it will fall back to "
                              "the live asset")
                break

    if not stamped:
        print("nothing to stamp — all versions already tied to commits.")
        return
    for pid, ver, commit in stamped:
        print(f"  {pid} v{ver} -> {commit}")
    if args.dry_run:
        print(f"\n(dry run) would stamp {len(stamped)} version(s).")
        return
    json.dump(d, open(MANIFEST, "w"), indent=2, ensure_ascii=False)
    open(MANIFEST, "a").write("\n")
    print(f"\nstamped {len(stamped)} version(s) into parts.json. "
          f"Re-run filament.py and commit parts.json + parts.generated.json.")


if __name__ == "__main__":
    main()
