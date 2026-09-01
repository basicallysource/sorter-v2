"""Guard the revision-tracking discipline in catalog/parts.json.

VERSIONING.md defines the model this enforces. Two rules, both pure JSON plus
one git read (the same HEAD~1 baseline check_generated_pins.py uses: the
previous main commit on a push, the base branch on a PR's merge ref):

1. **The breaking bit.** Every revision authored on or after 2026-08-31 must
   declare `breaking: true|false` on its versions[] entry, answering one
   question about one node: can an old physical instance of THIS node — a
   print of the part, an assembled unit of the assembly — still be used in
   its place? A first version never carries the bit (nothing older exists to
   break), and neither does a candidate (a candidate is a parallel
   experiment, not a revision; the bit belongs to the version minted if it
   is adopted). Revisions predating adoption are exempt, not failed.

2. **The stamp rule.** A structural change to an assembly's `lines` — a
   member removed, replaced, or a quantity changed — must be stamped: the
   assembly's `version` bumped and a new versions[] entry authored with a
   date, a message, and its breaking bit. Exception: purely ADDING lines to
   a `stub`/`partial` assembly is completing the record of what was always
   physically there, not changing the design, and needs no stamp. A part
   whose `uid` changed is a new revision by definition and must bump its
   `version` with a new entry the same way.

    python scripts/check_versioning.py [--base <ref>]

Exits non-zero listing every violation.
"""
import argparse
import collections
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent

# Revisions from this date on must carry `breaking`; older history is exempt.
ADOPTION_DATE = "2026-08-31"


def previous_manifest(base):
    """parts.json at the baseline ref, or None when history isn't there
    (a depth-1 clone), in which case the diff-based checks are skipped."""
    r = subprocess.run(["git", "-C", str(HERE), "show",
                        f"{base}:parts-calculator/catalog/parts.json"],
                       capture_output=True)
    if r.returncode != 0:
        print(f"note: no parts.json at {base}, skipping the change-stamp checks")
        return None
    return json.loads(r.stdout)


def is_initial(entry):
    """The first version of a node: nothing older exists for it to break."""
    return str(entry.get("version")) == "1"


def check_breaking_bits(manifest):
    bad = []
    for kind in ("parts", "assemblies"):
        for item in manifest.get(kind, []):
            where = f"{kind[:-1]} {item['id']}"
            for v in item.get("versions") or []:
                tag = f"{where} v{v.get('version')}"
                if "breaking" in v and not isinstance(v["breaking"], bool):
                    bad.append(f"{tag}: breaking must be true or false, "
                               f"got {v['breaking']!r}")
                elif is_initial(v):
                    if "breaking" in v:
                        bad.append(f"{tag}: a first version cannot carry "
                                   f"`breaking` -- nothing older exists to break")
                elif "breaking" not in v and (v.get("date") or "") >= ADOPTION_DATE:
                    bad.append(f"{tag} (dated {v.get('date')}): missing `breaking` "
                               f"-- can an old instance still be used in its "
                               f"place? true/false, see VERSIONING.md")
            for c in item.get("candidates") or []:
                if "breaking" in c:
                    bad.append(f"{where} candidate {c.get('uid')}: a candidate "
                               f"is not a revision and cannot carry `breaking`; "
                               f"the bit belongs to the version minted if it "
                               f"is adopted")
            # a bumped version with no versions[] history is a revision that
            # left no record at all
            if str(item.get("version", "1")) != "1" and not item.get("versions"):
                bad.append(f"{where}: version is {item['version']} but there is "
                           f"no versions[] history recording the revisions")
    return bad


def stamp_missing(item, prev, what_changed):
    """A structural change must land with a bumped `version` and a new
    versions[] entry carrying date, message and the breaking bit. Returns the
    problems with this item's stamp, empty when the stamp is complete."""
    tag = f"{item['id']}: {what_changed}"
    if str(item.get("version", "1")) == str(prev.get("version", "1")):
        return [f"{tag}, but `version` was not bumped -- stamp the revision "
                f"(bump version, append a versions[] entry with date, message "
                f"and breaking; see VERSIONING.md)"]
    newest = (item.get("versions") or [{}])[-1]
    out = []
    if str(newest.get("version")) != str(item.get("version")):
        out.append(f"{tag} and version bumped to {item.get('version')}, but the "
                   f"newest versions[] entry is v{newest.get('version')} -- "
                   f"append an entry for the new version")
        return out
    for field in ("date", "message"):
        if not newest.get(field):
            out.append(f"{tag}: new version entry has no {field}")
    if "breaking" not in newest:
        out.append(f"{tag}: new version entry does not declare `breaking`")
    return out


def check_change_stamps(manifest, prev):
    bad = []
    prev_parts = {p["id"]: p for p in prev.get("parts", [])}
    for p in manifest.get("parts", []):
        q = prev_parts.get(p["id"])
        if q and p.get("uid") != q.get("uid"):
            bad += [f"part {b}" for b in
                    stamp_missing(p, q, f"uid changed {q.get('uid')} -> {p.get('uid')} (a new revision)")]

    prev_asms = {a["id"]: a for a in prev.get("assemblies", [])}
    for a in manifest.get("assemblies", []):
        q = prev_asms.get(a["id"])
        if not q:
            continue
        cur = [json.dumps(line, sort_keys=True) for line in a.get("lines") or []]
        old = [json.dumps(line, sort_keys=True) for line in q.get("lines") or []]
        if collections.Counter(cur) == collections.Counter(old):
            continue
        # Filling in a stub/partial assembly -- only adding lines, every old
        # line untouched -- records what was always physically there and is
        # not a design change. Anything removed or altered is one.
        additive = not (collections.Counter(old) - collections.Counter(cur))
        if additive and q.get("status") in ("stub", "partial"):
            continue
        bad += [f"assembly {b}" for b in stamp_missing(a, q, "lines changed")]
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="HEAD~1",
                    help="baseline ref for the change-stamp checks (default HEAD~1; "
                         "use origin/main when checking a dirty tree locally)")
    args = ap.parse_args()

    manifest = json.loads((HERE / "catalog" / "parts.json").read_text())
    bad = check_breaking_bits(manifest)
    prev = previous_manifest(args.base)
    if prev is not None:
        bad += check_change_stamps(manifest, prev)

    if bad:
        print(f"{len(bad)} versioning violation(s) in parts.json:")
        for b in bad:
            print(f"  {b}")
        print("\nThe model is defined in parts-calculator/VERSIONING.md.")
        sys.exit(1)
    print("versioning discipline holds (breaking bits + change stamps)")


if __name__ == "__main__":
    main()
