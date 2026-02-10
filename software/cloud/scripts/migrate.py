import os
import sqlite3
import glob

DB_PATH = os.environ["DB_PATH"]
MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")

if not os.path.isdir(MIGRATIONS_DIR):
    raise RuntimeError(f"migrations directory not found: {MIGRATIONS_DIR}")

for entry in os.listdir(MIGRATIONS_DIR):
    if not entry.endswith(".sql"):
        raise RuntimeError(f"non-.sql file found in migrations directory: {entry}")

conn = sqlite3.connect(DB_PATH)
conn.execute("""
    CREATE TABLE IF NOT EXISTS applied_migrations (
        name TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
""")
conn.commit()

applied = {row[0] for row in conn.execute("SELECT name FROM applied_migrations").fetchall()}

migration_files = sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql")))
for filepath in migration_files:
    name = os.path.basename(filepath)
    if name in applied:
        continue
    print(f"applying {name}")
    sql = open(filepath).read()
    conn.executescript(sql)
    conn.execute("INSERT INTO applied_migrations (name) VALUES (?)", (name,))
    conn.commit()

conn.close()
print("migrations complete")
