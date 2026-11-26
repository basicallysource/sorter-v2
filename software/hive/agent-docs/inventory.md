# The inventory API

What a person's own machines hold, for any inventory app: a shelf of bags and
trays, a parts list, a shop. Each lot with its parts and colours, the sorting
runs, every bin with what it was assigned, what each bin holds now or got in a
run, and every emptying of a bin with the pieces it took. Read-only, versioned
under `/api/inventory/v1`, served by `routers/inventory.py`; the arithmetic is
`services/inventory.py`.

## Who may read it

A key with the scope `inventory:read`, which any member may make
(`USER_GRANTABLE_API_KEY_SCOPES`; the settings page lists it), or a signed-in
session. Only the caller's own machines (`machines.owner_id`), even for an
admin, and of those only the ones a machine-scoped key names
(`user_api_keys.machine_ids`). Another machine answers 404.

## What it is counted from

Everything a sorter syncs ([piece-data.md](piece-data.md)):

| What | Where Hive keeps it | Data type |
|---|---|---|
| Every piece: when it was seen, the bin it went into and when, its part and colour, the operator's verdict | `machine_pieces` (`seen_at`, `bin_x`/`bin_y`/`bin_z`, `recorded_at`) | `piece_records` |
| Lots and sorting runs | `machine_lots`, `machine_sorting_runs` | `sorting_runs` |
| Pieces sent back to be sorted again | `machine_sent_back_pieces` | `sent_back_pieces` |
| Each emptying of a bin | `machine_bin_emptyings` | `bin_emptyings` |
| Every layout the machine ran: its bins, what each was assigned and what the profile called it | `machine_bin_layouts` | `bin_layouts` |

The rules, which match the machine's own counts:

- **A piece went into a bin** when the machine recorded it there:
  `recorded_at` is when it was distributed.
- **It belongs to the sorting run** whose stretch holds its `seen_at` (a run
  lasts from its start until the next run starts).
- **A lot's pieces** are those seen in the runs that add to it, those the
  machine reaped as stuck (`dead`) left out, less those sent back. A run that
  names the lot without adding to it is another pass over pieces the lot
  already counted. These are the machine's own lot and run counts
  (`sorting_runs.py` on the sorter).
- **An emptying** took the pieces put in its bin after the bin's emptying
  before (or ever, for the first one), up to it.
- **What a bin holds now** is what went in after its last emptying. A machine
  only knows of an emptying when someone clears the bin on it; a person who
  empties a bin by hand and records it elsewhere (an inventory app) says when
  with `put_in_after`, and the later of the two counts.
- **A piece sent back** left its bin: it is in no item and no count but
  `sent_back`.
- **An item** is a part in a colour, named by BrickLink's ids as the machine
  reports them: `bricklink:3001/5`, or `bricklink:3001` when the colour is
  unknown. Its colour is the operator's correction when they gave one (the
  sentinel `any_color` counts as unknown), else the machine's. A piece the
  machine did not classify, or whose part the operator said is wrong, has no
  item: it counts in `unidentified`.

Bins are numbered from 1, as the sorter shows them: `"key": "L1-S2-B4"` is
layer 1, section 2, bin 4 (`layer`, `section`, `bin` say the same as numbers).
The machine itself numbers them from 0 (`bin_x`, `bin_y`, `bin_z`).

## Endpoints

Every answer names its `machine` (`id`, `name`). Times are ISO 8601 in UTC.

| Request | Answer |
|---|---|
| `GET /machines` | The caller's machines, each with `synced` (how far each stream above has synced: `pieces`, `sent_back`, `emptyings`, `layouts`, `runs`) and `version`, which changes whenever any of them does. |
| `GET /machines/{id}/lots` | Its lots, oldest first, each with its `runs` (those that add to it and the passes). |
| `GET /machines/{id}/lots/{lot}` | A lot's inventory: `pieces`, `unidentified`, `sent_back`, `items` (most first), `first_put_in`, `last_put_in`, and its `runs`. |
| `GET /machines/{id}/runs` | Its sorting runs, oldest first, with `started_at`, `ends_at`, `lot_id`, `adds_to_lot`. |
| `GET /machines/{id}/runs/{run}` | A run's pieces the way its lot counts them, in items. |
| `GET /machines/{id}/bins` | Every bin of the layout it runs: `size`, `bins_in_section`, `enabled`, `not_in_inventory`, `max_dimension_mm`, the `categories` it is assigned (`id`, `name`), its `last_emptying`; and the `layout` (when it changed, the profile, the layers). `at=TIME` gives the layout it ran then. `run=ID` adds each bin's `assignments` during that run: every set of categories it held, `since` and `until`. |
| `GET /machines/{id}/contents` | The pieces put in its bins, per bin: `pieces`, `unidentified`, `sent_back`, `items`, `first_put_in`, `last_put_in`. Of what each bin holds now (`since` says from when), or with `run=ID` what each bin got in that run, or with `emptying=ID` what that emptying took. `put_in_after` and `put_in_before` narrow by when the pieces went in; `bins=L1-S1-B1,L1-S1-B2` to some bins. |
| `GET /machines/{id}/emptyings` | Every emptying, in the order the machine recorded them, `limit` (20, at most 100) a page: pass `next` back as `after` until it is null. Each: `bin`, `emptied_at`, `scope` (the clear covered this `bin`, its `layer` or `all` of them), `machine_count` (what the machine counted in the bin), `categories`, `profile`, and the pieces it took (as in contents) unless `items=false`. `bin=L1-S1-B1` gives one bin's. |

## Keeping a copy

An app that keeps its own copy keeps each machine's `version` and asks again
for what it keeps when it changes. Emptyings never change: keep the last `id`
and ask for those after it. Lots, runs and layouts are small and come whole.
A piece at a time, with every colour people and models gave it: the records
API (`/api/records/machines/{id}/pieces`, `records:read`).

## Limits

Every read is one range of an index that leads with the machine and either the
bin (`ix_machine_pieces_bin_recorded_at`) or the time
(`ix_machine_pieces_machine_seen_at`), and one answer reads at most
`inventory.WINDOW` (50,000) pieces: a request that would read more answers 422
`TOO_MANY_PIECES`, asking for fewer bins or a shorter stretch, rather than a
partial count. What a bin holds now for a machine that has not sent its layout
yet answers 409 `NO_LAYOUT` unless `bins` names them.
