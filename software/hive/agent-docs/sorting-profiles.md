# Sorting profiles

A sorting profile decides which bin each piece goes to. This is how Hive
stores, compiles and serves them, and what a sorter does with the result.

## The document

What people and assistants edit: an ordered list of **rules**, a
**fallback** and a **default category** (`misc`).

- A **filter rule** (`rule_type: "filter"`) has `conditions` over a part's
  catalog fields and its color (`app/services/profile_engine/fields.py`
  lists every field, its type, its operators and what its values name), a
  `match_mode` (`all` or `any`), and `children`: groups inside it with their
  own mode, combined with the rule's own conditions by the rule's mode. A
  rule without conditions takes nothing.
- A **kit rule** (`rule_type: "kit"`) names a kit (`kit_id`): parts in colors
  with quantities (`app/models/kit.py`). Set rules from before kits
  (`rule_type: "set"`, a set number or a parts list held in the rule) still
  compile; saving a version turns each into a kit of its own and a kit rule,
  keeping the rule's id.
- Every rule may have an `image_url`, the picture its bin is shown by.
- The **fallback** takes what no rule does: one bin per BrickLink category,
  per Rebrickable category, or per color. The document keeps the three old
  switches (`fallback_mode`); they are read as one choice, BrickLink first.

**A rule's id is its bin.** A sorter assigns bins by rule id, so an edit
keeps a rule's id and a new rule gets a new one.

Condition values are coerced to their field's type before anything compares
them (`fields.normalize_condition`): a BrickLink ID sent as the number 3001
is the ID "3001". A condition that cannot be read (unknown field, an operator
its type does not take, a bad pattern) is a **problem**: a preview lists it,
and saving a version is refused with every problem in `details`.

Colors in conditions are Rebrickable color IDs, which is what the catalog
lists; everything a sorter sees is BrickLink IDs (parts and colors), which is
what its classifier reports.

## Compiling

`app/services/profile_engine/compiler.py`, `compile_document`. It runs when
a version is saved and for every preview, so it has to be fast: the catalog
(80,000 parts) is laid out once per catalog generation in a `CatalogIndex`,
one row per part, and each condition is evaluated over a column as a numpy
mask (cached), not by walking the part records. A realistic profile of 50
rules compiles in well under a second.

A rule with color conditions is split by color: every catalog color is given
the truth of each color condition, colors with the same answers are grouped,
and the rule's formula is evaluated once per group. The result for each group
is (parts, colors), where either may be "any".

The output, the **artifact**, holds:

- `program`: what a sorter runs. An ordered list of entries, first match
  wins: `{"category", "parts": [BrickLink IDs] | null, "colors": [BrickLink
  color IDs] | null}` for a filter rule (one entry per color group), or
  `{"category", "kit": {part: [colors, null for any]}}` for a kit rule; then
  the `fallback` (`{"by": "category", "map": {part: category}}` or
  `{"by": "color"}`) and the `default`. A rule that only tests color stays
  one entry with `parts: null`, instead of one entry per part and color.
- `categories`: every bin described for people, keyed by category id (a
  rule's id, `bl_5`, `rb_11`, `color_5`, `misc`): name, kind, picture
  (`image_url`: the rule's own, the kit's, or the rule's best known part),
  its conditions in words (`describe_conditions`: field labels, operators in
  words, values named, with swatches and part pictures), how many parts it
  takes and a few of them, most sold first. `category_order` is the order to
  show them in. Bins limited to some colors are counted and shown by the parts
  BrickLink knows in those colors, when the catalog says.
- `set_inventories`: each kit's lines in the shape a sorter counts them in.
- `stats`, `rules` (the normalized document), `requires` (below) and
  `artifact_hash`.

A version's warnings (a rule nothing reaches, a kit whose parts rules above
it take, a kit line with no color) are kept with its stats, and so are its
first bins (`stats.bins`) for cards that show a profile by its bins without
loading the artifact. The artifact column itself is deferred: it loads only
when read.

## What a sorter downloads

`GET /api/machine/profiles/versions/{id}/artifact`. A current sorter asks
for `format=program` and names what it can run in `features`
(`program,color_fallback,kit_cascade`). A sorter from before the program asks
for neither and gets the **flat map** (`expand_legacy`): `"{color}-{part}"`
and `"any_color-{part}"` to a category, built from the program rule by rule,
first claim wins, so it routes every piece the way the program does (tests
check it against the compiler the program replaced). It is built on request
and kept for the last two versions asked for.

`requires` lists what a sorter must be able to run a version: today only
`color_fallback` (the flat map cannot say "any part in this color"). A sorter
that does not name a required feature is not offered the profile in its
library and is refused its artifact with `PROFILE_NEEDS_NEWER_SORTER`.

On the sorter, `sorting_profile.ProfileRouter` runs the program. A kit entry
takes a piece only while the kit still needs that part and color
(`SetProgressTracker.isFull`); once it has enough, the piece goes on to the
next entry that takes it. A sorter without the program keeps sending such
pieces to the kit's bin.

## Hive's default profiles

`app/services/default_profiles.py` defines profiles every machine gets
without saving them: BrickLink categories, Colors, and Colors and basic
pieces. Hive keeps them itself (owned by a user no one signs in as), public,
with `system_key` and `default_rank`. On every start it compiles each one and
publishes a new version when the result changed (a new definition, or a
catalog update). A sorter with no profile starts on the first one.

## For assistants

Every profile, kit and catalog route a person's browser uses also takes an
API key with the `profiles:read` / `profiles:write` scopes, which any user can
make (`agent-docs/auth.md`); `records:read` adds what the person's own
machines sorted (`/api/records`). Hive serves a skill, `GET
/api/agent/skill.md` (`app/agent/sorting-profiles-skill.md`), that tells an
assistant how to use them. Keep it in step with the routes: it is the
documentation assistants actually read. A version saved through a key
records the key (`created_via`, `created_via_key_id`), and
`GET /api/profiles/{id}/head` is cheap enough for an open page to poll, so a
change an assistant makes shows up on the page within seconds.

`POST /api/profiles/preview` compiles a draft without saving it,
`POST /api/profiles/preview-rule` lists one rule's matches, and
`POST /api/profiles/route` says where given pieces go and why.
