"""Backfill each superseded assembly version's `tree` from git history.

A superseded version entry stamped since the tree mechanism carries the
whole subtree as the site last showed it while that version was current;
entries stamped before the mechanism only carry their flat lines snapshot,
so flipping the page to them shows names instead of the machine. This walks
every superseded entry without a tree, finds the commit that superseded it
(the NEXT entry's commit), and freezes the subtree from the manifest just
before that commit -- exactly what stamp_versions.py records going forward.

Entries whose superseding commit is unknown, or whose reign predates the
assembly existing in parts.json, are reported and left flat. An entry that
already has a tree (a deliberate lock) is never touched.

    python scripts/backfill_trees.py [--dry-run]

Safe to re-run; only missing trees are written.
"""
import argparse
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG = os.path.join(HERE, "..", "catalog")
sys.path.insert(0, CATALOG)
import stamp_versions  # noqa: E402  (manifest_at, freeze_subtree)

MANIFEST = os.path.join(CATALOG, "parts.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    d = json.load(open(MANIFEST), object_pairs_hook=collections.OrderedDict)
    wrote, skipped = [], []
    for a in d.get("assemblies", []):
        versions = a.get("versions") or []
        for k in range(len(versions) - 1):
            v = versions[k]
            if v.get("tree"):
                continue
            succ = versions[k + 1].get("commit")
            if not succ:
                skipped.append(f"{a['id']} v{v.get('version')}: superseding commit unknown")
                continue
            m = stamp_versions.manifest_at(f"{succ}~")
            if not m or not any(x["id"] == a["id"] for x in m.get("assemblies", [])):
                skipped.append(f"{a['id']} v{v.get('version')}: no readable manifest "
                               f"with this assembly at {succ}~")
                continue
            v["tree"] = stamp_versions.freeze_subtree(m, a["id"])
            wrote.append(f"{a['id']} v{v.get('version')} <- {succ}~ "
                         f"({len(v['tree'])} nodes)")

    for w in wrote:
        print(f"  + {w}")
    for s in skipped:
        print(f"  ~ {s}")
    if args.dry_run:
        print(f"(dry run) would write {len(wrote)} tree(s)")
        return
    if wrote:
        json.dump(d, open(MANIFEST, "w"), indent=2, ensure_ascii=False)
        open(MANIFEST, "a").write("\n")
    print(f"backfilled {len(wrote)} tree(s); {len(skipped)} left flat")


if __name__ == "__main__":
    main()
