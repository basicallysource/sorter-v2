# Part sizes

Every part's size in mm, measured from its LDraw model, and served in the
`dimensions` block of the piece metadata a sorter fetches
(`GET /api/machine/parts/{part_num}`, built by `profile_engine.db.pieceMetadata`).
A sorter uses it to decide which bins a piece fits: small bins take only small
pieces, and a piece of unknown size can go only to the biggest bins or misc.
So a part with no size costs sorting quality, not just a blank in the UI.

## Where the numbers come from

`part_geometry` in `parts.db` (migration `009_part_geometry_mm.sql`), one row
per id: the bounding box (sorted, largest first), the largest distance across
the part, a volume, and which LDraw file it was measured from. It is filled by
`ldraw_geometry.computeAllGeometry`, which the catalog's `geometry` sync runs
(admin parts page) and `backend/scripts/compute_part_geometry.py` runs
outside Hive, against a local LDraw library and a copy of `parts.db`, for when
the measuring should not load the server. Nothing measures at request time.

`computeAllGeometry` makes two passes:

1. **Every Rebrickable part** (`parts`): its own number, then the LDraw ids
   Rebrickable lists for it, then the base mold of a printed or decorated
   variant (`baseMoldId`: 3001pr0042 is measured as 3001). `geometry_source`
   is `direct` or `parent`.
2. **Every BrickLink number that is not a Rebrickable part number**, from the
   Rebrickable parts it maps to (`part_bricklink_ids`, primary first). A sorter
   predicts BrickLink numbers, and the two catalogs file many common parts
   apart: BrickLink's 3040, 3069, 3068 and 3070 are Rebrickable's 3040b,
   3069b, 3068b and 3070b, and BrickLink's 4073 is Rebrickable's 6141. Without
   this pass a lookup by the number a sorter sends finds no row. When a number
   maps to several parts (4287 is 4287a, 4287b and 4287c), the row takes the
   **largest** of their sizes: a piece predicted as that number may be any of
   them, and must never be sent to a bin too small for it.
   `geometry_source` is `bricklink`, and `physical_parent_part_num` names the
   Rebrickable part the size is from. If none of the parts has a model, LDraw's
   own file of the BrickLink number is tried (for an old number it is often a
   `~Moved to` that points at the current one).

A BrickLink number that is also a Rebrickable part number keeps the Rebrickable
meaning; in the few cases where the two catalogs use one number for different
parts, the size is the Rebrickable part's.

## How a lookup resolves (`resolvePartDimensions`)

| tier | `source` | `confidence` | from |
|---|---|---|---|
| 1 | `ldraw_direct`, `ldraw_parent`, `ldraw_bricklink` | `exact` | the id's own `part_geometry` row |
| 2 | `canonical:<part>` | `family` | a category's stand-in shape (any minifig torso is 973c00) |
| 3 | `studs_footprint` | `coarse` | BrickStore's stud size, x and y only, from the part's BrickLink items or the BrickLink item of that number |
| — | `none` | `none` | nothing found |

An id that is neither a Rebrickable part nor a BrickLink item gets no metadata
at all (a 404), so it has no size either.

## Keeping it current

The geometry is computed, not synced: it changes only when the LDraw library,
the parts list or the BrickLink mapping does. Re-run it after a parts or
BrickStore sync brings in many new numbers. Sorters cache what Hive answered
for two weeks, so a size that was missing reaches a sorter when its cached
entry is refreshed, or at once if its metadata cache is cleared (it is
disposable).
