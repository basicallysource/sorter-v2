-- Rebrickable's themes, sets and set inventories, imported whole from its CSV
-- downloads by the "sets" catalog sync (app/services/set_inventory.py). They
-- replace the per-set cache that was filled from Rebrickable's API one set at
-- a time. Columns are the CSV files' own.
DROP TABLE IF EXISTS rebrickable_set_inventory;
DROP TABLE IF EXISTS rebrickable_sets;

CREATE TABLE rebrickable_themes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER
);

CREATE TABLE rebrickable_sets (
    set_num TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    year INTEGER,
    theme_id INTEGER,
    num_parts INTEGER,
    img_url TEXT
);

CREATE INDEX idx_rebrickable_sets_theme ON rebrickable_sets(theme_id);

-- A set can have several inventory versions, the first being the set as
-- released. Minifigures have inventories too (set_num "fig-…").
-- (No semicolons in comments: the migration runner splits on them.)
CREATE TABLE rebrickable_inventories (
    id INTEGER PRIMARY KEY,
    version INTEGER NOT NULL,
    set_num TEXT NOT NULL
);

CREATE INDEX idx_rebrickable_inventories_set ON rebrickable_inventories(set_num, version);

CREATE TABLE rebrickable_inventory_parts (
    inventory_id INTEGER NOT NULL,
    part_num TEXT NOT NULL,
    color_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    is_spare INTEGER NOT NULL,
    img_url TEXT
);

CREATE INDEX idx_rebrickable_inventory_parts_inventory ON rebrickable_inventory_parts(inventory_id);
