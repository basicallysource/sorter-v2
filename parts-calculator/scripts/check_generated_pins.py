#!/usr/bin/env python3
"""Verify the committed generated data agrees with the committed source pins.

The generated files are written by whoever edits catalog/parts.json running
catalog/generate.py, and committed in the same change; nothing regenerates them
after the fact. So the guard against "edited the source, forgot to regenerate"
is this cross-check: every part's generated entry must carry the uid its
source names, every printed one must serve exactly the STL its pin names and
carry real slice numbers, and no entry may outlive its part. Pure JSON, no
network, no slicer.

    python scripts/check_generated_pins.py

Exits non-zero listing every disagreement.
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "scripts"))
from publish_assets import stl_url  # noqa: E402


def all_uids(manifest):
    return {u for item in manifest["parts"] + manifest.get("assemblies", [])
            for u in [item.get("uid")] + [v.get("uid") for v in item.get("versions") or []]
                     + [c.get("uid") for c in item.get("candidates") or []] if u}


def stamp_problems(where, uid, g):
    """The stamped downloads (catalog/engrave.py) are named for the uid they
    carry, <id>-<uid>-stamped-<face>-<hash12>.stl; one named for another uid
    would hand out a print engraved with the wrong id. A missing list means
    the generator that wrote this entry predates stamping."""
    out = []
    stamped = g.get("stamped")
    if stamped is None:
        return [f"{where}: no stamped list -- run the full generator"]
    for v in stamped:
        tail = str(v.get("stl", "")).rsplit("/", 1)[-1]
        if f"-{uid}-stamped-" not in tail:
            out.append(f"{where}: stamped download {tail!r} is not named for uid {uid}")
    return out


def previous_uids():
    """Every uid in parts.json one commit back: HEAD~1 is the previous main commit
    on a push and the base branch on a PR's merge ref. None when history is not
    there (a depth-1 clone), in which case the check is skipped, not failed."""
    r = subprocess.run(["git", "-C", str(HERE), "show", "HEAD~1:parts-calculator/catalog/parts.json"],
                       capture_output=True)
    if r.returncode != 0:
        print("note: no previous parts.json in history, skipping the uid-retention check")
        return None
    return all_uids(json.loads(r.stdout))


def main():
    manifest = json.loads((HERE / "catalog" / "parts.json").read_text())
    generated = json.loads(
        (HERE / "src" / "lib" / "data" / "catalog.generated.json").read_text())
    gen = {p["id"]: p for p in generated["parts"]}

    printed = [p for p in manifest["parts"]
               if p.get("kind", "printed") == "printed" and p.get("stl_hash")]
    bad = []
    for p in printed:
        g = gen.get(p["id"])
        if g is None:
            bad.append(f"{p['id']}: pinned in parts.json but absent from catalog.generated.json")
            continue
        want = stl_url(p["id"], p["stl_hash"])
        if g.get("stl") != want:
            bad.append(f"{p['id']}: generated stl is {g.get('stl')!r}, the pin says {want!r}")
        if not isinstance(g.get("grams"), (int, float)):
            bad.append(f"{p['id']}: no grams in the generated data")
        bad += stamp_problems(p["id"], p["uid"], g)

    live = {p["id"] for p in printed}
    for pid in gen:
        if pid not in live:
            bad.append(f"{pid}: in catalog.generated.json but no longer pinned in parts.json")

    emitted = {**{h["id"]: h for h in generated.get("hardware", [])},
               **{lc["id"]: lc for lc in generated.get("lasercut", [])}, **gen}
    for p in manifest["parts"]:
        g = emitted.get(p["id"])
        if g is not None and g.get("uid") != p.get("uid"):
            bad.append(f"{p['id']}: generated uid is {g.get('uid')!r}, parts.json says {p.get('uid')!r}")

    for p in printed:
        have = {c.get("uid"): c for c in (gen.get(p["id"]) or {}).get("candidates") or []}
        for c in p.get("candidates") or []:
            gc = have.get(c["uid"])
            want = stl_url(p["id"], c["stl_hash"])
            if gc is None:
                bad.append(f"{p['id']}: candidate {c['uid']} is in parts.json but not in the generated data")
            elif gc.get("stl") != want:
                bad.append(f"{p['id']}: candidate {c['uid']} serves {gc.get('stl')!r}, the pin says {want!r}")
            elif not isinstance(gc.get("grams"), (int, float)):
                bad.append(f"{p['id']}: candidate {c['uid']} has no grams -- run the full generator, not --metadata-only")
            else:
                bad += stamp_problems(f"{p['id']} candidate {c['uid']}", c["uid"], gc)

    # A uid is a promise to whoever engraved it on a print: once in parts.json it
    # never leaves. Superseded and rejected candidates are marked, not deleted.
    before = previous_uids()
    if before is not None:
        gone = sorted(before - all_uids(manifest))
        if gone:
            bad.append(f"uid(s) removed from parts.json: {gone} -- mark them superseded/rejected instead")

    if bad:
        print(f"{len(bad)} disagreement(s) between parts.json and catalog.generated.json:")
        for b in bad:
            print(f"  {b}")
        print("\nRun catalog/generate.py and commit the regenerated data with your change.")
        sys.exit(1)
    print(f"catalog.generated.json agrees with parts.json ({len(printed)} pinned parts)")


if __name__ == "__main__":
    main()
