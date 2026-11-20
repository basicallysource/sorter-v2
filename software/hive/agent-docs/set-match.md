# Which sets are in a lot

A sorter keeps lots: a batch of bulk LEGO whose every piece it has identified
(part, color, count, in BrickLink's ids). `POST /api/machine/sets/match` takes
a lot's inventory and answers which LEGO sets it could be (partly) built from,
likeliest first, for a "sets in this lot" list on the sorter's dashboard. It
returns nothing when nothing really matches.

Code: `backend/app/services/set_match.py` (the index and the matching),
`backend/app/routers/machine_sets.py` (the endpoint),
`sorter-client/hive_client.py` (`HiveClient.match_sets`).

## The endpoint

Machine token (`Authorization: Bearer <token>`, `get_current_machine`), like
every `/api/machine/...` route.

```json
POST /api/machine/sets/match
{
  "inventory": [{"part_id": "3001", "color_id": 5, "quantity": 12}],
  "limit": 20,
  "missing_limit": 30,
  "exclusive": true,
  "min_set_pieces": 20,
  "min_distinctive_lines": 3,
  "min_evidence": 10.0,
  "min_distinctive_share": 0.6,
  "min_share": 0.4,
  "distinctive_chance": 0.1
}
```

Only `inventory` is required; the rest are the defaults. `part_id` is a
BrickLink item number (a Rebrickable part number works too), `color_id` a
BrickLink color id (a number or its text; null when the sorter did not name
one). Lines of one part and color are added up. At most 50,000 lines.

```json
{
  "sets": [
    {
      "set_num": "8084-1",
      "name": "Snowtrooper Battle Pack",
      "year": 2010,
      "image_url": "https://cdn.rebrickable.com/media/sets/8084-1.jpg",
      "num_parts": 74,
      "total_pieces": 58,
      "required_pieces": 54,
      "covered_pieces": 30,
      "share": 0.5556,
      "distinctive_lines": 4,
      "distinctive_lines_present": 3,
      "distinctive_pieces": 6,
      "distinctive_pieces_present": 4,
      "distinctive_share": 0.6669,
      "evidence": 9.77,
      "wrong_color_pieces": 9,
      "not_required_pieces": 4,
      "score": 6.52,
      "same_contents": [],
      "missing_lines": 19,
      "missing": [
        {
          "part_num": "6120",
          "part_name": "Sports Ski with Hinge",
          "color_id": 85,
          "color_name": "Dark Bluish Gray",
          "needed": 2,
          "have": 1,
          "missing": 1,
          "in_other_colors": 0,
          "other_colors": [],
          "sets_with_it": 12,
          "distinctive": true
        }
      ]
    }
  ],
  "matched_sets": 1,
  "exclusive": true,
  "inventory": {"lines": 1949, "pieces": 4098, "unknown_part_pieces": 17, "unknown_color_pieces": 0},
  "thresholds": {"min_set_pieces": 20, "min_distinctive_lines": 3, "min_evidence": 8.0,
                 "min_distinctive_share": 0.6, "min_share": 0.4, "distinctive_chance": 0.1},
  "catalog": {"sets": 18864, "synced": {"profile_catalog.last_sync.sets": "..."}},
  "took_ms": 79.6
}
```

(That answer was asked for with `min_evidence` 8; with the defaults the same
lot returns `"sets": []`.)

| Field | Meaning |
|---|---|
| `num_parts` | Rebrickable's piece count for the set, its minifigures' parts included |
| `total_pieces` | The pieces of the set's own inventory, spares left out |
| `required_pieces` | Those of them a set needs to count as built (below) |
| `covered_pieces`, `share` | Required pieces the lot has, the part in its own color, each line capped at what it needs; and that over `required_pieces` |
| `distinctive_lines`, `distinctive_pieces` | The set's required lines the lot had little chance of holding, and their pieces |
| `..._present` | Those of them found (a line with at least one piece; the pieces found) |
| `evidence`, `distinctive_share` | The surprise of the distinctive lines found, and that over the surprise of all the set's distinctive lines |
| `wrong_color_pieces` | Missing pieces the lot has in another color. Never counted as covered |
| `not_required_pieces` | Stickers, printed parts and minifigure body parts in the set's inventory |
| `same_contents` | Other set numbers with exactly these lines (one box, several numbers) |
| `missing` | Required lines the lot is short of, the most unusual first, `missing_limit` of the `missing_lines`. `color_id` is BrickLink's; `part_num` is the set's own (Rebrickable's) |
| `matched_sets` | How many sets passed; `sets` holds the first `limit` |
| `inventory.unknown_part_pieces` | Pieces whose part id the catalog cannot place in any set |

While the web process has not built its index yet (the first call after a
start), the answer is `503` with code `SET_INDEX_BUILDING` and
`details.retry_after_s`: ask again.

## What a set needs

- The lines of the set's first inventory version (the set as released), spares
  left out. Hive's catalog has the sets' own inventories, not their
  minifigures' (Rebrickable keeps those apart), so minifigures are not asked
  for.
- **Not required**: stickers, printed and patterned parts, minifigure and
  minidoll body parts (heads, torsos, legs, hair, hats). A sorter rarely names
  one as its own part, so a set would never look complete. Minifigure
  accessories and tools stay required.
- **Mold variants are one part** where the catalog can tell: the Rebrickable
  parts that share a BrickLink item number (BrickLink `4287` is Rebrickable's
  `4287a`, `4287b` and `4287c`), and the parts numbered the same but for a
  closing letter (`3062a`, `3062b`), in families of up to four. A camera
  cannot tell them apart.
- **Color is exact.** The same part in another color is `wrong_color_pieces`
  and each missing line's `in_other_colors`, never covered.
- A set whose lines are exactly an earlier set's is matched once, as the
  earlier number, and listed in its `same_contents`.

## The scoring

A set's share of pieces found says little by itself. Measured on a real
4,098-piece mixed lot (1,949 part + colors): 995 sets of 20 pieces or more
have half their pieces in it and 38 have four fifths, almost all of them
small models of plain bricks. A made-up lot of 40,000 common bricks covers
half of 8,086 sets.

What tells is a set's distinctive lines: a part in a color that few sets
contain. How few is few depends on the lot, so the weight is read off the lot:

- Every part + color some set requires is in a rarity band by how many sets
  contain it (1, 2, 3, 4, 5, 6, 7, 8 to 9, ... a quarter of a doubling each).
- **Chance** of a band: the share of its part + colors that the lot holds
  (smoothed, and never lower for a commoner band than a rarer one). It is the
  odds that a part + color that rare turns up in a lot like this one.
- **Surprise** of a line: `ln(1 / chance)`. An inverse document frequency
  that knows the lot's size.

| A part + color contained by | 1 set | 5 | 10 | 20 | 50 | 100 sets |
|---|---|---|---|---|---|---|
| chance in the 4,098-piece lot | 0.1% | 0.5% | 1.6% | 4.7% | 11% | 23% |
| chance in a simulated 46,000-piece lot | 1.1% | 6% | 11% | 25% | 49% | 80% |

- A line is **distinctive** when its chance is at most `distinctive_chance`
  (10%): contained by up to about 40 sets for a lot of 4,000 pieces, about 8
  for one of 40,000.
- **Evidence**: the surprise of the set's distinctive lines found, a line
  found in part counting in part (1 of the 4 a set needs is a quarter). Only
  distinctive lines count. The small surprises of commoner lines are not
  added up: a lot of plain bricks holds hundreds of them at once, for every
  set of plain bricks.
- **Distinctive share**: evidence over the surprise of all the set's
  distinctive lines.

Sets are ordered by `score`, evidence times distinctive share.

## What is returned, and what is not

A set is returned when all of these hold:

| Parameter | Default | Why |
|---|---|---|
| `min_set_pieces` | 20 | Smaller sets are too small to tell from chance |
| `min_distinctive_lines` | 3 | One or two unusual parts turn up by accident |
| `min_evidence` | 10.0 | Three lines at one chance in thirty each. At 8, one of 64 lots with no set in them returned a set; at 10 and 12 none did |
| `min_distinctive_share` | 0.6 | Most of what is distinctive about the set is there. A big set has hundreds of unusual lines and any big lot holds some of them |
| `min_share` | 0.4 | A fair share of the set's pieces is there too |

So a significant share of pieces alone is never enough, and neither are a few
rare parts of a big set. Common bricks carry no evidence at all: lots of
common bricks only returned nothing at every size tried.

**One set per piece (`exclusive`, on by default).** Sets of one theme and year
share their unusual parts, so a set in a lot brings its siblings along. The
sets that pass against the whole lot are taken likeliest first, each one's
pieces out of the lot before the next is matched again, and a set that no
longer passes is dropped; each returned set's numbers are against what the
sets before it left. With `exclusive` false every set is matched against the
whole lot.

### How the defaults were measured

On a production-size catalog (Rebrickable's downloads of 2026-11-20: 28,670
sets, 18,864 distinct contents, 1.26 million lines, 77,770 part + colors):

- **Simulated lots**, ten of them, of 4,000 to 46,000 pieces: sets drawn at
  random from a span of years, each present whole or at 80%, 50% or 25%, 5%
  of pieces lost, 4% in a wrong color, 4% as a wrong part, and 15% more loose
  pieces from no set. Of 761 sets put in, 239 were returned (180 of the 372
  put in whole), and 4 that were not put in, 3 of them near twins of one that
  was (two versions of one box). Without `exclusive` (seven of those lots, at
  `min_evidence` 12) 25 sets that were not put in came back, with it 2.
- **The sets not returned** had fewer than three distinctive lines for a lot
  that size, or were mostly missing. That is the price of never matching on
  common bricks: in a lot of 40,000 pieces about a third of the whole sets
  can be told, in one of 4,000 most.
- **Lots with no set in them**, 64 of them, of 2,000 to 40,000 pieces, drawn
  from common bricks only or from every part + color by how often sets use
  it: none returned a set.
- **The real lot** above returns nothing: it is loose bricks. Its nearest set
  (the example answer) has 3 of its 4 distinctive lines and 30 of 54 pieces,
  with evidence 9.8.

Loosen `min_evidence` or `min_distinctive_share` to see nearer misses; the
answer's `thresholds` says what was used.

## The index

`build_index` reads parts.db once into numpy arrays: every set's lines, and
for every part + color the sets that require it and how many (an inverted
index). Matching pulls one slice of that index per part + color the lot has
and adds them up per set, so every set is scored in a few array passes.

- **When.** `SetMatchService` builds it on a thread at the first request of a
  process, and again when a catalog sync has changed parts.db (it compares the
  sets, parts and colors sync times at most once a minute; the index in use
  serves until its replacement is whole). Only a process that answers requests
  ever builds it.
- **Cost**, measured on a 2-vCPU, 4 GB server with the production-size
  catalog: 23 to 32 seconds to build (reading 1.5 million inventory lines from
  disk), about 155 MB while building, 33 MB of arrays kept, plus the part
  lookups. A lot of 1,949 lines is matched in about 80 ms, one of 7,300 lines
  (46,000 pieces) in about 120 ms.
- **No tables, no migration.** The index is derived, so nothing is stored.

## What the catalog lacks

- **Rebrickable's part relationships are not imported.** Mold variants and
  alternates come from shared BrickLink numbers and part-number letters, which
  misses alternates numbered differently (`3794b` and `15573`) and joins a few
  lettered families that are not variants (a left and a right wing). Importing
  `part_relationships.csv` with the sets sync and reading its `M` and `A` rows
  in `_mold_variants` would replace both guesses.
- **Minifigures' inventories are not imported**, so a set's minifigures are
  never asked for or reported.
- **A part added since the catalog moved to Rebrickable's downloads has no
  BrickLink number** (the downloads carry none): it is matched only when
  BrickLink numbers it as Rebrickable does. 4,058 of the 41,585 parts in set
  inventories have none, on 0.4% of the lines.
- **BrickLink assemblies and printed items a sorter names** (`3680c01`,
  `3068pb1684`) mostly have no part in a set inventory and count as
  `unknown_part_pieces` (17 of the real lot's 4,098 pieces).
