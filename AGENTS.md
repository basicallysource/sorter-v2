# AGENTS.md

**This file is committed to the public repo.** Anything here must be generally
useful documentation for any agent or contributor working in this repository:
how things build, where things live, what the conventions are. Nothing
specific to one person's machines, accounts, or setup goes in this file; that
belongs in the gitignored `agents.local/` directory.

Deliberately thin right now; sections get filled in as the systems they
describe land.

- `electronics/wire_harness/AGENTS.md`: the wire harness, and the derived-asset
  pipeline (sources in git, renders in the assets bucket, CI publishes).
- `docs/AGENTS.md`: working on the docs site.

If a gitignored `agents.local/` directory exists next to this file, read
its `README.md` and the files it lists: they carry machine-local private
context (machine names, access details) that never gets committed.
