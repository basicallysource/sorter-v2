CREATE TABLE IF NOT EXISTS part_search (
    part_num TEXT PRIMARY KEY,
    name_text TEXT NOT NULL,
    id_text TEXT NOT NULL,
    word_count INTEGER NOT NULL DEFAULT 0,
    is_variant INTEGER NOT NULL DEFAULT 0,
    is_off_system INTEGER NOT NULL DEFAULT 0,
    popularity INTEGER NOT NULL DEFAULT 0
)
