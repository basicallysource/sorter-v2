CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    part_count INTEGER DEFAULT 0
);

CREATE TABLE bricklink_categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER DEFAULT 0
);

CREATE TABLE colors (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    rgb TEXT,
    is_trans INTEGER DEFAULT 0,
    extra TEXT DEFAULT '{}'
);

CREATE TABLE parts (
    part_num TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    part_cat_id INTEGER REFERENCES categories(id),
    year_from INTEGER,
    year_to INTEGER,
    part_img_url TEXT,
    part_url TEXT,
    external_ids TEXT DEFAULT '{}'
);

CREATE TABLE part_bricklink_ids (
    part_num TEXT NOT NULL REFERENCES parts(part_num),
    item_no TEXT NOT NULL,
    is_primary INTEGER DEFAULT 0,
    PRIMARY KEY (part_num, item_no)
);

CREATE TABLE bricklink_items (
    item_no TEXT PRIMARY KEY,
    part_num TEXT NOT NULL REFERENCES parts(part_num),
    name TEXT,
    type TEXT DEFAULT 'PART',
    category_id INTEGER REFERENCES bricklink_categories(id),
    weight REAL,
    year_released INTEGER,
    is_obsolete INTEGER DEFAULT 0,
    synced_at TEXT
);

CREATE INDEX idx_parts_name ON parts(name);
CREATE INDEX idx_parts_cat_id ON parts(part_cat_id);
CREATE INDEX idx_bl_items_part ON bricklink_items(part_num);
CREATE INDEX idx_bl_items_cat ON bricklink_items(category_id);
CREATE INDEX idx_pbl_item_no ON part_bricklink_ids(item_no);
