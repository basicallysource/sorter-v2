# The labeling queue, and why no request scans the fleet

The piece labeling page (`/piece-bboxes`) reads from tables that background
workers keep, never from a join or count over all of `machine_pieces`,
`machine_piece_images` or `samples`. At a million pieces those took 11 to 48 s
per request and spilled hundreds of MB to temp files; every request now reads a
handful of rows. Keep it that way: **no HTTP request aggregates, sorts or counts
history.** If a page needs a number over the fleet, a worker computes it per
machine and the request sums the rows.

## What lives where

| table | written by | read by |
|---|---|---|
| `labeling_queue` | `services/labeling_queue.py` (worker) | the piece grid (`GET /api/labeling/pieces`) |
| `labeling_queue_counts` | same worker, every pass | `GET /api/labeling/stats` (`total_labelable`) |
| `labeling_queue_state` | same worker | the worker (its progress) |
| `piece_link_scores` | `services/piece_link_scores.py`, on the first open of a piece | `GET /api/labeling/possible-crops/...` |
| `piece_color_guesses` | `services/piece_color_guess.py`, on the first open | `GET /api/labeling/piece/...` |
| `machine_stats_cache.*_samples` | `services/machine_stats.py` (hourly) | `GET /api/stats/overview` (the dashboard) |

## The queue

One narrow row per labelable piece: not dead, at least one crop in storage. The
grid also waits until a piece arrived 15 minutes ago (its upstream channel crops
upload after it), checked on `arrival_at` at read time. `arrival_at` is
`coalesce(seen_at, recorded_at, created_at)`: the grid's "newest" order, the
15-minute rule and the same-piece window all use it.

The worker (`labeling-queue-worker`, every 5 minutes):

- evaluates the pieces, and piece crops, that reached Hive since its last pass
  (by `created_at`, with a 10-minute overlap for transactions still open),
- marks queued pieces whose arrival window holds a newly synced channel crop as
  having same-piece candidates,
- recounts each machine's labelable pieces,
- once a day re-evaluates every piece in batches of 5,000, which catches rows
  that changed after they arrived (a record re-sent as dead or re-classified).

The first pass after a deploy is that full evaluation; it fills an empty queue
in a couple of minutes, and the grid shows what is done so far. A piece that
dies between evaluations never shows: the grid joins `machine_pieces` and
checks `dead` on the rows it serves.

It reads the crop tables through BRIN indexes on `created_at` (they only
append), and `machine_pieces` through `(machine_id, created_at)` one machine at
a time.

## The grid

`services/labeling_grid.py`. Every sort is a few segments read in order until
the page is full: a **walk** of the queue in arrival order through an index
(for a sort about a label count, only pieces with no label of that kind, which
is nearly all of them), the **labeled** pieces ordered by how many labels (a
small set, written by people), and for "likely a rare color" a walk of its own
index. "Priority" is: candidates with no colour label, candidates with labels,
then the same without candidates.

Paging is a keyset cursor (`next_cursor`, passed back as `cursor`): the segment
and the sort key of the last piece served. Page 50 costs what page 1 does, and
a label made while someone scrolls shifts nothing under them.

Thumbnails come as presigned storage URLs (`thumb_url`) when the storage
backend can sign them, so a page of 60 cards is not 60 more API requests. The
image routes remain for local storage and as the fallback.

## Per-piece results kept, not recomputed

- **Link scores** are kept per `(machine, piece, link model sha256)`. The first
  open reads the anchor and candidate crops concurrently, with no transaction
  open, and scores them; later opens read the row. Crops that synced since are
  scored and merged in. The pick threshold is the published model's
  `predict_threshold` (the `detection_models` row of the same slug), else
  `hive.predict_threshold` in the ONNX metadata, else 0.5; the response carries
  it as `link_threshold` and the panel shows it.
- **Colour guesses** (pixel average and colour model) are made from one
  concurrent read of the piece's crops and kept per `(machine, piece, colour
  model sha256)`, remade when the piece's usable crops change.

## Postgres

Prod's postgres settings are in `docker-compose.prod.yml` (`command:`), sized
for the 4 GB box. A release never recreates the postgres container, so a change
there only takes effect after `docker compose ... up -d postgres` on the box
(see `scripts/README.md`). Handlers and workers that still aggregate call
`app.database.tune_for_aggregates` (per-transaction `work_mem`, JIT off).
