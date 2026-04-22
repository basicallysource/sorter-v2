CREATE TABLE IF NOT EXISTS rebrickable_sets (
    set_num TEXT PRIMARY KEY,
    name TEXT,
    year INTEGER,
    num_parts INTEGER,
    set_img_url TEXT,
    theme_id INTEGER,
    raw_json TEXT,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rebrickable_set_inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    set_num TEXT NOT NULL,
    part_num TEXT NOT NULL,
    color_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    is_spare INTEGER NOT NULL DEFAULT 0,
    element_id TEXT,
    part_name TEXT,
    part_img_url TEXT,
    color_name TEXT,
    color_rgb TEXT,
    UNIQUE(set_num, part_num, color_id, is_spare)
);
