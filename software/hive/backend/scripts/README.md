# Hive backend scripts

One-off and maintenance tools. Run them from `software/hive/backend` with
`uv run scripts/<name>.py`.

## generate_secondary_profile.py

Builds the "Seltenes und Besonderes" secondary sorting profile from a
Rebrickable CSV dump (`colors`, `part_categories`, `parts`, `inventories`,
`inventory_parts`; download from rebrickable.com/downloads and keep them
outside the repo).

    uv run scripts/generate_secondary_profile.py /path/to/rebrickable-csvs \
        --out /tmp/seltenes-und-besonderes.json

Writes the profile JSON in the `POST /api/profiles/{id}/versions` body shape
(every rule a filter rule with `role: "secondary"`, in bin-priority order:
printed, minifig heads/torsos/legs/accessories, animals and plants,
windows/doors/panels, transparent, metallic, wheels, Technic special, rare,
high-value) and a markdown summary next to it with per-rule CSV counts, pile
share, and what the rule engine cannot express. Rarity is baked as a
`part_num in [...]` list, so regenerate after a CSV refresh
(`--rare-max-sets`, default 20). `--price-min` sets the BrickLink used-average
threshold of the high-value rule, which only matches once the parts cache has
synced prices.

`tests/test_generate_secondary_profile.py` runs it against
`tests/fixtures/rebrickable_mini/` and pushes the result through the rule
engine.
