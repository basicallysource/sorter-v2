# Hive — agent guide

Hive is the cloud side of the sorter ecosystem: FastAPI backend
(`backend/`), SvelteKit frontend (`frontend/`), postgres, alembic
migrations.

## agent-docs/ — read it, and KEEP IT UPDATED

Longer-form documentation for anyone (human or agent) working on Hive lives
in [`agent-docs/`](agent-docs/):

- [`agent-docs/auth.md`](agent-docs/auth.md) — the auth & permissions
  system: every credential type, how scoping works, and the design
  philosophy behind it.
- [`agent-docs/set-instances.md`](agent-docs/set-instances.md) — set
  instances: physical set copies, where progress lives, the machine sync
  routing and the BrickLink wanted-list export.

> **⚠️ These docs are only useful if they match the code.**
> If you change anything the docs describe — auth flows, credential types,
> scopes, middleware, endpoints they mention — **update the doc in the same
> change.** If you find a doc that contradicts the code, fix the doc (or the
> code) before building on either. Stale docs are worse than no docs: they
> send the next agent confidently in the wrong direction. When you add a
> significant subsystem, add a doc for it here and link it from this list.
