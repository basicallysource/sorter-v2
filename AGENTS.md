# AGENTS.md

**This file is committed to the public repo.** Anything here must be generally
useful documentation for any agent or contributor working in this repository:
how things build, where things live, what the conventions are. Nothing
specific to one person's machines, accounts, or setup goes in this file; that
belongs in the gitignored `agents.local/` directory.

Don't commit binaries and don't use Git LFS: vision models come from Hive,
images and other assets from the asset service.

## Where things live

| Path | What it is | Read first |
|---|---|---|
| `software/sorter/backend/` | The machine's Python backend: hardware, vision, state machines, API | `software/README.md` |
| `software/sorter/frontend/` | The machine's web UI | `software/sorter/frontend/AGENTS.md` |
| `software/firmware/` | Firmware for the control boards | its `README.md` |
| `software/sorteros/` | The Orange Pi OS image, first boot, and the image customizer site | `software/sorteros/README.md` |
| `software/hive/` | Hive, the cloud side: backend, frontend, postgres | `software/hive/AGENTS.md` |
| `software/training/` | Detection model training | its `README.md` |
| `docs/` | The documentation site | `docs/AGENTS.md` |
| `parts-calculator/` | The parts catalog, shared with the docs, and the parts calculator site | `parts-calculator/AGENTS.md` |
| `electronics/wire_harness/` | Wire harness sources and the render pipeline | `electronics/wire_harness/AGENTS.md` |
| `electronics/`, `mechanical/` | Boards and CAD | their READMEs |

Agent instructions live in `AGENTS.md` in the folder they cover, with a
one-line `CLAUDE.md` (`@AGENTS.md`) beside it so every agent picks them up.
Add new ones the same way, and add a row above.

If a gitignored `agents.local/` directory exists next to this file, read
its `README.md` and the files it lists: they carry machine-local private
context (machine names, access details) that never gets committed.
