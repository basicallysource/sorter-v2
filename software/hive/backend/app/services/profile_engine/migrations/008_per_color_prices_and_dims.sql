ALTER TABLE bricklink_items ADD COLUMN dim_x_studs REAL;

ALTER TABLE bricklink_items ADD COLUMN dim_y_studs REAL;

CREATE TABLE IF NOT EXISTS bricklink_item_colors (
    item_no TEXT NOT NULL,
    bl_color_id INTEGER NOT NULL,
    PRIMARY KEY (item_no, bl_color_id)
);

ALTER TABLE price_guides RENAME TO price_guides_legacy_v7;

CREATE TABLE price_guides (
    item_no TEXT NOT NULL,
    bl_color_id INTEGER NOT NULL,
    rb_color_id INTEGER,
    updated_at TEXT,
    inv_new_lots INTEGER DEFAULT 0,
    inv_new_qty INTEGER DEFAULT 0,
    inv_new_min REAL,
    inv_new_max REAL,
    inv_new_avg REAL,
    inv_new_wavg REAL,
    inv_used_lots INTEGER DEFAULT 0,
    inv_used_qty INTEGER DEFAULT 0,
    inv_used_min REAL,
    inv_used_max REAL,
    inv_used_avg REAL,
    inv_used_wavg REAL,
    ord_new_lots INTEGER DEFAULT 0,
    ord_new_qty INTEGER DEFAULT 0,
    ord_new_min REAL,
    ord_new_max REAL,
    ord_new_avg REAL,
    ord_new_wavg REAL,
    ord_used_lots INTEGER DEFAULT 0,
    ord_used_qty INTEGER DEFAULT 0,
    ord_used_min REAL,
    ord_used_max REAL,
    ord_used_avg REAL,
    ord_used_wavg REAL,
    PRIMARY KEY (item_no, bl_color_id)
);

CREATE INDEX idx_price_guides_rbcolor ON price_guides(rb_color_id);
