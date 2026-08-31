"""One-shot backfill of the catalog changelog from git history.

The history view on the assembly page merges two sources: `versions[]`
entries in parts.json (authoritative, written at stamp time, required by
check_versioning.py since 2026-08-31) and src/lib/data/changelog.generated.json
-- structural changes reconstructed from the git history of parts.json for
the era before the stamp rule existed.

This script wrote that file once. It walks every commit of
parts-calculator/catalog/parts.json (the file's modern era -- before that
path the catalog was the old filament-calculator schema with no assembly
lines, so there is no structure to reconstruct) and diffs adjacent states:

- a part's uid, version or stl_hash changing  -> part-revised
- a part's quantities changing                -> qty-changed
- a part or assembly appearing or vanishing   -> added / removed
- an assembly's lines changing                -> lines-changed

Metadata (names, descriptions, notes, warnings) is deliberately ignored.
Events already represented by a recorded versions[] entry (same node, same
commit) are suppressed -- the recorded entry wins. Reconstructed events
borrow the commit's PR title as their message, and carry no breaking bit:
nobody answered that question at the time, so the field would be a guess.

The output is a frozen artifact: it covers a fixed era that ends where the
stamp rule begins, so it never needs regenerating, and CI could not anyway
(checkouts are fetch-depth 2). Do not hand-edit it and do not re-run this
against a grown history expecting the same file -- if it ever must be
re-made, check the diff, not the checksum.

    python scripts/backfill_changelog.py
"""
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PATH = "parts-calculator/catalog/parts.json"
OUT = HERE / "src" / "lib" / "data" / "changelog.generated.json"


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          cwd=HERE.parent).stdout


def states():
    rows = git("log", "--reverse", "--format=%H|%ad|%s", "--date=short",
               "--", PATH).strip().splitlines()
    out = []
    for row in rows:
        sha, date, subj = row.split("|", 2)
        out.append((sha, date, subj, json.loads(git("show", f"{sha}:{PATH}"))))
    return out


def by_id(items):
    return {x["id"]: x for x in items or []}


def lines_map(asm):
    m = {}
    for line in asm.get("lines") or []:
        member = line.get("part") or line.get("assembly")
        m[member] = line.get("qty")
    return m


def qty_str(q):
    return str(q) if not isinstance(q, dict) else json.dumps(q, sort_keys=True)


def diff_lines(old, new):
    """Human detail for a lines change: '+x ×3, −y, z ×10→4'."""
    bits = []
    for m in sorted(set(old) | set(new)):
        if m not in old:
            bits.append(f"+{m} ×{qty_str(new[m])}")
        elif m not in new:
            bits.append(f"−{m} ×{qty_str(old[m])}")
        elif old[m] != new[m]:
            bits.append(f"{m} ×{qty_str(old[m])}→{qty_str(new[m])}")
    return ", ".join(bits)


def diff_quantities(old, new):
    """Per-section detail for a quantities change: 'interface 1→0'."""
    if not isinstance(old, dict) or not isinstance(new, dict):
        return f"{old}→{new}"
    return ", ".join(f"{k} {old.get(k, 0)}→{new.get(k, 0)}"
                     for k in sorted(set(old) | set(new))
                     if old.get(k) != new.get(k))


def part_revision_detail(old, new):
    bits = []
    if old.get("uid") and new.get("uid") and old["uid"] != new["uid"]:
        bits.append(f"uid {old['uid']}→{new['uid']}")
    if old.get("version") != new.get("version") and new.get("version"):
        bits.append(f"v{old.get('version', '?')}→v{new['version']}")
    if not bits and old.get("stl_hash") != new.get("stl_hash"):
        bits.append("geometry changed (stl)")
    return ", ".join(bits)


def main():
    events = []
    walk = states()
    for prev, (sha, date, subj, new) in zip(walk, walk[1:]):
        old = prev[3]
        pr = re.search(r"\(#(\d+)\)\s*$", subj)
        ev = {"date": date, "commit": sha[:8],
              "pr": int(pr.group(1)) if pr else None,
              "message": re.sub(r"\s*\(#\d+\)\s*$", "", subj)}

        op, np = by_id(old.get("parts")), by_id(new.get("parts"))
        for pid in sorted(set(op) | set(np)):
            if pid not in op:
                events.append({**ev, "node": pid, "kind": "part-added"})
            elif pid not in np:
                events.append({**ev, "node": pid, "kind": "part-removed"})
            else:
                d = part_revision_detail(op[pid], np[pid])
                if d:
                    events.append({**ev, "node": pid, "kind": "part-revised",
                                   "detail": d})
                if json.dumps(op[pid].get("quantities"), sort_keys=True) != \
                        json.dumps(np[pid].get("quantities"), sort_keys=True):
                    events.append({**ev, "node": pid, "kind": "qty-changed",
                                   "detail": diff_quantities(
                                       op[pid].get("quantities"),
                                       np[pid].get("quantities"))})

        oa, na = by_id(old.get("assemblies")), by_id(new.get("assemblies"))
        for aid in sorted(set(oa) | set(na)):
            if aid not in oa:
                events.append({**ev, "node": aid, "kind": "assembly-added"})
            elif aid not in na:
                events.append({**ev, "node": aid, "kind": "assembly-removed"})
            else:
                d = diff_lines(lines_map(oa[aid]), lines_map(na[aid]))
                if d:
                    events.append({**ev, "node": aid, "kind": "lines-changed",
                                   "detail": d})

    # A recorded versions[] entry beats its reconstruction. Match by commit
    # when the entry is pinned, by date when the pin is still null (pending) --
    # revision events only; adds/removals/qty tweaks are never stamped.
    manifest = json.loads((HERE / "catalog" / "parts.json").read_text())
    recorded = set()
    for item in manifest["parts"] + manifest.get("assemblies", []):
        for v in item.get("versions") or []:
            recorded.add((item["id"], (v.get("commit") or "")[:8]))
            recorded.add((item["id"], v.get("date")))
    kept = [e for e in events
            if e["kind"] not in ("part-revised", "lines-changed")
            or ((e["node"], e["commit"]) not in recorded
                and (e["node"], e["date"]) not in recorded)]

    OUT.write_text(json.dumps({
        "note": "Reconstructed from the git history of catalog/parts.json by "
                "scripts/backfill_changelog.py. Frozen artifact -- covers the "
                "era before the stamp rule (2026-08-31); recorded versions[] "
                "entries are the source of truth from then on.",
        "events": kept,
    }, indent=2) + "\n")
    print(f"{len(kept)} events ({len(events) - len(kept)} suppressed by "
          f"recorded versions) -> {OUT.relative_to(HERE)}")


if __name__ == "__main__":
    main()
