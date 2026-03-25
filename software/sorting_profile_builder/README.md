# Sorting Profile Builder
> Warning: You have entered extreme vibe coding territory

Web UI for building rule-based sorting profiles that map LEGO parts to categories.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

Create a `.env` file:

```
REBRICKABLE_API_KEY=your_key_here
```

Other optional env vars: `PARTS_DB_PATH` (default `./parts.db`), `PROFILES_DIR` (default `./profiles`), `PORT` (default `8001`), `BRICKSTORE_DB_PATH`.

## Run

```
make run
```

Opens at `http://localhost:8001`.

## Usage

1. **Sync data** — On the home page, sync categories, colors, and parts from Rebrickable. You can also import BrickLink categories from a local BrickStore database. This populates the local parts cache that rules match against.

2. **Create a profile** — Give it a name and open it.

3. **Add rules** — Each rule is a category (bin) that parts get sorted into. A rule has conditions like "name contains brick" or "category is Plates". Rules can have child rules for more specific overrides (children take priority over parents).

4. **Configure conditions** — Each rule can match on part name, Rebrickable category, BrickLink category, color, or part number. Conditions within a rule combine with ALL (every condition must match) or ANY (at least one must match).

5. **Preview** — Preview which parts match a rule before committing. You can also preview the full profile to see category distribution stats.

6. **Set fallback mode** — Parts that don't match any rule can fall back to their Rebrickable category, be grouped by color, or both.

7. **Generate** — Generates the final `part_to_category` mapping across all cached parts and saves it to the profile JSON. This is the file the sorter client loads at runtime via `SORTING_PROFILE_PATH`.
