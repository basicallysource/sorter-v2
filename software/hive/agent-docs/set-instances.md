# Set instances

A set instance is one physical copy of a LEGO set a Hive user is extracting
with the sorter. Progress (parts found) belongs to the instance, never to a
machine's profile assignment: it survives profile edits, machine swaps and
re-assignments, and a user may own the same set several times.

## Data

| Table | Purpose |
|---|---|
| `set_instances` | `user_id`, `set_source`, `set_num`, `label`, `status` (`open` / `complete` / `archived`), `include_spares`, `notes` |
| `set_instance_progress` | per instance: `part_num`, `color_id`, `quantity_needed`, `quantity_found`; unique per (instance, part, colour) |

Keys are **BrickLink** part and colour ids, the same keys the compiled profile
artifact's `set_inventories` and the sorter's progress reports use, and what a
BrickLink wanted list needs. Expansion goes through
`ProfileCatalogService.set_inventory_parts()` (shared with the set-rule
compiler), which maps Rebrickable ids to BrickLink ids and fetches the set on a
cache miss.

`open` and `complete` follow the counts automatically; `archived` is set by the
user and never flips back on its own. The legacy `machine_set_progress` table
(keyed by assignment) still serves profiles whose set rules do not name an
instance; the migration `f0e1d2c3b4a5` moved rows over where they did.

## Code

- Models: `app/models/set_instance.py`
- Service: `app/services/set_instances.py` (create with inventory expansion,
  list/update/archive, totals, manual adjust, machine progress apply, missing
  list, wanted-list XML)
- Router: `app/routers/set_instances.py`, prefix `/api/set-instances`, owner
  gated (cookie auth + CSRF on writes)
- Frontend: `/sets` (list + add flow via `SetSearch`), `/sets/[id]` (per-part
  found/missing, manual adjust, wanted-list download, archive)

## Machine sync

`POST /api/machine/set-progress` items may carry `set_instance_id`. Tagged
items are written to that instance (the instance must belong to the machine's
owner, and the part must be in its inventory); the set is then not expected in
the assignment-keyed snapshot. Untagged items follow the legacy path unchanged
(complete snapshot required). Reported `quantity_found` values are absolute
and clamped to `quantity_needed`.

## Wanted list

`GET /api/set-instances/{id}/wanted-list.xml` returns the BrickLink upload
format (`<INVENTORY><ITEM>` with `ITEMTYPE=P`, `ITEMID`, `COLOR`, `MINQTY`)
for every part with `quantity_needed > quantity_found`.
