CREATE TABLE IF NOT EXISTS part_geometry (
    part_num TEXT PRIMARY KEY,
    ldraw_id TEXT,
    physical_parent_part_num TEXT,
    geometry_source TEXT,
    bbox_x_mm REAL,
    bbox_y_mm REAL,
    bbox_z_mm REAL,
    max_extent_mm REAL,
    volume_mm3 REAL,
    computed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_part_geometry_parent ON part_geometry(physical_parent_part_num);
