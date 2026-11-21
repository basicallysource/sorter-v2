"""Every stamped version must name a commit the build can still read.

`npm run build` runs `prebuild` -> `scripts/version-snapshots.mjs`, which
materializes each superseded version by reading

    parts-calculator/src/lib/data/catalog.generated.json

out of git at that version's moment: `snapshot_at`, or the parent of the NEXT
entry's `commit` (VERSIONING.md, "Flipping to a version shows the site as it
was"). A stamped entry whose moment cannot be read is a hard build failure by
design -- the script prints "version snapshots FAILED for stamped entries" and
exits 1, before Vite starts. Cloudflare Pages then reports "Build failed" with
no compile error anywhere in the log, which is a genuinely awful thing to debug
from a dashboard nobody can read.

That is not hypothetical. `catalog/stamp_versions.py` stamps whatever commit
you are sitting on, so on a pull request it stamps the BRANCH commit. Rebase or
amend that branch and the stamped commit is orphaned: it belongs to no ref, no
clone can fetch it, and the build dies -- on `main`, after the merge, forever,
because every later commit carries the same parts.json. sorter-v2#561 stamped
`970249dd`, was rebased, merged as a5ebc2ca, and left `main` red from
2026-09-06 to 2026-09-07.

So this check does exactly what the build does, and nothing else: resolve every
stamped moment and read the generated catalog there.

    python scripts/check_version_commits.py

FAILS when a moment cannot be read (the build cannot either).
WARNS when it can only be read via some branch other than main -- that stamp
dies the day the branch is deleted, so it wants moving to the commit on main.

Exits non-zero listing every unreadable moment.
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parent
GENERATED = "parts-calculator/src/lib/data/catalog.generated.json"

_fetched = False


def git(*args, check=False):
    return subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, text=True, check=check)


def fetch_once():
    """Pages clones the repo, not your working copy: a stamp is only readable
    if it is on a ref. Pull every branch in once so this check sees exactly
    what a clone would."""
    global _fetched
    if _fetched:
        return
    _fetched = True
    refspec = "+refs/heads/*:refs/remotes/origin/*"
    shallow = git("rev-parse", "--is-shallow-repository").stdout.strip() == "true"
    # A shallow checkout (actions/checkout defaults to fetch-depth: 1) has none
    # of the history this reads, and every stamp would look unreadable.
    if shallow:
        git("fetch", "--quiet", "--unshallow", "--no-tags", "origin", refspec)
    else:
        git("fetch", "--quiet", "--no-tags", "origin", refspec)


def readable(ref):
    """Can the generated catalog be read at `ref`, the way the build reads it?"""
    if git("cat-file", "-e", f"{ref}:{GENERATED}").returncode == 0:
        return True
    fetch_once()
    return git("cat-file", "-e", f"{ref}:{GENERATED}").returncode == 0


def moments(manifest):
    """(node, version, ref) for every superseded entry the build snapshots."""
    for a in manifest.get("assemblies", []):
        versions = a.get("versions") or []
        for k, v in enumerate(versions[:-1]):
            succ = versions[k + 1].get("commit")
            ref = v.get("snapshot_at") or (f"{succ}~" if succ else None)
            if ref:  # no ref: pre-stamp-era entry, the app falls back to lines
                yield a.get("id"), v.get("version"), ref


def on_main(commit):
    return git("merge-base", "--is-ancestor", commit,
               "origin/main").returncode == 0


def branches_with(commit):
    out = git("branch", "-r", "--contains", commit).stdout.split()
    return [b for b in out if b != "origin/HEAD" and "->" not in b][:3]


def main():
    manifest = json.loads((HERE / "catalog" / "parts.json").read_text())
    unreadable, off_main = [], []
    for node, version, ref in moments(manifest):
        where = f"{node} v{version} -> {ref}"
        if not readable(ref):
            unreadable.append(where)
            continue
        commit = ref[:-1] if ref.endswith("~") else ref
        if not on_main(commit):
            branches = branches_with(commit) or ["no branch at all"]
            off_main.append(f"{where} (only via {', '.join(branches)})")

    for w in off_main:
        print(f"warning: stamped commit is not on main: {w}")
    if unreadable:
        print(f"\n{len(unreadable)} stamped version moment(s) the build cannot read:")
        for u in unreadable:
            print(f"  {u}")
        print("\nThe commit is orphaned or was never pushed, so a fresh clone "
              "cannot fetch it and\n`npm run build` fails in prebuild. Stamp the "
              "commit that carries the change on main\n(the squash commit), not a "
              "branch head. See parts-calculator/VERSIONING.md.")
        sys.exit(1)
    print(f"every stamped version moment is readable "
          f"({len(off_main)} not on main, see warnings above)")


if __name__ == "__main__":
    main()
