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
| `catalog-tasks` (worker) | The parts catalog's own work, each piece in a child process: the default profiles at start, an auto-sync when the catalog is stale, the syncs an admin starts (below) |
| `catalog-auto-sync`, `default-profiles` (all) | The same, on threads of an all-in-one process, which holds the catalog anyway |
| `teacher-worker` | Runs teacher jobs (OpenRouter / Perceptron) |
| `condition-worker` | The condition auto-labeler (off unless `CONDITION_WORKER_ENABLED`) |
| `machine-stats-worker` | Per-machine stats cache and the daily analytics table |
| `fleet-mass-worker`, `fleet-records-worker` | What `/api/public/fleet/mass` and `/fleet/records` serve |
| `storage-stats-worker` | Walks the object store for the admin server-health page |
| `labeling-queue-worker` | The labeling queue (`agent-docs/labeling-queue.md`) |
| `job-worker` | The job queue (`agent-docs/jobs.md`; off unless `JOB_WORKER_ENABLED`) |

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

## The parts catalog: one copy, in the web process

The catalog service holds every part, color and category in memory, ~390 MB
of a process. The web process needs that for its requests. The worker process
never loads it (`get_profile_catalog_service()` raises there):

- **Lookups** its passes make (a part's weight for the fleet mass, its picture
  and name for the fleet records, the color palette) go through
  `catalog_lookup()`, which in the worker is a `CatalogLookup`: SQL against
  `parts.db` on a connection that never writes, nothing loaded. Anywhere else
  it is the process's own catalog service. Code that runs in the worker uses
  `catalog_lookup()`, never `get_profile_catalog_service()`.
- **Work that needs the whole catalog** runs as a catalog task, a child
  process (`python -m app.catalog_task default-profiles | auto-sync | sync
  <type>`, started by `app/services/catalog_tasks.py`): it loads the catalog,
  does the one thing, writes what an all-in-one process would (`parts.db`, the
  default profiles in Postgres), logs its peak memory and exits, and its memory
  goes back to the box. One child at a time, each stopped after
  `CATALOG_TASK_TIMEOUT_MINUTES` (120). The default profiles run once at the
  worker's start. Every `PROFILE_CATALOG_AUTO_SYNC_CHECK_INTERVAL_MINUTES` the
  runner counts rows and reads the sync times (no catalog loaded) and starts an
  `auto-sync` child when something is stale; a sync that failed or was cut
  short is planned again at the next check, as before. An admin's start and stop arrive as requests; stop
  sends the child SIGTERM, which stops its sync the way the stop button always
  has. A child drops its old copy before reloading after a sync, so it never
  holds two.

The child owns the syncs' side effects: the search-index rebuild and marking a
sync a dead process left `running` as interrupted
(`ProfileCatalogService(runs_syncs=...)`). The web process does neither. It
follows the syncs: at most once a minute (on any use of the catalog) it compares
the sync times recorded in `parts.db` with the ones it loaded, and reloads its
in-memory catalog on a thread of its own when they changed (`follow_syncs`).
The catalog page's status comes from the worker's heartbeat
(`CatalogTaskRunner.catalog_status`: the same shape as the service's, counted
from the tables and the progress rows a running sync keeps in `parts.db`), and
its start and stop go to the worker as requests.

Requests reach `parts.db` through one SQLite connection
(`ProfileCatalogService._conn`). A connection can be handed to other threads
but not used by two at once, and requests run on a thread pool, so every use of
it holds `ProfileCatalogService._lock` for one call: a new method that touches
`_conn` takes the lock, and nothing that waits on the network or reads the whole
catalog runs under it. The reload after a sync (a few seconds) reads `parts.db`
on a connection of its own, and the sets sync writes on one of its own, so a
search never waits for either. Two threads inside the connection at once
showed up as `sqlite3.InterfaceError: bad parameter or other API misuse` on
`/api/profile-catalog/search-parts`;
`tests/test_profile_catalog_connection.py` is the test for it.

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
| `POST /api/color-models/backfill` | 60 s | Reads the model folder, selects up to 50,000 of a machine's pieces and queues a job per 20 pieces per model |
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
development database (33k pieces, 5.5k samples, 540k channel crops), in MB of
resident plus swapped memory. "Load" is 66 page views, 74 machine requests, two
passes asked for from the admin pages and 20 swatch_find jobs on 4K frames.

| | Idle | After the load | Peak |
|---|---|---|---|
| `web` | 561 | 578 | 587; 926 while it reloads after a sync |
| `worker` | 142 | 260 | 417, running the swatch jobs |
| a catalog task child | | | 482–511, for 19–35 s |
| `all` (one process, as before) | 579 | 762 | 941 |

The in-memory parts catalog is ~390 MB (a process is 68 MB with its imports,
456 MB once the catalog is loaded), and only the web process holds it. The
split itself costs a second interpreter, about 100 MB. A catalog task loads the
catalog for its one job and gives it all back when it exits; it drops its old
copy before reloading after a sync, so it never holds two. The web process,
which must keep answering while it reloads, holds both copies for the few
seconds a reload takes and keeps ~150–180 MB of it afterwards (allocator
fragmentation), as an all-in-one process always did after its own syncs. A
reload also forgets the compiler's shared index (`compiler.forget_index`):
kept, the index held the old copy alive beside the new one until the next
compile, ~365 MB.
