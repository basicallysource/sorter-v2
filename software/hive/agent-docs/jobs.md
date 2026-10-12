# Background jobs

Hive has one general job queue for work that follows from something arriving
(a sample to analyse, a file to index) and should not happen inside the
request that brought it. It is a table, `jobs`, and a worker that runs in the
backend process: `app/services/job_queue.py`, `app/models/job.py`. New async
work goes here rather than into another worker thread of its own.

The older workers (`teacher_worker.py`, `condition_worker.py`, and the
periodic ones in `periodic.py`) predate it and still run their own loops.

## Adding a kind of job

```python
from app.services import job_queue
from app.services.job_queue import JobContext, PermanentJobError

def handle(job: JobContext) -> dict | None:
    # job.subject, job.payload, job.attempts. Open your own short sessions
    # (SessionLocal); none is open while a handler runs.
    ...
    return {"what": "happened"}           # stored as the job's result

job_queue.register_handler("my_kind", handle, max_attempts=3, lease_s=300, backoff_s=30)

job_queue.enqueue(db, "my_kind", subject=str(sample_id))          # False if already pending
job_queue.enqueue_many(db, "my_kind", ids, priority=-10)           # how many were new
```

Register at import time in the handler's module and import that module from
`app/main.py`, so the kind exists before the worker starts. A worker only
claims kinds it has a handler for; jobs of an unknown kind wait.

## How it behaves

| | |
|---|---|
| Dedupe | At most one job per (kind, subject) is `queued` or `running` (a partial unique index; enqueue is `INSERT … ON CONFLICT DO NOTHING`). Once it is `done` or `failed`, the subject can be queued again. |
| Claim | `SELECT … FOR UPDATE SKIP LOCKED` on the due `queued` row with the highest `priority`, then the oldest `run_after`. Two workers never take the same job and never wait on each other. |
| Lease | A claimed job is `running` with `locked_by` and `locked_until` (now + the kind's `lease_s`). A worker that dies leaves the lease to run out; the worker's maintenance pass (every minute) queues it again, or fails it once it has used `max_attempts`, so a job that kills its worker cannot loop forever. A finish from a worker whose lease was taken is ignored. Make `lease_s` comfortably longer than one run. |
| Retry | A handler that raises is queued again after `backoff_s`, doubling each attempt (capped at an hour, with jitter), until `max_attempts`; then `failed`, with the error kept. Raise `PermanentJobError` when trying again cannot help (the subject is gone): it fails at once. Make handlers safe to run twice. |
| Pruning | `done` jobs are deleted after `JOB_KEEP_DONE_HOURS` (72), `failed` after `JOB_KEEP_FAILED_DAYS` (30), in batches, hourly. |

## Keeping it light

The worker shares a small box with the API, so:

- It is off unless `JOB_WORKER_ENABLED=true`. Jobs can be queued while it is
  off; they wait.
- `JOB_WORKER_CONCURRENCY` threads, 1 by default: background work uses at
  most one core whatever is queued.
- Each thread lowers its own priority (`JOB_WORKER_NICE`, 10; Linux keeps nice
  values per thread), and rests `JOB_WORKER_PAUSE_S` after every job, so a
  long backlog never runs back to back.
- No database session is held while a handler runs.
- Every exception is caught and logged; a failing database makes the worker
  back off, not die. The threads are daemons, stopped in the app's lifespan.
- A handler keeps its own weight down: one subject in memory at a time,
  onnxruntime on one thread, nothing cached but what it means to.

## Seeing it

`/admin/jobs` (admin) shows the worker's state, counts by kind and status, the
oldest waiting job of each kind and the latest failures, with a retry button.
API: `GET /api/admin/jobs`, `POST /api/admin/jobs/{id}/retry`.

## Settings

| Setting | Default | |
|---|---|---|
| `JOB_WORKER_ENABLED` | `false` | Start the worker in this process. |
| `JOB_WORKER_CONCURRENCY` | `1` | Worker threads. |
| `JOB_WORKER_POLL_INTERVAL_S` | `5` | Idle wait between looks (an enqueue in this process wakes it at once). |
| `JOB_WORKER_PAUSE_S` | `0.5` | Rest after each job. |
| `JOB_WORKER_NICE` | `10` | Nice value of the worker threads (Linux), 0 to leave it. |
| `JOB_KEEP_DONE_HOURS` | `72` | How long done jobs are kept. |
| `JOB_KEEP_FAILED_DAYS` | `30` | How long failed jobs are kept. |

## Job kinds

### `swatch_find`

Some machines carry a colour reference palette: LEGO tiles of known colours
(white, the greys, black, the primaries) at the edge of the classification
camera's view. A small ONNX network finds each tile's flat top face in a raw
frame, and its colour is read from the full-resolution pixels
(`app/services/swatch_finder.py`).

- **Models** (`swatch_models`, `app/services/swatch_models.py`): ONNX files in
  `SWATCH_MODEL_DIR` whose metadata says `hive.kind` = `swatch_finder` (with
  `hive.name`, `hive.colour_names`, `hive.classes` as BrickLink colour ids,
  `hive.net_long_side`). They are copied there out of band; `/admin/swatch-models`
  rescans the folder and activates one. At most one is active.
- **Queued** when a sample whose `source_role` is in `SWATCH_FIND_SOURCE_ROLES`
  (`["classification_channel"]`) arrives through `/api/machine/sync/sample`
  while a model is active, and by the backfill (`POST /api/swatch-models/backfill`,
  or the form on `/admin/jobs`): one machine's samples captured in a time
  range, newest first, behind the live ones (priority -10), leaving out
  samples the active model has already read unless `rerun`.
- **Run**: reads the sample's full frame from storage, runs the active model
  (onnxruntime on `SWATCH_FINDER_THREADS`, 1, without its memory arena so the
  process's footprint stays flat), and stores the readings.
- **Stored** in `sample_swatch_runs` (one per pass: sample, model name and
  sha256, frame size, tiles found, palette flags, seconds, when) and
  `sample_swatches` (one per tile: position along the palette, colour,
  BrickLink id, colour and surface scores, pixels read, median RGB, RGB
  standard deviation, clipped share, centre, box, length, width, flags). A
  newer model adds a run beside the old; the same model file run again
  replaces its own.
- **Served** at `GET /api/samples/{id}/swatch-runs` (whoever can see the
  sample), and drawn over the frame on the sample page.
