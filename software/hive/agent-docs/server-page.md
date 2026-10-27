# The Server page and request timing

What Hive's server is doing, in one place: `/admin/server` (admins), served by
`GET /api/admin/server` (`app/services/server_status.py`). It is read when the
page opens and when Refresh is pressed; nothing polls it and nothing is stored.
`GET /api/admin/server-health` stays for monitoring by API key
(`server_health:read`, see `auth.md`); the old Server health page redirects
here.

## Request timing

`app/middleware/request_timing.py` times every HTTP request, in memory, in the
process that serves it. It is registered last in `app/main.py`, so it is the
outermost middleware and its time is the whole of the request.

- **Keys** are the route template FastAPI matched (`GET
  /api/samples/{sample_id}`), never the raw path. A request no route matched
  counts as `(no route)` and an unusual method as `OTHER`, so there are never
  more keys than routes.
- **A rolling window** of the last 60 minutes, one slot per minute. In each
  slot, per route seen that minute: the count, how many answered 5xx, how many
  took 2 s or longer, the total and longest time, the time in database
  queries, and a latency histogram of 68 bins, each 20% wider than the one
  before, from 1 ms to about three minutes. Memory stays the same however many
  requests arrive: about 40 KB for a route seen every minute of the hour.
  p50, p90 and p99 are read off the merged histogram, within about 10% of the
  exact values.
- **Database time** comes from SQLAlchemy's cursor events on every engine: each
  query adds its time to a timer the middleware keeps in a context variable.
  The threadpool copies the context, so a sync endpoint's queries count, and a
  query that fails (a statement timeout) counts too. A background thread's
  queries carry no timer.
- **A slow request** (`SLOW_REQUEST_S`, 2 s) logs one warning on the `app`
  logger: `slow request: GET /api/samples answered 500 in 60123 ms, 60010 ms
  of it in 4 database queries`.
- **CPU**: the window notes the process's CPU time once a minute, which the
  page shows as how much of one core the process kept busy (all its threads).
- It belongs to one process and starts empty when the process does.

## What the page shows

| Part | From |
|---|---|
| At a glance | Requests, p90, 5xx, slow requests, CPU, database connections, cache hit, disk free |
| Requests | The window above, one row per route, ordered by total time, p90 or count |
| This process | pid and `HIVE_ROLE`, uptime, CPU, the threadpool sync endpoints run on (busy, waiting), this process's database connections, requests still running, load |
| Disk and memory | `shutil.disk_usage` of `/` (in a container, the host disk Docker keeps its data on) and of the upload folder when storage is local; `/proc/meminfo` and the process's RSS |
| Job queue | `job_queue.summary` plus what finished and failed in the last hour, what is running and in which process, the latest failures. From the jobs table, so it is right whichever process runs the jobs. |
| Background workers | Each worker's own status as this process knows it. A process that runs no background work shows them as not running. |
| Database | Size, cache hit ratio, temporary files, rollbacks and deadlocks (`pg_stat_database`), connections by state, and the five oldest transactions or queries still running (`pg_stat_activity`, query text cut at 500 characters) |
| Tables, Indexes | The twelve biggest, with sequential and index scans, dead rows and the last vacuum; an index never scanned is marked |
| Stored files | The storage walk's cached totals (`server_health.py`); Count again wakes the walk, so it shows only where this process runs the background work |

## Keeping it cheap

Each part is read on its own: one that fails shows its error and the rest
still show. The database parts run under `SET LOCAL statement_timeout = 5000`
and read only Postgres's statistics views and catalog; the job counts use the
jobs table's indexes. Nothing walks storage or counts a big table.
