# Piece data from sorters

How a sorter's per-piece data reaches Hive, where each kind lands, and where
to find verdicts and predictions when training a model.

## How it arrives

Each sorter runs one sync thread per Hive target (`software/sorter/backend/server/hive_sync.py`).
It asks `GET /api/machine/sync/state` for the highest cursor value Hive holds
per data type, then sends what is above it, in order. Every endpoint upserts by
a natural key, so a re-send never duplicates.

| Data type | Endpoint (machine token) | Lands in | Natural key | Cursor |
|---|---|---|---|---|
| `piece_records` | `POST /api/machine/sync/piece-records` (JSON batch) | `machine_pieces`, `machine_piece_rejection_reasons` | machine, piece_uuid | `sync_seq` |
| `piece_predictions` | `POST /api/machine/sync/piece-predictions` (JSON batch) | `machine_piece_predictions` | machine, piece_uuid, source, request, kind, rank | `local_id` |
| `piece_images` | `POST /api/machine/sync/piece-image` (multipart, one image) | `machine_piece_images` | machine, piece_uuid, seq | `sync_seq` |
| `channel_crops` | `POST /api/machine/sync/channel-crop-batch` (multipart, many crops in one file), or `.../channel-crop` (one) | `machine_channel_crops` | machine, local_id | `local_id` |
| `control_data_segments` | `POST /api/machine/sync/control-data-segment` | `machine_control_data_segments` | machine, local_id | `local_id` |
| `samples` | `POST /api/machine/sync/sample` | `samples` | session, local_sample_id | `local_id` |
| `piece_corrections` | `POST /api/machine/sync/piece-corrections` | `machine_pieces` verdict columns | machine, piece_uuid | `local_id` |
| `training_runs` | `POST /api/machine/sync/training-runs` (JSON batch) | `machine_training_runs` | machine, run_uuid | `sync_seq` |
| `sorting_runs` | `POST /api/machine/sync/sorting-runs` (the whole set) | `machine_lots`, `machine_sorting_runs` | machine, lot_id / run_id | the set's `version` |
| `telemetry` | `POST /api/machine/sync/telemetry` (JSON batch) | `machine_telemetry` ([telemetry.md](telemetry.md)) | machine, local_id | `local_id` |

**Lots and sorting runs** go whole: a lot is pieces that came in together, a
sorting run one stretch of sorting from its start to the next run's, which
names a lot and adds to it or not (another pass over pieces it already
counted). The machine can rename, move or delete a run, so each send replaces
the machine's lots and runs, and its state is not a cursor but the set's
`version`, a number the sorter derives from the set's content
(`sorting_runs.syncSet`); the sorter sends when its version differs. A lot's
pieces are those whose `seen_at` falls in the stretches of its runs that add
to it; `GET /api/records/machines/{id}/sorting-runs` gives each run's
`ends_at`.

**The cursor rule.** A row that never changes on the sorter syncs by its id
(`local_id`). A row that changes (a piece record gets its bin, a verdict, a
feedback flag; an image becomes ready) carries `sync_seq`: a value from one
counter per machine, taken in the same SQLite write transaction every time the
row becomes ready or changes. SQLite has one writer, so commit order is seq
order and nothing is skipped. Hive advances `machine_sync_state.max_local_id`
by `sync_seq` when the row has one, else by `local_id`. When a sorter first
adds `sync_seq`, its existing rows take `sync_seq = id` and the counter starts
above every id, so a watermark Hive already holds keeps its meaning.

**Batches never stall.** The JSON batch endpoints validate rows one by one: a
bad row is logged and skipped (the response counts it in `skipped`) and the
watermark still moves past it. A row the database refuses is retried alone in a
savepoint and skipped if it fails again.

**Each upload stays cheap.** The fleet sends several files a second, so the
file endpoints (crops, piece images, control data, samples, and the older
`/api/machine/upload`) keep to this:

- The file is checked (its magic bytes and size, never decoded) and written to
  storage with no transaction open: the read the machine-token lookup began
  is committed first, so no connection waits in a transaction while bytes
  travel. The rows follow in one short transaction.
- The watermark advances in one statement (an upsert that keeps the larger
  value and returns it).
- The one-row upserts (a crop, a piece image, a segment) and the watermark
  are plain SQL (`text()`) that SQLAlchemy compiles once. Its own
  `insert().on_conflict_do_update()` is never cached: compiling it and its
  `excluded` columns again on every crop was about a fifth of the request.
- `machines.last_seen_at` is written at most once a minute per machine
  (`services/machine_presence.py`): only when the value loaded with the
  machine is a minute old, and only by the first of the requests in this
  process that loaded it.
- On S3 a file up to 8 MB goes in one `put_object`, not through a transfer
  manager.

A crop with its file is three statements (token, crop, watermark), none
compiled again, around the storage write; `tests/test_machine_ingest.py`
holds the line.

**Channel crops come in batches.** A C2/C3 crop is a few KB and a sorter takes
thousands an hour, so a sorter sends up to a few hundred in one request
(`channel-crop-batch`): their JPEGs back to back in one file, and each crop's
metadata naming its `offset` and `length` in it. Hive stores the file once
(`<machine>/channel_crops/batches/<first>-<last>.bin`) and upserts every crop's
row in one statement; a crop's `image_key` is the file's key plus
`#<offset>+<length>` (`storage_backend.ranged_key`). Reading or serving such a
key reads that range (S3 `Range`, or a seek on local storage), it is never a
signed link, and deleting it leaves the file. A crop whose range is not a JPEG,
or whose metadata does not validate, loses only its own picture or row; the
watermark still moves past it. The batch counts as one file against the
machine's upload budget. Sorters that predate batches, or a Hive without the
endpoint (404), use the one-crop endpoint.

**What a sorter sends when.** A piece's record goes when the piece is
distributed (or reaped, or corrected before it distributes), and again each
time it changes. Its images go once its record exists, with their final
`used` / `excluded_from_result` flags; images of a piece that never got a
record never sync. Predictions go once: the machine's own when classification
settles, a later run's when it is imported on the sorter.

**Training runs.** A sorter in training mode labels every piece it sees during
a run with what the run was for; the first kind is a colour run, where the
operator feeds one colour (or a set) and each piece counts as one of them. The
piece's record carries `training_run_uuid`, `training_segment_uuid`,
`training_color_id` (NULL when the run could not decide one), `training_label_source` (`run`: the run's one
colour; `prediction`: the first of the piece's own colour predictions that is
one of the run's; `nearest`: the run colour nearest the machine's),
`training_excluded` and `training_updated_at`; the sorter owns them, so every
record overwrites them. The run itself (`mode`, `color_ids`: every colour it
used, `segments`, `started_at`, `ended_at`, `excluded`) syncs as
`training_runs`. A run is a sequence of segments: the operator can change the
colours fed without ending the run, and each change starts a segment
(`{segment_uuid, color_ids, started_at, ended_at}`, oldest first, kept as JSON
on the run's row and overwritten on every sync); a piece names the segment it
was seen in. A training colour **counts**
as a colour label when it is set, the piece is not excluded and its run is not
(a run Hive has not received yet counts as not excluded). Hive keeps each run's
`piece_count`, `labeled_count` and `excluded_count` on its row, recounting a
run (an indexed count over its pieces, `ix_machine_pieces_training_run`) when a
batch of records touches it and when the run syncs, so no request counts a
run's pieces (`services/training_runs.py`). The machine page lists a machine's
runs (`GET /api/machines/{id}/training-runs`); the piece panel shows the
piece's run (`training_run` on `GET /api/labeling/piece/...`).

**Older sorters** send records without `sync_seq` and the operator's verdict on
the separate `piece_corrections` stream. Hive keeps that endpoint: a correction
for a piece whose record has not arrived yet creates the piece's row
(`local_id` 0, no classification), which the record fills in later; the row's
`created_at` then becomes the record's arrival, since workers count new
pieces forward from `created_at`.

## Who said what: verdicts

Each source owns its verdict; nothing writes another source's.

- **The machine operator** (on the sorter's Correct the prediction card):
  `machine_pieces.part_correct`, `color_corrected_id`, `correction_updated_at`,
  the `*_feedback_submitted` flags (whether the sorter sent it to Brickognize),
  and `machine_piece_rejection_reasons`. Written only by the sync endpoints.
  `color_corrected_id` can be the sentinel `any_color`.
- **A training run**: `machine_pieces.training_*`, from the machine (above).
  Excluding a piece or a run is the operator's, on the sorter.
- **Each Hive labeler**: `piece_color_labels` (`color_id`, or `cant_tell`),
  `piece_part_labels` (`part_num` or `cant_tell`, and `part_correct`: their
  answer to "is the machine's part right?"), `piece_rejections`. Their
  Brickognize feedback is recorded on their own row
  (`brickognize_feedback_at`). Brickognize hears about a piece at most once per
  channel, from the machine or from Hive.

For training, read the views (one row per verdict, any source):

- `piece_color_verdicts`: `source` (`machine` | `hive` | `training_run`),
  `verdict_by` (as text: the machine's owner, the labeler, or the run's
  `run_uuid`), `machine_id`, `piece_uuid`, `color_id` (BrickLink id as text),
  `cant_tell`, `verdict_at`, and what the machine applied: `machine_color_id`,
  `machine_color_provider`, `machine_color_confidence`. A `training_run` row is
  a training colour that counts (above); `verdict_at` is the label's
  `training_updated_at`, else when the piece was seen. The SQL is
  `PIECE_COLOR_VERDICTS_SQL` in the latest migration that defines it
  (`f6a8c0e2b4d7_training_runs.py`).
- `piece_part_verdicts`: the same for parts, with `part_num`, `part_correct`,
  `machine_part_id`, `machine_mold_provider`, `machine_confidence`. A machine
  verdict that the part is right has `part_num` = the machine's part; one that
  it is wrong has no `part_num`.

## What the machine predicted

`machine_piece_predictions` keeps every ranked answer a piece got on its
sorter, from any source. `source` `live` is the machine's own classification
while sorting: each Brickognize request's (`combined`, `single_burst`) top
five parts and colours with scores, and the hosted colour model's (`hosted`,
provider `hive_basically`, `model` = its sha256, `model_name`) top three. Any
other `source` is the label of a later run of a model over the piece's stored
images, imported on the sorter (`POST /api/predictions/import` there; its
`request` is the model's name) or on Hive by an admin
(`POST /api/records/machines/{id}/predictions`, `predictions:write`; the row's
`local_id` is 0, as no machine row backs it). `images` lists the piece's images each
prediction was made from (`set` `burst`: a `machine_piece_images` seq; `link`:
an upstream crop the piece-link model matched), NULL for rows from sorters
that did not record them, as are `model_name` and `source` (taken as `live`).
`rank` is the provider's own order (0-based); `applied` marks the one part
and the one colour the piece took. `GET /api/labeling/piece/{machine}/{piece}`
returns them as `machine_predictions`, the live ones first. Hive's own colour models' answers are kept per model in
`piece_model_colors` (`jobs.md`, `color_model_run`), returned as
`model_answers`; the piece panel steps through both. The records API
(`GET /api/records/machines/{id}/pieces`) gives each piece's later colours
(every non-live run's top colour, through
`ix_machine_piece_predictions_later_colors`, and the active model's answer as
source `hive`) and its Hive colour labels. Pieces from sorters older than this have none; their
applied colour and score are on `machine_pieces` (`color_id`,
`color_confidence`, `color_provider`).
