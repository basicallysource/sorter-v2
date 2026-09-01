"""Alert when a catalog change is about to leave the docs stale.

The docs site reads the same catalog this directory generates, and its pages
reference parts two ways: a `- part: <id>` list in a page's frontmatter (the
page's own bill of materials), and, for an assembly's write-up, the
assembly's `docs` route in parts.json pointing at the page. Neither link is
enforced anywhere else -- an id can be retired out of every assembly, or an
assembly restamped into a new shape, and the page naming it keeps building
happily (uids never die, so nothing 404s). This check makes the drift
visible at PR time.

Warnings, not failures: docs describing an older state of the machine are
allowed to exist. Every finding prints as a GitHub Actions ::warning
annotation and the script always exits 0 -- the alert is the product.

  W1  a docs page names a part id the catalog doesn't have (typo)
  W2  a docs page names a part the catalog no longer uses anywhere
      (no assembly line, no `requires`, no connection `via`)
  W3  an assembly with a docs page was revised in this change (its
      version differs from the --base ref), so the page may now
      describe the old structure

    python scripts/check_docs_refs.py [--base HEAD~1]

--base follows check_versioning.py: HEAD~1 is the previous main commit on a
push and the base branch on a PR's merge ref.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parent
DOCS = REPO / "docs" / "src" / "content"

PART_REF = re.compile(r"^\s*-\s*part:\s*(\S+)\s*$", re.M)


def frontmatter_refs(md: Path):
    text = md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    if end < 0:
        return []
    return PART_REF.findall(text[:end])


def used_ids(d):
    used = set()
    for a in d.get("assemblies", []):
        for line in a.get("lines") or []:
            if line.get("part"):
                used.add(line["part"])
        for c in a.get("connections") or []:
            if c.get("via"):
                used.add(c["via"])
    for p in d["parts"]:
        for req in p.get("requires") or []:
            used.add(req["part"])
    return used


def docs_file(route):
    """The markdown file serving a docs route, if it exists."""
    rel = route.strip("/")
    for cand in (DOCS / f"{rel}.md", DOCS / rel / "index.md"):
        if cand.is_file():
            return cand
    return None


def baseline(ref):
    r = subprocess.run(
        ["git", "-C", str(REPO), "show", f"{ref}:parts-calculator/catalog/parts.json"],
        capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="HEAD~1",
                    help="baseline ref for the revised-assembly check")
    args = ap.parse_args()

    d = json.loads((HERE / "catalog" / "parts.json").read_text())
    known = {p["id"] for p in d["parts"]}
    used = used_ids(d)

    warnings = []

    if DOCS.is_dir():
        for md in sorted(DOCS.rglob("*.md")):
            rel = md.relative_to(REPO)
            for pid in frontmatter_refs(md):
                if pid not in known:
                    warnings.append((rel, f"references part {pid!r}, which is "
                                          f"not in the catalog"))
                elif pid not in used:
                    warnings.append((rel, f"references part {pid!r}, which the "
                                          f"catalog no longer uses anywhere -- "
                                          f"the page may be stale, or the "
                                          f"catalog record incomplete"))

    base = baseline(args.base)
    if base is None:
        print(f"note: no parts.json at {args.base}; skipping the "
              f"revised-assembly check")
    else:
        base_ver = {a["id"]: a.get("version") for a in base.get("assemblies", [])}
        for a in d.get("assemblies", []):
            route = a.get("docs")
            if not route or a["id"] not in base_ver:
                continue
            if a.get("version") != base_ver[a["id"]]:
                md = docs_file(route)
                if md:
                    rel = md.relative_to(REPO)
                    warnings.append((rel, f"assembly {a['id']!r} was revised in "
                                          f"this change (v{base_ver[a['id']]} -> "
                                          f"v{a['version']}); this page may "
                                          f"describe the old structure"))

    for rel, msg in warnings:
        print(f"::warning file={rel}::{msg}")
    n = len(warnings)
    print(f"{n} docs-staleness warning(s)" if n else
          "docs references agree with the catalog")
    sys.exit(0)


if __name__ == "__main__":
    main()
