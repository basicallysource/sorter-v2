# Process roles: the web process and the worker process

Hive's backend image runs as two processes in production: one answers requests,
the other runs every background worker. A third role puts both in one process,
for a dev server and the tests. `HIVE_ROLE` (`app/config.py`) says which a
process is; `app/roles.py` answers the two questions code asks of it.

| `HIVE_ROLE` | Answers requests | Background workers | Runs as |
|---|---|---|---|
| `all` (default) | yes | all of them | `uvicorn app.main:app` (dev, tests) |
| `web` | yes | none | `uvicorn app.main:app`, the `backend` service |
| `worker` | no | all of them | `python -m app.worker`, the `worker` service |

Run one `all` process, or one `web` and one `worker`. Never an `all` beside a
`worker`: every worker would run twice (`app.worker` refuses any role but
`worker`, and the web app refuses `worker`).

**Why.** Python runs one thread at a time. When one process answered the UI,
took in every machine's uploads and ran a dozen background loops, a pass over
the whole fleet or a backlog of jobs held the interpreter a request was waiting
for, and every request paid for it. Two processes give each its own interpreter,
its own memory ceiling and its own CPU weight, so the work that can wait waits.

## What runs where

`app/background.py` is the one list of background workers and the one place
that starts them (both entrypoints call `background.start()`):

| Worker | What it does |
|---|---|
| `catalog-auto-sync` | Re-syncs the parts catalog from Rebrickable when it is stale (only with `REBRICKABLE_API_KEY`) |
| `teacher-worker` | Runs teacher jobs (OpenRouter / Perceptron) |
| `condition-worker` | The condition auto-labeler (off unless `CONDITION_WORKER_ENABLED`) |
| `machine-stats-worker` | Per-machine stats cache and the daily analytics table |
| `fleet-mass-worker`, `fleet-records-worker` | What `/api/public/fleet/mass` and `/fleet/records` serve |
| `storage-stats-worker` | Walks the object store for the admin server-health page |
| `labeling-queue-worker` | The labeling queue (`agent-docs/labeling-queue.md`) |
| `job-worker` | The job queue (`agent-docs/jobs.md`; off unless `JOB_WORKER_ENABLED`) |
| `default-profiles` | Publishes Hive's default sorting profiles once at start |

A new background worker goes in that list, and in no other process. Whatever
role, a process also logs its own memory every five minutes
(`memory-log-worker`), and a web process loads the parts catalog in the
background at start, so its first requests find it ready.

## How the two processes talk: `worker_state`

Nothing is shared in memory, so anything a request needs from a worker goes
through one small table, `worker_state` (`app/services/worker_state.py`), one
row per name:

- **Published answers** (`published:<what>`). A worker whose output requests
  serve publishes it there on every pass (`worker_state.publish`) and the
  endpoint reads it (`worker_state.published`); never a module global, which
  the web process cannot see. `fleet_mass` and `fleet_records` work this way.
- **The heartbeat** (`heartbeat`). Every `WORKER_HEARTBEAT_INTERVAL_S` (15 s)
  the worker process writes its role, host, pid and every worker's
  `status()`, and the catalog's sync status. The admin pages read it in a web
  process through `background.worker_status(db, name)` (and
  `background.reported_catalog_status`); a report older than
  max(60 s, four intervals) reads as not running. After each report the
  worker touches `WORKER_HEARTBEAT_FILE`, which is its container's healthcheck.
- **Requests** (`request:<what>`). An admin asking for something now (a
  stats pass, a storage walk, the condition labeler, a catalog sync started or
  stopped) leaves a row; the worker process takes and does them every
  `WORKER_POLL_INTERVAL_S` (2 s). Use `background.request_pass(db, name)`:
  in an `all` process it wakes the worker directly.

Asking for a fleet-wide recompute on a request is how a request ends up
holding the interpreter: `POST /api/admin/machines/stats/refresh` used to run
the pass itself and now asks the worker for one.

## The parts catalog in two processes

`parts.db` is a SQLite file both processes open (WAL mode; the bind mount is
shared). The worker process owns the syncs: the auto-sync, the syncs an admin
starts, the search-index rebuild, and marking a sync a previous process left
`running` as interrupted (`ProfileCatalogService(runs_syncs=...)`). A web
process does none of that. It follows the syncs instead: at most once a minute
(on any use of the catalog) it compares the sync times recorded in `parts.db`
with the ones it loaded, and reloads its in-memory catalog on a thread of its
own when they changed (`follow_syncs`). The catalog endpoints that start, stop
and report syncs go to the worker process in a web process.

## Every request is bounded: statement timeouts

In every process that answers requests, each request's database session sets
`statement_timeout` at the start of every transaction (`SET LOCAL`, so it ends
with the transaction and a handler that commits halfway keeps its limit):
`app.deps.get_db` puts the limit on the session, the `after_begin` listener in
`app/database.py` applies it.

| Requests | Limit | Setting |
|---|---|---|
| People and integrations (everything else) | 15 s | `REQUEST_STATEMENT_TIMEOUT_MS` |
| Machines: `/api/machine/...`, `/api/devices/...` | 20 s | `MACHINE_STATEMENT_TIMEOUT_MS` |

A statement that runs out is cancelled by Postgres and the request answers
**503** with code `STATEMENT_TIMEOUT` (`app/errors.py`), logged with its path.
The engine's own 60 s (`app/database.py`) is unchanged and still bounds
everything that is not a request: workers, startup, scripts.

An endpoint that legitimately runs longer says so with
`@statement_timeout(seconds=...)` under its route decorator, with a comment on
why. These are all of them; each should become a job when it next matters:

| Endpoint | Limit | Why it is long |
|---|---|---|
| `POST /api/samples/batch-archive`, `/batch-unarchive` | 60 s | Counts, then updates, every sample a filter matches (up to `max_archive`) |
| `POST /api/samples/batch-delete` | 60 s | Counts, loads and deletes every sample a filter matches |
| `POST /api/admin/teacher/jobs` | 60 s | Selects every sample a filter matches and inserts an item per sample |
| `POST /api/swatch-models/backfill` | 60 s | Selects up to 50,000 samples and queues a job for each |
| `DELETE /api/machines/{id}` | 60 s | One DELETE that cascades through everything the machine sent. It also deletes the machine's files from the object store, which no statement timeout bounds: the first candidate for a job |
| `POST /api/machines/{id}/purge` | 60 s | Deletes every upload session, cascading to samples and reviews; the same file deletion |

## Running it

- Dev: `make backend` is one `all` process, as before.
- Both roles locally, against the same database and files:
  `HIVE_ROLE=web uv run uvicorn app.main:app --port 8002` and
  `HIVE_ROLE=worker uv run python -m app.worker`.
- Production (`docker-compose.prod.yml`): the `backend` service is `web` and
  the only one traefik routes to; the `worker` service is the same image with
  `command: python -m app.worker`. It runs no migrations (it starts once the
  backend, whose start applies them, is healthy), has its own memory ceiling
  (`HIVE_WORKER_MEM_LIMIT`, default 1200m, no swap) and a quarter of the
  backend's CPU weight (`cpu_shares: 256`), so requests win when both want
  the cores. `JOB_WORKER_ENABLED` is read by the worker service only. The
  release agent deploys the services a release's compose file defines
  (`scripts/README.md`).

## Memory

Measured 2026-10-12 with the full parts catalog (81k parts) and a copy of a
development database (33k pieces, 5.5k samples, 540k channel crops), resident
set in MB:

| | Idle | After 66 page views, 74 machine requests, two passes and 20 swatch_find jobs |
|---|---|---|
| `web` | 536–560 | 565–585 |
| `worker` | 542–544 | ~670–750, peak 895 during the jobs |
| `all` (one process, as before) | 594 | 709, peak 938 |

The split costs about one more parts catalog: the in-memory catalog is
~390 MB of each process (68 MB for the interpreter and imports, 456 MB once
it is loaded), and both processes hold one. A catalog reload, which follows
every sync (in the worker, and in the web process a minute later), holds the
old and the new catalog for a few seconds: 802 MB at its peak, 591 MB after.
The worker holds its copy for the default profiles at start and for its
syncs; a worker that loaded it only for those would bring the split close to
one process's memory.
