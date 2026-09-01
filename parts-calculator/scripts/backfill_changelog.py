"""One-shot backfill of the catalog changelog from git history.

The history view on the assembly page merges two sources: `versions[]`
entries in parts.json (authoritative, written at stamp time, required by
check_versioning.py since 2026-08-31) and src/lib/data/changelog.generated.json
-- structural changes reconstructed from the git history of parts.json for
the era before the stamp rule existed.

The same file carries the tree timeline that makes time travel work: for
every assembly the era ever saw, the sequence of line-sets it held (`seq`
orders same-day commits), plus the last-known names of nodes that have since
left the catalog (`ghosts`). The assembly page reconstructs the whole tree
at any recorded moment from it; moments after `through` are reconstructed
from versions[] snapshots instead, which the stamp rule guarantees exist.

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


def bare_lines(asm):
    """A line stripped to what the tree needs: member and qty."""
    return [{k: line[k] for k in ("part", "assembly", "qty") if k in line}
            for line in asm.get("lines") or []]


def main():
    events = []
    walk = states()

    # The tree timeline: every assembly's initial line-set, then a new entry
    # at each commit that changed it (None = removed). seq is the commit's
    # position in the walk, so same-day states stay ordered.
    timelines = {}
    names = {}
    first = walk[0][3]
    for a in first.get("assemblies") or []:
        timelines[a["id"]] = [{"seq": 0, "date": walk[0][1],
                               "lines": bare_lines(a)}]
    for state in walk:
        for x in (state[3].get("parts") or []) + (state[3].get("assemblies") or []):
            names[x["id"]] = x.get("name", x["id"])

    for seq, (prev, (sha, date, subj, new)) in enumerate(zip(walk, walk[1:]),
                                                         start=1):
        old = prev[3]
        pr = re.search(r"\(#(\d+)\)\s*$", subj)
        ev = {"date": date, "commit": sha[:8], "seq": seq,
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
                timelines.setdefault(aid, []).append(
                    {"seq": seq, "date": date, "lines": bare_lines(na[aid])})
            elif aid not in na:
                events.append({**ev, "node": aid, "kind": "assembly-removed"})
                timelines[aid].append({"seq": seq, "date": date, "lines": None})
            else:
                d = diff_lines(lines_map(oa[aid]), lines_map(na[aid]))
                if d:
                    events.append({**ev, "node": aid, "kind": "lines-changed",
                                   "detail": d})
                    timelines[aid].append({"seq": seq, "date": date,
                                           "lines": bare_lines(na[aid])})

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

    final = walk[-1][3]
    current = ({p["id"] for p in final.get("parts") or []}
               | {a["id"] for a in final.get("assemblies") or []})
    ghosts = {i: n for i, n in sorted(names.items()) if i not in current}

    OUT.write_text(json.dumps({
        "note": "Reconstructed from the git history of catalog/parts.json by "
                "scripts/backfill_changelog.py. Frozen artifact -- covers the "
                "era up to `through`; recorded versions[] entries are the "
                "source of truth from then on.",
        "through": walk[-1][1],
        "commits": {sha[:8]: {"seq": i, "date": date}
                    for i, (sha, date, _, _) in enumerate(walk)},
        "events": kept,
        "assemblies": {i: {"timeline": tl} for i, tl in sorted(timelines.items())},
        "ghosts": ghosts,
    }, indent=2) + "\n")
    print(f"{len(kept)} events ({len(events) - len(kept)} suppressed by "
          f"recorded versions), {len(timelines)} assembly timelines, "
          f"{len(ghosts)} ghosts, through {walk[-1][1]} "
          f"-> {OUT.relative_to(HERE)}")


if __name__ == "__main__":
    main()
