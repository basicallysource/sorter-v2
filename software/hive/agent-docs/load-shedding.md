# Load shedding: sorter uploads turned away while Hive is overloaded

The fleet sends several files a second: piece images, channel crops, control
data and training samples. When the box stalls (a slow disk, a busy
database), those requests keep arriving before the earlier ones finish, and
each one waiting holds its upload in memory. A stall of a few minutes was
enough to push the web process past its memory ceiling and have it killed,
taking every page and machine with it.

None of those uploads has to arrive, and a sorter keeps what Hive has not
accepted. So while the web process is overloaded,
`app/middleware/load_shed.py` answers them at once with **429 and
`Retry-After: 60`**, body `{"error": "...", "code": "HIVE_OVERLOADED"}`,
without parsing the upload, opening a database session or touching storage.
The body is read and dropped so the connection stays usable.

## Which routes

`POST` to `/api/machine/sync/piece-image`, `channel-crop`,
`channel-crop-batch`, `control-data-segment`, `sample`, and the older
`/api/machine/upload`. Nothing else is turned away: piece records,
predictions, telemetry, heartbeats, profiles and every page are answered as
before.

## What a sorter does with it

`software/sorter/backend/server/hive_sync.py` treats a 429 as "this target is
busy": the whole target backs off, for at least Retry-After seconds, and its
cursors stay where they were, so the same data goes again later. Sorters from
before Retry-After support back off on any failed pass. Neither stops sorting.

## When it trips

Any of these, checked as each upload arrives (settings in `app/config.py`):

| Setting | Default | Trips when |
|---|---|---|
| `LOAD_SHED_MAX_UPLOADS_IN_FLIGHT` | 16 | that many of these uploads are already being served |
| `LOAD_SHED_MAX_REQUESTS_IN_FLIGHT` | 80 | more requests of any kind than this are in flight |
| `LOAD_SHED_MEMORY_FRACTION` | 0.8 | the container's anonymous memory (cgroup v2 `memory.stat` `anon`, not `memory.current`, which counts reclaimable page cache) passes this share of `memory.max`; 0 turns it off; skipped without a limit |
| `LOAD_SHED_HOLD_S` | 60 | refusals continue until this long has passed with nothing tripping |
| `LOAD_SHED_RETRY_AFTER_S` | 60 | the Retry-After sent |

## What it reports

- A log line when an episode starts (the reason), one a minute while it lasts
  (refusals in that minute, uploads and requests in flight) and one when it
  ends (how long, how many refused). All begin `load shed:`.
- An operator alert at the start (urgency `time_sensitive`) and the end
  (`normal`), through `app/services/admin_alert.py`, when `ADMIN_ALERT_URL`
  (the whole URL, path included) and `ADMIN_ALERT_TOKEN` are set. Each
  episode's alerts carry a stable `request_id`, so a retried delivery is not
  shown twice.
- `load_shed` on `GET /api/admin/server` (`services/server_status.py`):
  whether it is shedding, why, how many refused this episode, uploads and
  requests in flight.
- A refused upload is counted by the request-timing middleware as a 429 on
  `(no route)`: the middleware answers before routing.

The state is per process. Production has one web process, so it is global
there.
