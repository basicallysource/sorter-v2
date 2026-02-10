CREATE TABLE IF NOT EXISTS captures (
    id TEXT PRIMARY KEY,
    machine_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    camera_name TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    raw_img_name TEXT NOT NULL,
    annotated_img_name TEXT,
    segmentation_data_filename TEXT
);
