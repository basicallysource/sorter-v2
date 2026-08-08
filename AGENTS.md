# AGENTS.md

**This file is committed to the public repo.** Anything here must be generally
useful documentation for any agent or contributor working in this repository:
how things build, where things live, what the conventions are. Nothing
specific to one person's machines, accounts, or setup goes in this file; that
belongs in the gitignored `AGENTS.local.md`.

Deliberately thin right now; sections get filled in as the systems they
describe land.

- `electronics/wire_harness/AGENTS.md`: the wire harness, and the derived-asset
  pipeline (sources in git, renders in the assets bucket, CI publishes).
- `docs/AGENTS.md`: working on the docs site.

If a gitignored `AGENTS.local.md` exists next to this file, read it too: it
carries machine-local private context (machine names, access details) that
never gets committed.
