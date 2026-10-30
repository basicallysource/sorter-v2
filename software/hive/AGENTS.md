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
- [`agent-docs/process-roles.md`](agent-docs/process-roles.md) — the web
  process and the worker process (`HIVE_ROLE`): what runs where, how they talk
  (`worker_state`), the catalog in two processes, and the statement timeout
  every request carries, with the endpoints allowed longer.
- [`agent-docs/jobs.md`](agent-docs/jobs.md) — the background job queue: how
  to add a kind of job, how it claims, leases, retries and stays light, and
  its first kind, `swatch_find` (the colour reference palette's readings).
- [`agent-docs/piece-data.md`](agent-docs/piece-data.md) — piece data from
  sorters: the sync endpoints and their cursor rule, where each kind lands,
  whose verdict lives where, and the views and tables to train from.
- [`agent-docs/machine-defaults.md`](agent-docs/machine-defaults.md) — the
  defaults every sorter starts from: the block Hive holds, how a machine
  fetches it, and changing a default in code or live.
- [`agent-docs/telemetry.md`](agent-docs/telemetry.md) — machine telemetry:
  how each sorter is set up and runs (specs, stepper load, camera readings,
  stalls), the record forms and kinds, their size, and how to query them.
- [`agent-docs/server-page.md`](agent-docs/server-page.md) — the admin Server
  page and the request-timing middleware behind it: each route's latency over
  the last hour in fixed memory, the slow-request log line, and the job queue,
  workers, database and disk figures beside it.
- [`agent-docs/labeling-queue.md`](agent-docs/labeling-queue.md) — the review
  queues of Piece samples and Channel samples: one queue module and one machine
  filter for both, the labeling queue and its worker, sort segments and cursor
  paging, the per-piece results kept instead of recomputed, and the rule that
  no request scans the fleet.
- [`agent-docs/query-plans.md`](agent-docs/query-plans.md) — how that rule is
  enforced: a production-sized seeded database and a test that EXPLAINs every
  list and count the API serves, and what to do when it fails.

> **⚠️ These docs are only useful if they match the code.**
> If you change anything the docs describe — auth flows, credential types,
> scopes, middleware, endpoints they mention — **update the doc in the same
> change.** If you find a doc that contradicts the code, fix the doc (or the
> code) before building on either. Stale docs are worse than no docs: they
> send the next agent confidently in the wrong direction. When you add a
> significant subsystem, add a doc for it here and link it from this list.
