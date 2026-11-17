# Stats the worker keeps current

Every number about what machines sorted (a machine's pieces, distinct parts and
colours, active time and PPM, the daily table, the fleet's mass and records,
each machine's channel crops) is served from tables the stats worker
(`machine-stats-worker`, `services/machine_stats.py`) keeps. No request
aggregates history (`query-plans.md`), and since 2026-11-17 no pass does
either: a pass reads what changed since the last one.

## Why

The worker used to recompute everything from scratch every hour: grouped scans
over all of `machine_pieces` (two million rows), a count of all of
`machine_channel_crops` (fifty million) and grouped scans of the wide `samples`
rows. As the fleet grew those statements passed the worker's 60 s statement
limit (`app/database.py`) on busy days, every pass failed, and the cache, the
public roster and everything that reads them froze at the last good pass.
Lifting the limit only makes each pass longer. The work has to be proportional
to what changed.

## Pieces: machine-days

`services/piece_days.py`, tables in `models/machine_piece_day.py`:

| table | one row per | holds |
|---|---|---|
| `machine_piece_days` | machine and UTC day of `seen_at` | pieces, distributed, classified, first and last `seen_at`, active seconds within the day |
| `machine_piece_day_keys` | machine, day, kind, key | how many pieces had that status (`s`), part (`p`), colour (`c`) or classified part in a colour (`pc`), the max name, the first classified `seen_at` |
| `machine_piece_keys` | machine, kind, key | the same summed over the machine's days |
| `machine_piece_day_marks` | change | a machine-day whose pieces changed since the worker last looked |

**Triggers on `machine_pieces` write the marks** (statement-level, with
transition tables; one per event): an insert marks the new rows' days, a
delete the old rows' days, an update both, but only when a column the stats
read changed (`_STAT_COLUMNS`: `seen_at`, status, part, colour, names,
`bin_x`). So every write path is caught, a sync, a correction, a machine's
delete cascading, an admin's SQL, without the code that writes knowing about
stats, and a re-sent record that changes nothing marks nothing. Pieces without
a `seen_at` are kept under the day `0001-01-01` (`NULL_DAY`).

**A pass**, for each machine with marks, in a transaction of its own under an
advisory lock on the machine: take (delete) its marks; rebuild each marked day
from its pieces (an index range on `(machine_id, seen_at)`); recompute the
machine's key totals for only the keys those days held before or hold now;
fold its day rows (a few hundred at most) into the cache row and its rows of
`machine_daily_stats`. A machine with no marks costs nothing.

**The numbers are the full scans' numbers.** A count is a sum over days, a
distinct count the number of keys, a name the max over days (taken in SQL, so
the database's collation decides as before), active time the sum of each day's
gaps plus the gap across each midnight (from the day rows' last and first
pieces), in exact decimal seconds as Postgres gave them. `fleet_mass` reads the
part totals and `fleet_records` the first classified sighting per key, so
neither scans pieces either. `tests/test_piece_days.py` changes pieces every
way the app does and compares against the old scans after each pass; the
switch was checked the same way against production's data, machine by machine.

## Channel crops: deltas

Triggers on `machine_channel_crops` append one row to
`machine_channel_crop_deltas` per statement that inserts or deletes crops (a
re-sent crop updates its row and adds nothing). A pass adds them to each
machine's `channel_crops` and deletes them in the same transaction.

## The first time a machine is seen

A machine whose pieces and crops predate the triggers is counted in full once
(`_seed`), the first pass after the migration that added them, or the first
time the worker sees a new machine: every day it has pieces on is marked and
its crops are counted, removing in the same snapshot the deltas that count
already includes. `machine_stats_cache.incremental_since` records when. Set it
back to NULL to have a machine counted in full again.

## Samples

The per-machine sample counts and the weekly diversity rows are still grouped
scans, of narrow indexes on `samples` (`ix_samples_machine_review_captured`,
`ix_samples_machine_role_active`, `ix_samples_machine_reason_active`) rather
than the wide table: a few thousand samples arrive a day, not a million crops.

## Cadence and freshness

`MACHINE_STATS_REFRESH_INTERVAL_MINUTES` (10). The live piece counter still
adds the pieces that arrived since a machine's `computed_at`, the time its
marks were taken. A pass also alerts the operator (once a day) while the disk
has less than `DISK_ALERT_FREE_PCT` free.

## Adding a stat

Make it a sum, a union or a min/max over machine-days and keep it in the day
rows or key rows, or recompute it from a bounded range (the fleet records'
trailing day). If it needs a column the triggers do not watch, add the column
to `_STAT_COLUMNS` in the model and to a new migration's trigger function (the
test checks the two texts are the same), and extend the comparison test.
