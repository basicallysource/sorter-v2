---
layout: default
title: Sorting profile reference
type: reference
audience: contributor
applies_to: Sorting profiles compiled by Hive (schema_version 2) and the older flat part map (schema_version 1)
owner: sorter
slug: sorter-profile-reference
kicker: SorterOS — Configuration reference
lede: "What a sorting profile is made of and what the machine's file looks like: rules, conditions, groups, kits, the fallback, and the compiled program the machine runs."
permalink: /sorter/profile-reference/
---

A sorting profile is the rulebook that tells SorterOS which bin a piece belongs in. There are two forms of it:

- **The profile** is what people and assistants edit in Hive: an ordered list of rules, a fallback, and a default bin. Hive keeps every saved version.
- **The compiled profile** is what Hive hands a machine for one version. It holds the profile and, next to it, the **program**: the same rules turned into plain lookups, with every catalog field already worked out. The machine does not evaluate conditions: it looks the piece's part and color up in the program.

A machine keeps the one it runs in `active_sorting_profile.json` in the backend folder, and the profiles it has saved or uploaded in `sorting_profiles/` beside it. A machine runs one profile at a time. The backend loads it again when a profile is activated or updated, and from the **Reload** button on the Profiles page. No restart is needed.

If you are making your first profile rather than reading one, start with [build your first sorting profile]({{ '/hive/first-profile/' | relative_url }}). Edit profiles in Hive and activate them again. The compiled fields below are generated, and a hand edit to them is lost the next time the profile is compiled.

## How a piece is routed

The machine tells the profile two things about a piece: its part (a BrickLink part ID, or the Rebrickable number when the part has no BrickLink ID) and its color (a BrickLink color ID, or none when the color could not be told). Everything else a rule can test, such as category, name, year or price, was looked up from the catalog when Hive compiled the profile.

The program is tried from the top, and the first entry that takes the piece decides its bin:

1. **Rules, in order.** A rule that does not take the piece passes it on to the next. A color rule takes only the colors it names, so every other color carries on down the list.
2. **The fallback**, if the profile has one: one bin per BrickLink category, per Rebrickable category, or per color.
3. **The default bin**, `misc`, shown in Hive as **Everything else**.

`misc` never claims a real bin. Pieces in it fall through to the discard bin below the machine. [Send it to your machine]({{ '/hive/first-profile/send-it-to-your-machine/#pieces-that-go-to-the-discard-bin' | relative_url }}) covers that and what happens when a category has no bin free.

A bin is a **category**, and a category is a rule's `id`. The machine assigns bins by category ID, so a rule keeps its ID when it is edited. The fallback's categories are `bl_<id>` for a BrickLink category, `rb_<id>` for a Rebrickable one and `color_<id>` for a color.

## Top-level fields of the compiled profile

| Field | Type | Purpose |
|---|---|---|
| `schema_version` | int | `2` for a file with a program. Files from before the program are `1` and carry `part_to_category` instead. The loader does not check the number: it runs the file's `program` if it has one, and its `part_to_category` if it does not. A file with neither is refused. |
| `id`, `name`, `description` | string | The profile's own. `id` is empty for a profile that was never in Hive. |
| `profile_type` | string | `"set"` when any rule is a kit, otherwise `"rule"`. |
| `default_category_id` | string | The default bin. `"misc"` unless the profile says otherwise. |
| `fallback_mode` | object | See [The fallback](#the-fallback). |
| `rules` | array | The profile's rules, as Hive read them. See [Rules](#rules). |
| `categories` | object | Every bin by category ID, described for people: `name`, `kind` (`rule`, `kit`, `fallback` or `default`), `image_url`, its conditions in words, how many parts it takes and a few examples. The Profiles page draws its cards from this. |
| `category_order` | array | Category IDs in the order to show them: the rules in order, then the fallback's categories with the most parts first, then the default. |
| `program` | object | What the machine runs. See [The program](#the-program). |
| `set_inventories` | object | Present when a rule is a kit: each kit's lines. See [Kits](#kits). |
| `requires` | array | Features a machine needs to run this version. Today only `color_fallback`. |
| `stats` | object | Counts from compiling, for display. Regenerated, never edited. |
| `artifact_hash` | string | SHA-256 of the compiled profile. See [`artifact_hash`](#artifact_hash). |

## Rules

An ordered list. Each rule is one bin. This one takes red tiles and blue plates:

```json
{
  "id": "red-tiles-blue-plates",
  "rule_type": "filter",
  "name": "Red tiles and blue plates",
  "disabled": false,
  "match_mode": "any",
  "conditions": [],
  "children": [
    {
      "id": "red-tiles",
      "name": "Red tiles",
      "match_mode": "all",
      "conditions": [
        { "id": "a1", "field": "bl_category_id", "op": "eq", "value": 37 },
        { "id": "a2", "field": "color_id", "op": "eq", "value": 4 }
      ]
    },
    {
      "id": "blue-plates",
      "name": "Blue plates",
      "match_mode": "all",
      "conditions": [
        { "id": "b1", "field": "bl_category_id", "op": "eq", "value": 26 },
        { "id": "b2", "field": "color_id", "op": "eq", "value": 1 }
      ]
    }
  ]
}
```

In it, `37` is BrickLink's Tile category, `26` its Plate category, and `4` and `1` are Rebrickable's Red and Blue.

| Field | Notes |
|---|---|
| `id` | The rule's bin. Keep it when you change a rule and give a new rule a new one. |
| `rule_type` | `"filter"` (the default) for a rule made of conditions, or `"kit"` for a kit. `"set"` is the form kits had before they were their own thing: it still compiles, and saving a version turns each one into a kit and a kit rule that keeps its `id`. |
| `name` | The bin's name. |
| `disabled` | If `true`, the rule is skipped and its pieces go on to the rules below. |
| `match_mode` | `"all"` (every condition) or `"any"` (at least one). `"all"` when missing. |
| `conditions` | See [Conditions](#conditions). |
| `children` | Groups inside the rule. See [Groups](#groups-and-or-and-not). |
| `image_url` | The picture the bin is shown by. Without one, the bin shows its best known part. |
| `kit_id` | For a kit rule, the kit it collects. |

A rule with no conditions takes nothing, and so does a rule with a condition that cannot be evaluated. Hive warns about both when it compiles. It also warns when a rule can never get a piece, because the rules above it take everything it matches (`taken_above`), when no catalog part matches it (`matches_nothing`), and when a rule above takes every piece (`unreachable`).

### Conditions

A condition is `{ "id", "field", "op", "value" }`. Every field has one type, and the value is read as that type before anything is compared: the BrickLink ID `3001` typed as a number and as text mean the same part. A condition that cannot be read (an unknown field, an operator its type does not take, a value that is not of the type, a pattern that does not compile) is a **problem**. Hive's preview lists it, and saving a version is refused with every problem listed.

| `op` | Meaning |
|---|---|
| `eq`, `neq` | Is, and is not, this value. |
| `in`, `not_in` | Is one of, and is not one of, a list. |
| `contains` | The text contains this, ignoring case. |
| `regex` | The text matches a Python regular expression, ignoring case. The pattern may match anywhere in the text: anchor it with `^` and `$` to match the whole. |
| `gte`, `lte` | At least, and at most (numbers). |

Which operators a field takes follows its type: text takes `eq`, `neq`, `in`, `not_in`, `contains` and `regex`, numbers take `eq`, `neq`, `in`, `not_in`, `gte` and `lte`, and a yes or no takes `eq` and `neq`. A field's own list in the editor can be shorter. A field that names a part, a color or a category is compared by ID, so the editor offers only `eq`, `neq`, `in` and `not_in` for it.

A BrickLink ID is a list type, because a part can carry several (a mold and its aliases). A condition on it holds when any of them does.

**Colors in conditions are Rebrickable color IDs**, which is what the catalog lists, and not the BrickLink IDs a machine reports. Hive translates when it compiles. `GET /api/profile-catalog/colors` lists each color with both IDs.

| `field` | Type | What it reads |
|---|---|---|
| `name` | text | The part's Rebrickable name. |
| `part_num` | text | Its Rebrickable part number. |
| `bricklink_id` | text list | Its BrickLink part IDs. |
| `bl_catalog_name`, `bricklink_primary_item_no` | text | Its name and primary item in BrickLink's catalog. |
| `bricklink_item_count` | int | How many BrickLink items the part has. |
| `color_id` | int | The color, as a Rebrickable color ID. |
| `bl_category_id`, `bl_category_name` | int, text | Its BrickLink category. `bl_catalog_category_id` is an older name for `bl_category_id`. |
| `category_id`, `category_name` | int, text | Its Rebrickable category. |
| `year_from`, `year_to` | int | The first and the last year it was made. |
| `bl_catalog_year_released` | int | The year BrickLink says it was released. |
| `bl_catalog_is_obsolete` | yes or no | Whether BrickLink lists it as obsolete (stored as `1` or `0`). |
| `bl_catalog_weight` | number | Weight in grams. |
| `bl_catalog_dim_x`, `_y`, `_z` | number | Length, width and height in studs. |
| `bl_price_min`, `_max`, `_avg`, `_qty_avg`, `_lots`, `_qty` | number | BrickLink's price guide for the part's most traded color: used sales of the last six months, or used pieces for sale now when none sold. Prices are in dollars. |
| `bl_price_<section>_<metric>` | number | The same, for one section only: `inv_new` and `inv_used` (for sale now) or `ord_new` and `ord_used` (sold in the last six months), with `min`, `max`, `avg`, `wavg`, `lots` or `qty`. |

The price fields read the part's most traded color, not the color of the piece in front of the machine. `bl_price_unit_quantity` and `bl_price_total_quantity` are older names for `bl_price_lots` and `bl_price_qty`. Hive serves the live list, with what each value names, at `GET /api/profile-catalog/fields`.

### Groups: and, or, and not

`children` holds groups. A group has its own `match_mode` and `conditions`, and may hold groups of its own. It is not a bin. It is worked out alone, and its answer counts as one more true or false next to the rule's own conditions, which the rule's `match_mode` then combines. That is how a rule mixes and with or: in the example above the rule is `any` of two groups, and each group is `all` of its two conditions.

- A group that is `disabled` is left out.
- The editor offers groups two levels deep. The compiler sets no limit.
- **There is no `not` around a group.** A condition can be negated with `neq` or `not_in`. To leave something out of a rule, put the rule that wants it above and let the rest carry on.

### Kits

A kit rule is `{ "id", "rule_type": "kit", "kit_id", "name" }`. A kit is parts in colors with quantities. The compiled profile keeps each kit's lines as they were when the version was saved, so changing a kit later changes nothing until a new version is saved.

```json
"set_inventories": {
  "<kit rule id>": {
    "kit_id": "…",
    "set_num": "10266-1",
    "name": "NASA Apollo Saturn V",
    "parts": [
      { "part_num": "3001", "color_id": 5, "quantity": 12 }
    ]
  }
}
```

`part_num` is a BrickLink part ID and `color_id` a BrickLink color ID. A line with no color has `color_id` `-1`, and a piece of any color counts toward it. Hive warns about such lines (`kit_any_color`), about a kit with no parts (`kit_empty`), and about a kit whose parts rules above it already take (`kit_parts_taken_above`).

On the machine, `SetProgressTracker` (`set_progress.py`) counts the pieces sent to each kit's bin. Counts are saved to the machine (at most every five seconds) and kept across restarts. A kit rule takes a piece only while its kit still needs that part in that color. Once a line has its quantity, the rule stops taking it and the piece goes on to the next rule that takes it.

## The fallback

```json
"fallback_mode": {
  "by_color": false,
  "bricklink_categories": true,
  "rebrickable_categories": false
}
```

The fallback takes every piece no rule takes. Hive reads the three flags as **one** choice, and if several are set it takes BrickLink categories first, then Rebrickable categories, then color. All `false` means the pieces no rule takes go to `default_category_id`.

| Flag | Effect |
|---|---|
| `bricklink_categories` | One bin per BrickLink category (`bl_<id>`). |
| `rebrickable_categories` | One bin per Rebrickable category (`rb_<id>`). |
| `by_color` | One bin per color (`color_<id>`, a BrickLink color ID). A piece whose color is not known goes to the default bin. |

A part with no category in the catalog goes to the default bin. Sorting the rest by color needs current software on the machine, and a machine that lacks it is not offered a profile that does so (`requires` lists `color_fallback`).

## The program

```json
"program": {
  "format": 1,
  "rules": [
    { "category": "4340bd3e-…", "parts": ["3001", "3002"], "colors": ["5", "6"] },
    { "category": "7c1f02aa-…", "parts": null, "colors": ["0"] },
    { "category": "9d3e5b10-…", "kit": { "3001": ["5", null] } }
  ],
  "fallback": { "by": "category", "map": { "3003": "bl_5" } },
  "default": "misc"
}
```

`rules` is an ordered list, and the first entry that takes a piece wins.

- **A rule entry** has `category`, `parts` and `colors`. `parts` is a list of part IDs, or `null` for any part. `colors` is a list of BrickLink color IDs, or `null` for any color. It takes a piece whose part and color are both allowed. A piece with no color never matches an entry that lists colors.
- **A kit entry** has `category` and `kit`, a map from a part ID to the colors it is collected in, where `null` stands for any color. It takes the piece only while the kit still needs it.
- A rule can compile to several entries, one for each group of colors that gives a different answer. A rule that only tests color is one entry with `parts: null`, instead of one entry per part and color.
- `fallback` is `{ "by": "category", "map": { part: category } }`, `{ "by": "color" }`, or `null`.
- `default` is the default bin.

## Files from before the program

A machine on software from before the program reads a flat map instead, and Hive builds it on request from the program, rule by rule, with the first claim winning, so both route every piece the same way.

```json
"part_to_category": {
  "any_color-3001": "4340bd3e-…",
  "5-3001": "7c1f02aa-…"
}
```

Keys are `"{color_id}-{part_id}"` with a BrickLink color ID, or `any_color-{part_id}`. The lookup order is:

1. `{color_id}-{part_id}`, the color-specific entry.
2. `any_color-{part_id}`.
3. `default_category_id`.

Parts that end up in the default bin are left out of the map. Two things differ for such a machine. It keeps sending a piece to a kit's bin after the kit is full, because it cannot pass it on. A profile that sorts the rest by color is not offered to it.

A file that has a `program` is always run from it, and a `part_to_category` beside it is ignored.

## `artifact_hash`

A SHA-256 over the compiled profile. It is used for:

1. **Kit counts.** The machine keeps one set of counts, saved with the hash of the profile they were counted for. When a profile with a different hash is loaded, the counts start again from zero. Loading the same profile again keeps them.
2. **Telling Hive what runs.** The machine reports the hash when a version is activated.

A new version of a profile that changes any rule, the order, a kit's lines or the fallback has a new hash. Do not edit it by hand.

## Checking where a piece goes

- On the machine, **Profiles** has a **Where would a piece go?** panel (a BrickLink part and a color), and `GET /api/sorting-profiles/route?part_id=…&color_id=…` answers the same for the profile running now, kit counts included. Nothing moves.
- In Hive's editor, the **Categories** tab has the same question for the draft. `POST /api/profiles/route` answers it for a draft or a saved version, and says why (`rule`, `kit`, `fallback` or `default`).

## The smallest profile

The least a machine's loader accepts is a program. This one sends every piece to a single bin:

```json
{
  "schema_version": 2,
  "name": "Minimal",
  "description": "",
  "default_category_id": "misc",
  "categories": {
    "everything": { "name": "Everything", "kind": "rule" },
    "misc": { "name": "Everything else", "kind": "default" }
  },
  "category_order": ["everything", "misc"],
  "program": {
    "format": 1,
    "rules": [{ "category": "everything", "parts": null, "colors": null }],
    "fallback": null,
    "default": "misc"
  },
  "artifact_hash": ""
}
```

Hive's own files carry more (`rules`, `stats`, `requires`, pictures), and the Profiles page draws from them.

## Related

- [Build your first sorting profile]({{ '/hive/first-profile/' | relative_url }}) is the same thing without the file.
- [SorterOS troubleshooting]({{ '/sorter/troubleshooting/' | relative_url }}) lists symptoms for profile-related misrouting.
