# Background jobs

Hive has one general job queue for work that follows from something arriving
(a sample to analyse, a file to index) and should not happen inside the
request that brought it. It is a table, `jobs`, and a worker that runs in the
worker process, beside the other background workers and never in the process
that answers requests (`agent-docs/process-roles.md`):
`app/services/job_queue.py`, `app/models/job.py`. New async work goes here
rather than into another worker thread of its own.

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
`app/background.py` (which both entrypoints import), so the kind exists
before the worker starts. A worker only claims kinds it has a handler for;
jobs of an unknown kind wait.

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

- It is off unless `JOB_WORKER_ENABLED=true`, which only the process that
  runs the background workers reads (`HIVE_ROLE` `worker` or `all`; a web
  process never runs jobs). Jobs can be queued while it is off; they wait.
- `JOB_WORKER_CONCURRENCY` threads, 1 by default: background work uses at
  most one core whatever is queued.
- Each thread lowers its own priority (`JOB_WORKER_NICE`, 10; Linux keeps nice
  values per thread), and rests `JOB_WORKER_PAUSE_S` after every job, so a
  long backlog never runs back to back.
- No database session is held while a handler runs.
- Every exception is caught and logged; a failing database makes the worker
  back off, not die. The threads are daemons, stopped when the process stops
  (`app/background.py`).
- A handler keeps its own weight down: one subject in memory at a time,
  onnxruntime on one thread, nothing cached but what it means to.

## Seeing it

`/admin/jobs` (admin) shows the worker's state (as the worker process last
reported it), counts by kind and status, the oldest waiting job of each kind
and the latest failures, with a retry button.
API: `GET /api/admin/jobs`, `POST /api/admin/jobs/{id}/retry`. The Server page
(`server-page.md`) shows the queue beside the requests and the database, with
what each kind finished and failed in the last hour and which process holds
each running job.

## Settings

| Setting | Default | |
|---|---|---|
| `JOB_WORKER_ENABLED` | `false` | Run jobs in the process that runs the background workers. |
| `JOB_WORKER_CONCURRENCY` | `1` | Worker threads. |
| `JOB_WORKER_POLL_INTERVAL_S` | `5` | Idle wait between looks (an enqueue in the same process wakes it at once; one from the web process waits for the next look). |
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
- **Called**: a swatch is one connected region of top face in one colour (so
  blur cannot merge neighbouring tiles), at least `MIN_AREA` network pixels.
  The frame as a whole is called: the palette is in view when the largest
  chain of neighbouring swatches (each within 2.5 lengths of the next) has at
  least 4 swatches in at least 4 colours. A loose piece's top is a swatch but
  not the palette's. The palette flags are about the palette's swatches only.
  `swatch_finder.py` is a copy of the research finder (its docstring names the
  commit); keep the logic the same so readings compare.
- **Stored** in `sample_swatch_runs` (one per pass: sample, model name and
  sha256, frame size, swatches found, the call `palette_present` and
  `palette_swatches`, palette flags, seconds, when, and the sample's machine
  and frame time, `machine_id` and `frame_at`, by which the labeling pages
  find the palette frames near a piece) and `sample_swatches` (one
  per swatch: position along the palette, colour, BrickLink id, colour and
  surface scores, pixels read, median RGB, RGB standard deviation, clipped
  share, centre, box, length, width, flags, `in_palette`). The call is null on
  runs made before the finder made it; a backfill reads those again. A newer
  model adds a run beside the old; the same model file run again replaces its
  own.
- **Served** at `GET /api/samples/{id}/swatch-runs` (whoever can see the
  sample), and drawn over the frame on the sample page (the palette's swatches
  in green or yellow, others dashed), with the call above the list. The piece
  labeling panel shows the palette frame nearest a piece and its swatches, and
  the piece grid badges and filters the pieces with one near them
  (`labeling-queue.md`, the palette near a piece).
- **Filtered**: the Channel samples filter `palette` (a field of
  `SampleFilters` in `services/sample_filters.py`, so the list, the review
  queue, the batch actions and teacher re-runs all honour it): `in_view`,
  `not_in_view`, `unchecked` (a classification-camera sample with a full frame
  the model has not called yet). Its where-clause is
  `swatch_jobs.palette_filter`: it reads one model's runs, the active one, else
  the one changed last, with one EXISTS on `ix_sample_swatch_runs_model_palette`
  (model, call, sample).
- **Tests**: `tests/test_swatch_jobs.py` stubs the network. A real model runs
  when `HIVE_TEST_SWATCH_MODEL` names an exported finder and
  `HIVE_TEST_SWATCH_FRAME` a classification-camera JPEG with the palette in
  view (and `HIVE_TEST_SWATCH_FRAME_WITHOUT_PALETTE` one without).

### `color_model_run`

Every colour model's answer for a piece, kept side by side
(`app/services/color_model_runs.py`).

- **Models**: every colour classifier in `COLOR_MODEL_DIR` (the `color_models`
  registry, reconciled from the folder; `color_predictor.py`). Not only the
  active one: each model's answers are kept by its file's sha256, so an older
  model's stay beside a newer one's and a removed model's stay under the name
  it had.
- **Queued** by the backfill (`POST /api/color-models/backfill`, admin): one
  machine's labelable pieces (the labeling queue's), all of them or those with
  the colour reference palette near them (`with_palette`) or with same-piece
  candidates, newest first, for every registered model or the ones named,
  leaving out the pieces a model has already answered unless `rerun`. One job
  per 20 pieces per model, priority -10, each model's batches queued together.
  The registry is reconciled with the folder first, so a model just copied in
  is included.
- **Run**: the piece's chosen crops (`piece_color_guess.chosen_crops`: the
  ones the machine used, else the first in storage, at most five, the same as
  the piece panel's guess), read from storage concurrently with no
  transaction open, each resized to the model's input; the mean softmax over
  them, a multiview model getting each crop's camera channel. One model's
  session is kept at a time, on one thread without onnxruntime's memory arena,
  so a backfill loads each model once.
- **Stored** in `piece_model_colors`: per (machine, piece, model sha256) the
  top colour, its confidence, the top three, the crops read and the model's
  name. A model run again replaces its own answer.
- **Served**: the piece grid sorts by a model's confidence (`least_sure`,
  `surest`) and shows its answer on each card (`labeling-queue.md`); the piece
  panel lists every model's answer (`model_answers` on the piece detail).

### `piece_warm`

A piece's labeling panel worked out before anyone opens it
(`app/services/piece_warm.py`). Opening a piece used to make its colour
guesses and score its ~40 same-piece candidates with the link model in the
request, seconds of storage reads and model runs while the labeler waited.
Both results are kept per piece (`piece_color_guesses`, `piece_link_scores`),
so this job makes them ahead of time.

- **Queued** by the piece grid's list request (`GET /api/labeling/pieces`) for
  the pieces of the page it served that lack the active colour model's guess,
  or the active link model's scores when they have same-piece candidates (two
  keyed reads), at priority 10: ahead of live and backfill work, since a
  person is looking at them.
- **Run**: the same functions the panel calls (`color_guesses`,
  `link_scores`), each reading its kept row first, so a piece already worked
  out costs two reads.
