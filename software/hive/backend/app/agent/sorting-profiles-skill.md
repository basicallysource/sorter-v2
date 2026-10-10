---
name: hive-sorting-profiles
description: Build, test and change the sorting profiles a LEGO sorting machine runs, on the Hive at {{BASE_URL}}. Use when someone asks how their sorter should sort (bins for certain parts, colors, categories or kits), wants a profile checked or changed, or wants to know what their machine has been sorting.
---

# Sorting profiles on Hive

A sorting profile decides which bin each piece goes to. It is an ordered
list of **rules**; every rule is one bin, and a piece goes to the **first**
rule that takes it. Pieces no rule takes go to the profile's **fallback**
(one bin per BrickLink category, per Rebrickable category, or per color) or,
without one, to the default bin, "misc".

You work on profiles through Hive's API, the same one the Hive website uses.
A change you save shows up on the website within a few seconds, marked as
made through the person's key. It reaches a machine only when its owner
applies the profile on that machine.

## Connecting

- Base URL: `{{BASE_URL}}`
- Send the person's key on every request: `Authorization: Bearer hv_...`
- They make the key on Hive under Settings, API keys, with the scopes
  `profiles:read` and `profiles:write` (and `records:read` to see what
  their machines sorted). Never print the key back to them or anyone.
- `GET /api/agent/whoami` says whose key it is, its name and its scopes:
  check it first when something is refused or comes back empty.
- Errors come back as `{"ok": false, "error": "...", "code": "...", "details": [...]}`.
  `details` lists every problem at once; fix them all before trying again.
- Responses can be large (a profile with a fallback has hundreds of bins).
  Save them to a file and read the parts you need rather than printing them.

## The loop

1. **Look things up** in the catalog: parts, colors, categories, sets.
2. **Draft** a document (below) and `POST /api/profiles/preview` it (the body
   is the document itself). Nothing is saved. You get `categories`: each bin
   by id, with its conditions in words, how many parts it takes and a few
   examples; `category_order`; `warnings` (a rule that gets nothing, a kit
   whose parts earlier rules take, a line without a color); `problems`
   (conditions that cannot be evaluated); and `stats`: `sorted` of
   `total_parts` catalog parts go to a bin of their own, the rest to the
   default bin.
3. **Test pieces**: `POST /api/profiles/route` with `{"document": …}` (a
   draft) or `{"profile_id": …}` (saved; `version_id` for an older version),
   and `"pieces": [{"part": "3001", "color_id": 4}]`, says which bin each
   piece lands in and why (`rule`, `kit`, `fallback`, `default`). Kits start
   empty and fill in the order the pieces are listed, so listing five red
   2 x 4s shows where the fifth goes once a kit has its four (`kit_left` is
   what the kit still takes). For rules on the piece itself, a piece can say
   `confidence` and `color_confidence` (0 to 100; 100 when left out) and
   `price`; a piece with no `part` is one recognition could not identify.
   Check every piece the person named.
4. **Look inside one rule**: `POST /api/profiles/preview-rule?rule_id=…`
   (the body is the document; `q`, `offset` and `limit`, 50 by default, page
   through) lists the parts it matches, most sold first. A throwaway rule
   with `name` `matches` a pattern is also a quick way to find parts.
5. **Save**: `POST /api/profiles` for a new profile (`name`, `description`,
   `rules`, `fallback_mode`, `change_note`: its first version), or
   `POST /api/profiles/{id}/versions` with the whole document and a short
   `change_note` for the next version. A profile's `web_url` is its page:
   give the person that link.
6. Tell the person what changed, and that the profile reaches their machine
   when they apply it there (Profiles on the sorter's own page).

## A document

```json
{
  "name": "Workshop",
  "description": "Big bricks apart, trans by itself, the rest by BrickLink category",
  "default_category_id": "misc",
  "fallback_mode": {"bricklink_categories": true},
  "rules": [
    {
      "id": "bricks-2x4",
      "name": "2 x 4 bricks",
      "match_mode": "all",
      "conditions": [{"field": "bricklink_id", "op": "eq", "value": "3001"}]
    },
    {
      "id": "trans",
      "name": "Transparent",
      "conditions": [{"field": "color_id", "op": "in", "value": [47, 36, 34, 33]}]
    },
    {
      "id": "red-plates",
      "name": "Red plates and tiles",
      "conditions": [{"field": "color_id", "op": "eq", "value": 4}],
      "children": [
        {
          "id": "red-plates-kinds",
          "name": "Plates or tiles",
          "match_mode": "any",
          "conditions": [
            {"field": "bl_category_id", "op": "in", "value": [26, 27, 28]},
            {"field": "bl_category_id", "op": "in", "value": [37, 38, 117]}
          ]
        }
      ]
    },
    {"id": "order-42", "rule_type": "kit", "kit_id": "…", "name": "Order 42"}
  ]
}
```

- **Rule IDs are the bins.** A machine's bins are assigned by rule ID, so
  keep a rule's `id` when you change it, and give new rules new IDs (any
  short unique text).
- `match_mode` is `all` (every condition) or `any` (at least one). A rule's
  `children` are groups inside it, each with its own `match_mode` and
  `children`, to any depth; they combine with the rule's own conditions by
  the rule's mode. A rule without conditions takes nothing.
- `negate: true` on a rule or a group takes the opposite: with `any`, **none
  of** its conditions and groups hold; with `all`, **not all of** them do.
  With groups, that is any Boolean formula. "Plates that are not printed":

  ```json
  {"id": "plain-plates", "name": "Plain plates", "match_mode": "all",
   "conditions": [{"field": "bl_category_id", "op": "in", "value": [26, 27, 28]}],
   "children": [{"id": "printed", "name": "Printed", "match_mode": "any", "negate": true,
                 "conditions": [{"field": "name", "op": "contains", "value": "print"},
                                {"field": "name", "op": "contains", "value": "pattern"}]}]}
  ```
- `disabled: true` keeps a rule in the document without using it.
- `image_url` on a rule gives its bin a picture: a URL from
  `POST /api/profile-images` (a JPEG or PNG as the form field `file`), or
  any https picture. Without one, the bin shows its best-known part.
- `fallback_mode` sets one of `bricklink_categories`, `rebrickable_categories`
  or `by_color` to true, or none. Sorting by color needs current sorter
  software; the preview's `requires` says so.
- `fallback_mode.no_bin` says what a machine does when a piece's category
  has no bin and none is free: `"misc"` (it goes to Everything else and the
  run keeps going), `"share"` (the least filled bin takes the category too),
  or left out (the machine's own setting, which by default stops and asks
  the operator). A profile with more categories than the machine has bins
  (a fallback by category or color usually is) should say one; Hive's
  default profiles say `"misc"`.

## Conditions

`GET /api/profile-catalog/fields` lists every field, its type, the operators
it takes, what its values refer to (`ref`, with `refs` saying where each
kind of value is listed) and, where the label does not say it all, a
`description`. The ones used most:

| field | what | example value |
|---|---|---|
| `bricklink_id` | the part's BrickLink ID (any of its IDs) | `"3001"` |
| `part_num` | the part's Rebrickable number | `"3001"` |
| `name` | the part's Rebrickable name (`contains`, `regex`) | `"brick 2 x 4"` |
| `bl_category_id` | BrickLink category | `5` (Brick) |
| `category_id` | Rebrickable category | `11` (Bricks) |
| `color_id` | color, as a **Rebrickable** color ID | `4` (Red) |
| `bl_price_avg` | average used price, last 6 months, US$ | `1.5` |
| `bl_catalog_weight` | weight in grams | `2.3` |
| `year_from` | first year the part was made | `2020` |
| `confidence` | how sure recognition was of the part, 0 to 100 (`gte`, `lte`) | `60` |
| `color_confidence` | how sure it was of the color, 0 to 100 | `80` |
| `identified` | whether recognition named a part at all (`eq`) | `false` |
| `piece_price` | BrickLink's average price for this part **in this piece's color**, US$ | `2` |

The last four are fields of group `Piece` (`"piece": true` in the field
list): what the machine observes about each piece as it sorts, not catalog
facts, so the machine decides them itself. "Pieces it is not sure about go
to a review bin" is a rule at the top with `confidence` `lte` 60; "pieces it
could not identify get their own bin" is `identified` `eq` `false` (such a
piece has no part and no color, counts as 0% confident, and without a rule
for it goes to the default bin). An unknown confidence or price never meets
a threshold. The catalog price fields (`bl_price_*`) read the part's most
traded color; `piece_price` reads the piece's own. Rules on these fields need
current sorter software; the preview's `requires` says `piece_conditions`.

Operators: `eq`, `neq`, `in`, `not_in` (a list), `contains`, `regex`
(text, ignoring case; `regex` is Python's, so `^Plate Round 1 x 1\b`
works), `gte`, `lte` (numbers). Values are read as the field's type, so
`3001` and `"3001"` both work for a BrickLink ID, and a `bool` field
(`bl_catalog_is_obsolete`) takes `true` or `false`. Names are Rebrickable's:
"Plate Round 1 x 1 with Solid Stud", so `contains "1 x 1"` also takes a
"2 x 2 with 1 x 1 cutout"; anchor a pattern when that matters.

**Colors in conditions are Rebrickable color IDs.** `GET /api/profile-catalog/colors`
(`q` filters by name) lists each with its name, RGB and `bricklink_id`, the
ID a machine reports. In what comes back (a bin's colors, a routed piece's
color) `id` is the BrickLink ID and `rebrickable_id` the one conditions take.

`GET /api/profile-catalog/bricklink-categories` lists the categories that
have parts (`all=true` for every one, `q` to filter by name).

## Kits

A kit is parts in colors with quantities: a LEGO set, a customer's order, a
build. A kit rule collects its parts into one bin until each line has its
quantity; after that, pieces of that part go on to the next rule that takes
them. Put kit rules **above** broader rules, or those take the parts first
(the preview warns when they do).

- `POST /api/kits` `{"name", "parts": [{"part": "3001", "color_id": 4, "quantity": 10}]}`.
  `part` is a BrickLink ID or Rebrickable number; give the color as
  `color_id` (Rebrickable) or `bricklink_color_id`. A line with no color
  counts a piece of any color toward it, which is rarely what someone
  wants for an order: ask.
- `POST /api/kits/from-set` `{"set_num": "10283-1"}` makes a kit of a
  set's parts (`include_spares` to add the spares).
- `POST /api/kits/from-bricklink-csv` `{"csv_content", "name"}` from a
  BrickLink wanted list export (columns BLItemNo, BLColorId, Qty).
- `GET /api/kits`, `GET /api/kits/{id}`, `PATCH /api/kits/{id}` (giving
  `parts` replaces every line), `DELETE /api/kits/{id}` (refused while a
  profile uses it).
- In a profile: `{"id": "…", "rule_type": "kit", "kit_id": "<kit id>", "name": "…"}`.
  A profile version keeps the kit's lines as they were when it was saved;
  after changing a kit, save a new version of each profile that uses it.
- A machine counts what each kit rule has collected, line by line. The
  counts belong to the rule (keep its `id`) and its lines, so they carry
  over to a new version: a line the kit still lists keeps its count, up to
  its quantity now. They start again from zero only when the operator resets
  the kit on the machine (Set progress), or when the rule is made anew with a
  new `id`.

## Endpoints

| | |
|---|---|
| `GET /api/profiles?scope=mine` | the person's profiles (`library`, `defaults`, `discover` for others) |
| `GET /api/profiles/{id}` | a profile, its versions, and the current version's rules and bins |
| `GET /api/profiles/{id}/head` | the latest version number, cheap, to see if it changed |
| `POST /api/profiles` | a new profile: `name`, `description`, `rules`, `fallback_mode` |
| `PATCH /api/profiles/{id}` | rename, describe, `visibility` (`private`, `unlisted`, `public`) |
| `POST /api/profiles/{id}/versions` | save the next version: the whole document, `change_note`, `publish` |
| `POST /api/profiles/{id}/versions/{version_id}/publish` | let other people's machines use a version |
| `POST /api/profiles/{id}/fork` | a copy of someone's public profile for the person to change |
| `POST /api/profiles/preview` | a draft's bins, warnings and problems |
| `POST /api/profiles/preview-rule?rule_id=` | the parts one rule of a draft matches |
| `POST /api/profiles/route` | where pieces go: `{"document": …}` or `{"profile_id": …}`, and `pieces: [{"part", "color_id"}]` |
| `GET /api/profile-catalog/search-parts?q=` | parts by name or number |
| `GET /api/profile-catalog/parts/{id}` | one part, by BrickLink ID or Rebrickable number |
| `GET /api/profile-catalog/colors` | colors, with both IDs |
| `GET /api/profile-catalog/bricklink-categories` | BrickLink categories and their part counts |
| `GET /api/profile-catalog/categories` | Rebrickable categories |
| `GET /api/profile-catalog/search-sets?q=` | LEGO sets; `GET /api/profile-catalog/sets/{set_num}` for one set's parts |
| `GET /api/agent/whoami` | whose key this is, its name and scopes |
| `GET /api/records/machines` | the person's machines and how many pieces each sorted |
| `GET /api/records/machines/{id}/parts?since_days=30` | every part and color a machine sorted, most first |
| `GET /api/records/machines/{id}/pieces` | each piece, newest first (`cursor` for more) |

## Using what a machine sorted

To fit a profile to what actually comes through a machine, read
`/api/records/machines/{id}/parts`: the parts and colors it has seen, with
counts. Those IDs are BrickLink's. An empty machine list means this account
has no sorter linked to it (a sorter links to an account from its own
Settings, Hive); if the person's sorter reports to another account, the key
has to come from that one. Give the most common ones their own bins,
group the long tail by category, and route the piece types the person cares
about; then check them with `/api/profiles/route`.

## Care

- Change only what was asked. Before deleting a rule, a profile or a kit,
  or making anything public, ask.
- Preview before every save, and route every piece the person named.
- Profiles from before a change stay as versions; `GET /api/profiles/{id}`
  lists them, so nothing saved is lost.
- A profile with a kit rule has `profile_type: "set"`; nothing else changes.
