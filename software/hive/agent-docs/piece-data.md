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
| `piece_predictions` | `POST /api/machine/sync/piece-predictions` (JSON batch) | `machine_piece_predictions` | machine, piece_uuid, request, kind, rank | `local_id` |
| `piece_images` | `POST /api/machine/sync/piece-image` (multipart, one image) | `machine_piece_images` | machine, piece_uuid, seq | `sync_seq` |
| `channel_crops` | `POST /api/machine/sync/channel-crop` | `machine_channel_crops` | machine, local_id | `local_id` |
| `control_data_segments` | `POST /api/machine/sync/control-data-segment` | `machine_control_data_segments` | machine, local_id | `local_id` |
| `samples` | `POST /api/machine/sync/sample` | `samples` | session, local_sample_id | `local_id` |
| `piece_corrections` | `POST /api/machine/sync/piece-corrections` | `machine_pieces` verdict columns | machine, piece_uuid | `local_id` |

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

**What a sorter sends when.** A piece's record goes when the piece is
distributed (or reaped, or corrected before it distributes), and again each
time it changes. Its images go once its record exists, with their final
`used` / `excluded_from_result` flags; images of a piece that never got a
record never sync. Predictions go once, when classification settles.

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
- **Each Hive labeler**: `piece_color_labels` (`color_id`, or `cant_tell`),
  `piece_part_labels` (`part_num` or `cant_tell`, and `part_correct`: their
  answer to "is the machine's part right?"), `piece_rejections`. Their
  Brickognize feedback is recorded on their own row
  (`brickognize_feedback_at`). Brickognize hears about a piece at most once per
  channel, from the machine or from Hive.

For training, read the views (one row per verdict, any source):

- `piece_color_verdicts`: `source` (`machine` | `hive`), `verdict_by` (the
  machine's owner or the labeler), `machine_id`, `piece_uuid`, `color_id`
  (BrickLink id as text), `cant_tell`, `verdict_at`, and what the machine
  applied: `machine_color_id`, `machine_color_provider`,
  `machine_color_confidence`.
- `piece_part_verdicts`: the same for parts, with `part_num`, `part_correct`,
  `machine_part_id`, `machine_mold_provider`, `machine_confidence`. A machine
  verdict that the part is right has `part_num` = the machine's part; one that
  it is wrong has no `part_num`.

## What the machine predicted

`machine_piece_predictions` keeps every ranked answer the sorter got: each
Brickognize request's (`combined`, `single_burst`) top five parts and colours
with scores, and the hosted colour model's (`hosted`, provider
`hive_basically`, `model` = its sha256) top three. `rank` is the provider's own
order (0-based); `applied` marks the one part and the one colour the piece
took. `GET /api/labeling/piece/{machine}/{piece}` returns them as
`machine_predictions`. Pieces from sorters older than this have none; their
applied colour and score are on `machine_pieces` (`color_id`,
`color_confidence`, `color_provider`).
