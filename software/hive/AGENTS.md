# Hive — agent guide

Hive is the cloud side of the sorter ecosystem: FastAPI backend
(`backend/`), SvelteKit frontend (`frontend/`), postgres, alembic
migrations. The frontend: [`frontend/AGENTS.md`](frontend/AGENTS.md); how it
looks: [`../sorter-design-system`](../sorter-design-system).

## agent-docs/ — read it, and KEEP IT UPDATED

Longer-form documentation for anyone (human or agent) working on Hive lives
in [`agent-docs/`](agent-docs/):

- [`agent-docs/auth.md`](agent-docs/auth.md) — the auth & permissions
  system: every credential type, how scoping works, and the design
  philosophy behind it.
- [`agent-docs/sorting-profiles.md`](agent-docs/sorting-profiles.md) — sorting
  profiles: the document people and assistants edit, how it compiles into the
  program a sorter runs, the flat map older sorters get, kits, Hive's default
  profiles, and the API and skill for assistants.
- [`agent-docs/jobs.md`](agent-docs/jobs.md) — the background job queue: how
  to add a kind of job, how it claims, leases, retries and stays light, and
  its first kind, `swatch_find` (the colour reference palette's readings).
- [`agent-docs/piece-data.md`](agent-docs/piece-data.md) — piece data from
  sorters: the sync endpoints and their cursor rule, where each kind lands,
  whose verdict lives where, and the views and tables to train from.
- [`agent-docs/labeling-queue.md`](agent-docs/labeling-queue.md) — the review
  queues of Piece samples and Channel samples: one queue module and one machine
  filter for both, the labeling queue and its worker, sort segments and cursor
  paging, the per-piece results kept instead of recomputed, and the rule that
  no request scans the fleet.

> **⚠️ These docs are only useful if they match the code.**
> If you change anything the docs describe — auth flows, credential types,
> scopes, middleware, endpoints they mention — **update the doc in the same
> change.** If you find a doc that contradicts the code, fix the doc (or the
> code) before building on either. Stale docs are worse than no docs: they
> send the next agent confidently in the wrong direction. When you add a
> significant subsystem, add a doc for it here and link it from this list.
