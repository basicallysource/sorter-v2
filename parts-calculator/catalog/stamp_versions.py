#!/usr/bin/env python
"""Backfill `commit: null` version entries in parts.json with real git commit hashes.

A part's current version is its `uid` in parts.json and its geometry is its
`stl_hash` pin (the bytes live on the content-addressed bucket; nothing binary
is in git). A new version IS a new uid, so "the commit that introduced the
version" is the commit that changed the part's uid, and this script finds it
by walking parts.json's own history. A hash change with the same uid is a
re-export of the same design and is not a version.

The workflow the version system assumes:
  1. Mint a uid (`python catalog/mint_uid.py`), put it on the part, bump
     `version`, and author a new version entry with `"commit": null`
     (pending). Then upload the new STL (`python scripts/sync_bucket.py
     --upload part.stl`) and set the printed stl_hash.
  2. Commit ONLY that part's change, with a clear message (the version's
     changelog).
  3. Run this script. It stamps the pending version with the commit that
     changed the uid, and writes the REPLACED uid + stl_hash onto the version
     it superseded -- which is how old geometry stays retrievable forever.
  4. Commit the resulting parts.json (+ re-run generate.py) as a small "stamp"
     commit.

Unchanged parts are left alone, so this is safe to run repeatedly. Run:
  /opt/homebrew/opt/python@3.11/libexec/bin/python stamp_versions.py [--dry-run]
"""
import argparse
import collections
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "parts.json")


def manifest_commits():
    """Newest-first short hashes of every commit that touched parts.json."""
    out = subprocess.run(
        ["git", "-C", HERE, "log", "--format=%h", "--", "parts.json"],
        capture_output=True, text=True).stdout
    return [h for h in out.splitlines() if h.strip()]


def pins_at(commit):
    """{part id: (stl_hash, uid)} as of `commit`, or None if parts.json unreadable there."""
    r = subprocess.run(["git", "-C", HERE, "show", f"{commit}:./parts.json"],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return None
    try:
        d = json.loads(r.stdout)
    except ValueError:
        return None
    return {p["id"]: (p.get("stl_hash"), p.get("uid")) for p in d.get("parts", [])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report, don't write")
    args = ap.parse_args()

    d = json.load(open(MANIFEST), object_pairs_hook=collections.OrderedDict)
    pending = [p for p in d["parts"]
               if p.get("versions") and not p["versions"][-1].get("commit")]
    if not pending:
        print("nothing to stamp — all versions already tied to commits.")
        return

    commits = manifest_commits()
    snapshots = {}          # commit -> {id: (stl_hash, uid)}, filled lazily

    def snap(c):
        if c not in snapshots:
            snapshots[c] = pins_at(c)
        return snapshots[c]

    stamped = []
    for p in pending:
        versions = p["versions"]
        used = {v.get("commit") for v in versions if v.get("commit")}
        found = None
        for i, c in enumerate(commits):
            if any(c.startswith(u) or u.startswith(c) for u in used):
                break                      # older than the last stamped change
            cur = snap(c)
            prev = snap(commits[i + 1]) if i + 1 < len(commits) else {}
            if cur is None:
                continue
            cur_uid = (cur.get(p["id"]) or (None, None))[1]
            prev_pin = ((prev or {}).get(p["id"]) or (None, None))
            if cur_uid and cur_uid != prev_pin[1]:
                found = (c, prev_pin)
                break
        if not found:
            continue
        commit, (replaced_hash, replaced_uid) = found
        versions[-1]["commit"] = commit
        stamped.append((p["id"], versions[-1].get("version"), commit))
        if len(versions) > 1 and not versions[-2].get("uid"):
            if replaced_hash and replaced_uid:
                old = versions[-2]
                versions[-2] = collections.OrderedDict(
                    [("version", old.get("version")), ("uid", replaced_uid)]
                    + [(k, v) for k, v in old.items() if k != "version"]
                    + [("stl_hash", replaced_hash)])
            else:
                print(f"  ! {p['id']}: no prior stl_hash found at {commit}~; "
                      f"v{versions[-2].get('version')} will fall back to the "
                      "live asset")

    if not stamped:
        print("nothing to stamp — no pin changes found for the pending versions.")
        return
    for pid, ver, commit in stamped:
        print(f"  {pid} v{ver} -> {commit}")
    if args.dry_run:
        print(f"\n(dry run) would stamp {len(stamped)} version(s).")
        return
    json.dump(d, open(MANIFEST, "w"), indent=2, ensure_ascii=False)
    open(MANIFEST, "a").write("\n")
    print(f"\nstamped {len(stamped)} version(s) into parts.json. "
          f"Re-run generate.py and commit parts.json + catalog.generated.json.")


if __name__ == "__main__":
    main()
