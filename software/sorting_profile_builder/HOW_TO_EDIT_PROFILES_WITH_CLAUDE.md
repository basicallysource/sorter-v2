# How to Edit Sorting Profiles Directly (for Claude)

Sorting profiles are JSON files in `software/sorting_profile_builder/profiles/`. You can read and write them directly — no server, no UI, no agent needed.

All commands below should be run from `software/sorting_profile_builder/` using `uv run python -c "..."`.

## Profile structure

```json
{
  "id": "uuid",
  "name": "mine",
  "rules": [
    {
      "id": "uuid",
      "name": "Gray Bricks",
      "match_mode": "all",        // "all" = AND, "any" = OR
      "conditions": [
        {"id": "uuid", "field": "category_id", "op": "eq", "value": 11},
        {"id": "uuid", "field": "color_id", "op": "in", "value": [7, 8, 71, 72]}
      ],
      "children": [],             // nested sub-rules (same structure)
      "disabled": false
    }
  ],
  "categories": {"rule-id": {"name": "Gray Bricks"}, ...},  // auto-managed, mirrors rules
  "part_to_category": {...}       // generated output, must be regenerated after rule edits
}
```

Rule order = precedence. First matching rule wins. Children inherit parent conditions (AND).

## Available fields and operators

| Field | Operators | Value type | Notes |
|-------|-----------|------------|-------|
| `name` | `contains`, `regex` | string | Part name |
| `part_num` | `eq`, `neq`, `in` | string | Rebrickable part number |
| `category_id` | `eq`, `neq`, `in` | int | Rebrickable category ID |
| `category_name` | `contains`, `regex` | string | Rebrickable category name |
| `color_id` | `eq`, `neq`, `in` | int | Rebrickable color ID |
| `year_from` | `eq`, `neq`, `gte`, `lte` | int | Year part was first produced |
| `year_to` | `eq`, `neq`, `gte`, `lte` | int | Year part was last produced |
| `bricklink_id` | `eq`, `neq`, `in` | string | BrickLink item number |
| `bl_category_id` | `eq`, `neq`, `in` | int | BrickLink category ID |
| `bl_category_name` | `contains`, `regex` | string | BrickLink category name |
| `bl_catalog_name` | `contains`, `regex` | string | BrickLink catalog name |
| `bl_price_avg` | `eq`, `neq`, `gte`, `lte` | float | BrickLink average price (used, last 6mo) |
| `bl_price_min` | `eq`, `neq`, `gte`, `lte` | float | BrickLink min price |
| `bl_price_max` | `eq`, `neq`, `gte`, `lte` | float | BrickLink max price |
| `bl_catalog_weight` | `eq`, `neq`, `gte`, `lte` | float | Weight in grams |
| `bl_catalog_dim_x/y/z` | `eq`, `neq`, `gte`, `lte` | float | Dimensions |
| `bl_catalog_year_released` | `eq`, `neq`, `gte`, `lte` | int | BrickLink release year |
| `bl_catalog_is_obsolete` | `eq`, `neq` | 0 or 1 | Obsolete flag |

Operators: `eq` (equals), `neq` (not equals), `in` (value is list, matches any), `contains` (case-insensitive substring), `regex` (case-insensitive regex), `gte` (>=), `lte` (<=).

## Step 0: Look at existing profiles for reference

Before creating new rules, look at the rules in other profiles for examples of how rules are structured. Only read the rules section — don't pull entire profile files into context as they can be very large (the `part_to_category` field is huge).

```python
import json, glob
for f in sorted(glob.glob('profiles/*.json')):
    with open(f) as fh:
        data = json.load(fh)
    print(f"=== {data['name']} ({f}) - {len(data['rules'])} rules ===")
    for i, r in enumerate(data['rules']):
        conds = [(c['field'], c['op'], c['value']) for c in r['conditions']]
        children = f" ({len(r['children'])} children)" if r.get('children') else ''
        print(f"  {i}: {r['name']} [{r['match_mode']}] {conds}{children}")
```

## Step 1: Find the profile file

```python
import glob
files = glob.glob('profiles/*.json')
# files = ['profiles/cb3a66bc-36a8-493c-ada7-930efcc080f7.json']
```

Or by name:
```python
import json, glob
for f in glob.glob('profiles/*.json'):
    with open(f) as fh:
        data = json.load(fh)
    if data['name'] == 'mine':
        print(f)
```

## Step 2: Look up IDs for conditions

### Rebrickable categories
```python
from db import PartsData, initDb, reloadPartsData
conn = initDb('parts.db')
pd = PartsData()
reloadPartsData(conn, pd)

# search by name
for cid, c in sorted(pd.categories.items()):
    if 'brick' in c['name'].lower():
        print(f"  {cid}: {c['name']}")
# Output: 11: Bricks, 5: Bricks Special, 6: Bricks Wedged, etc.
```

### Colors
```python
for cid, c in sorted(pd.colors.items()):
    if 'gray' in c['name'].lower() or 'grey' in c['name'].lower():
        print(f"  {cid}: {c['name']} (rgb={c.get('rgb','?')}, trans={c.get('is_trans',False)})")
# Output: 7: Light Gray, 8: Dark Gray, 71: Light Bluish Gray, 72: Dark Bluish Gray, etc.
```

### Test conditions against the parts database
```python
from rule_engine import previewRule

rule = {
    "conditions": [
        {"field": "category_id", "op": "eq", "value": 11},
        {"field": "color_id", "op": "in", "value": [7, 8, 71, 72]},
    ],
    "match_mode": "all"
}
result = previewRule(rule, pd.parts, categories=pd.categories, bricklink_categories=pd.bricklink_categories, limit=5)
print(f"{result['total']} parts matched")
for p in result['sample']:
    print(f"  {p['part_num']}: {p['name']}")
```

## Step 3: Add a rule

```python
import json, uuid

PROFILE_PATH = 'profiles/cb3a66bc-36a8-493c-ada7-930efcc080f7.json'

with open(PROFILE_PATH) as f:
    data = json.load(f)

new_id = str(uuid.uuid4())
new_rule = {
    "id": new_id,
    "name": "Gray Bricks",
    "match_mode": "all",
    "conditions": [
        {"id": str(uuid.uuid4()), "field": "category_id", "op": "eq", "value": 11},
        {"id": str(uuid.uuid4()), "field": "color_id", "op": "in", "value": [7, 8, 71, 72, 151, 503]},
    ],
    "children": [],
    "disabled": False,
}

# insert at a specific position (0 = first, highest precedence)
data['rules'].insert(5, new_rule)

# also add to categories map (rule id -> name)
data['categories'][new_id] = {"name": new_rule['name']}

with open(PROFILE_PATH, 'w') as f:
    json.dump(data, f, indent=2)

print(f"Added rule '{new_rule['name']}' with id {new_id}")
```

## Step 4: Edit an existing rule

```python
import json

PROFILE_PATH = 'profiles/cb3a66bc-36a8-493c-ada7-930efcc080f7.json'

with open(PROFILE_PATH) as f:
    data = json.load(f)

# find by name
rule = next(r for r in data['rules'] if r['name'] == 'Gray Bricks')

# modify conditions
rule['conditions'] = [
    {"id": str(uuid.uuid4()), "field": "category_id", "op": "eq", "value": 11},
    {"id": str(uuid.uuid4()), "field": "color_id", "op": "in", "value": [7, 8, 71, 72, 151, 503]},
]

# or rename
rule['name'] = 'Gray/Silver Bricks'
data['categories'][rule['id']] = {"name": rule['name']}

with open(PROFILE_PATH, 'w') as f:
    json.dump(data, f, indent=2)
```

## Step 5: Move a rule (change precedence)

```python
import json

PROFILE_PATH = 'profiles/cb3a66bc-36a8-493c-ada7-930efcc080f7.json'

with open(PROFILE_PATH) as f:
    data = json.load(f)

# move "EXPENSIVE" to position 0 (first/highest precedence)
rule = next(r for r in data['rules'] if r['name'] == 'EXPENSIVE')
data['rules'].remove(rule)
data['rules'].insert(0, rule)

with open(PROFILE_PATH, 'w') as f:
    json.dump(data, f, indent=2)
```

## Step 6: Delete a rule

```python
import json

PROFILE_PATH = 'profiles/cb3a66bc-36a8-493c-ada7-930efcc080f7.json'

with open(PROFILE_PATH) as f:
    data = json.load(f)

rule = next(r for r in data['rules'] if r['name'] == 'Gray Bricks')
data['rules'].remove(rule)
del data['categories'][rule['id']]

with open(PROFILE_PATH, 'w') as f:
    json.dump(data, f, indent=2)
```

## Step 7: Add a child rule (sub-rule)

Child rules are nested inside a parent. A part must match both the parent AND the child.

```python
child_id = str(uuid.uuid4())
child_rule = {
    "id": child_id,
    "name": "1x1 Gray Bricks",
    "match_mode": "all",
    "conditions": [
        {"id": str(uuid.uuid4()), "field": "name", "op": "contains", "value": "1 x 1"},
    ],
    "children": [],
    "disabled": False,
}

parent = next(r for r in data['rules'] if r['name'] == 'Gray Bricks')
parent['children'].append(child_rule)
data['categories'][child_id] = {"name": child_rule['name']}
```

## Step 8: Generate profile (required after editing rules)

After all rule edits are done, regenerate `part_to_category`. This is the same "Generate" action from the UI.

```python
from db import initDb, PartsData, reloadPartsData
from sorting_profile import loadSortingProfile, saveSortingProfile
from rule_engine import generateProfile

PROFILE_PATH = 'profiles/cb3a66bc-36a8-493c-ada7-930efcc080f7.json'
PROFILES_DIR = 'profiles'

conn = initDb('parts.db')
pd = PartsData()
reloadPartsData(conn, pd)

sp = loadSortingProfile(PROFILE_PATH)
result = generateProfile(
    sp,
    pd.parts,
    pd.categories,
    pd.bricklink_categories,
    fallback_mode=sp.fallback_mode,
    parts_generation=pd.generation,
    rb_to_bl_color=pd.rb_to_bl_color,
)

sp.part_to_category = result['part_to_category']
sp.categories = {r['id']: {"name": r['name']} for r in sp.rules}

for cat_id in result['stats']['per_category']:
    if cat_id.startswith('rb_'):
        rb_id = int(cat_id[3:])
        rb_cat = pd.categories.get(rb_id)
        sp.categories[cat_id] = {"name": rb_cat['name'] if rb_cat else cat_id}
    elif cat_id.startswith('bl_'):
        bl_id = int(cat_id[3:])
        bl_cat = pd.bricklink_categories.get(bl_id)
        sp.categories[cat_id] = {"name": bl_cat.get('category_name', cat_id) if bl_cat else cat_id}

saveSortingProfile(PROFILES_DIR, sp)
print(f"Generated {len(sp.part_to_category)} part mappings")
```

## Verifying your changes

After editing, test the profile to make sure rules match what you expect:

```python
from sorting_profile import loadSortingProfile
from rule_engine import generateProfile, previewRule
from db import PartsData, initDb, reloadPartsData

conn = initDb('parts.db')
pd = PartsData()
reloadPartsData(conn, pd)

sp = loadSortingProfile('profiles/cb3a66bc-36a8-493c-ada7-930efcc080f7.json')
result = generateProfile(sp, pd.parts, pd.categories, pd.bricklink_categories)

for r in sp.rules:
    entry = result['stats']['per_category'].get(r['id'])
    if entry or not r.get('disabled'):
        parts = entry['parts'] if entry else 0
        colors = entry['colors'] if entry else 0
        color_str = f" - {colors} colors" if colors > 0 else ""
        print(f"{r['name']}: {parts} parts{color_str}")
```

## Notes

- Every rule and condition needs a unique UUID `id` field. Use `str(uuid.uuid4())`.
- The `categories` dict in the profile must have an entry for each rule id mapping to `{"name": "..."}`.
- If the server is running, reload the page after editing the file. The server re-reads from disk.
- Rule order matters — first match wins. Put specific rules (like "Red 1x bricks") before general ones (like "Red/Orange bricks").
- Color-sensitive rules (with `color_id` conditions) are evaluated per-color. A part can match different color rules for different colors.
- Always run generation after all rule edits are complete, otherwise `part_to_category` is stale.
