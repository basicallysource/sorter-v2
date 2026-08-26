"""
Rebuild a corrupted SQLite database into a fresh, clean file, salvaging every
readable row. Built for the silent-corruption failure family documented in
issues #328/#331 (ext4 data=writeback + unclean power-off), but generic: it
reads the schema from sqlite_master and works on any SQLite database.

    uv run python scripts/salvage_sqlite.py <corrupt.sqlite> <rebuilt.sqlite>

Notes that came from using this in anger on a live machine:

- If the source has a -wal/-shm pair, copy db+wal+shm together under matching
  names first (or run against the original paths with the owning process
  stopped) — otherwise the WAL tail is silently ignored.
- Rows are copied by rowid ranges; a range that throws "database disk image is
  malformed" is bisected down to single rows so only rows physically on a
  damaged page are lost. The per-table loss is printed at the end.
- Text columns are decoded with errors="replace" rather than read as raw
  bytes. Corrupt strings survive with U+FFFD characters and stay TEXT.
  Reading as bytes and re-inserting stores every string as a BLOB, and BLOB
  never compares equal to TEXT in SQLite — the rebuilt DB passes
  integrity_check and has correct row counts, yet every keyed lookup in the
  application silently misses. Verify with typeof(), not just counts.
- Exit code is non-zero unless the rebuilt file passes PRAGMA integrity_check.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time

BATCH_ROWS = 400


def copySchemaObjects(
    src: sqlite3.Connection, dst: sqlite3.Connection
) -> tuple[list[str], list[tuple[str, str]]]:
    schema = src.execute(
        "select type, name, sql from sqlite_master where sql is not null"
    ).fetchall()
    tables: list[str] = []
    deferred: list[tuple[str, str]] = []
    for obj_type, name, sql in schema:
        if name.startswith("sqlite_"):
            continue
        if obj_type == "table":
            if "WITHOUT ROWID" in sql.upper():
                raise SystemExit(
                    f"table {name!r} is WITHOUT ROWID; rowid-ranged salvage "
                    f"does not support it — extend the script before use"
                )
            dst.execute(sql)
            tables.append(name)
        else:
            deferred.append((f"{obj_type} {name}", sql))
    return tables, deferred


def copyTableRows(
    src: sqlite3.Connection, dst: sqlite3.Connection, table: str
) -> tuple[int, int]:
    cols = [c[0] for c in src.execute(f'select * from "{table}" limit 0').description]
    insert_sql = (
        f'insert or ignore into "{table}"(rowid,{",".join(cols)}) '
        f'values ({",".join("?" * (len(cols) + 1))})'
    )
    lo, hi, count = src.execute(
        f'select min(rowid), max(rowid), count(*) from "{table}"'
    ).fetchone()
    if lo is None:
        return 0, 0
    copied = 0
    start = lo
    while start <= hi:
        end = start + BATCH_ROWS - 1
        try:
            rows = src.execute(
                f'select rowid, * from "{table}" where rowid between ? and ?',
                (start, end),
            ).fetchall()
            dst.executemany(insert_sql, rows)
            copied += len(rows)
        except sqlite3.DatabaseError:
            for rowid in range(start, end + 1):
                try:
                    rows = src.execute(
                        f'select rowid, * from "{table}" where rowid = ?', (rowid,)
                    ).fetchall()
                    dst.executemany(insert_sql, rows)
                    copied += len(rows)
                except sqlite3.DatabaseError:
                    pass
        start = end + 1
    return count or 0, copied


def restoreSequences(src: sqlite3.Connection, dst: sqlite3.Connection) -> None:
    try:
        for name, seq in src.execute("select name, seq from sqlite_sequence"):
            dst.execute(
                "insert or replace into sqlite_sequence(name, seq) values (?, ?)",
                (name, seq),
            )
    except sqlite3.DatabaseError:
        pass


def salvage(src_path: str, dst_path: str) -> int:
    started = time.time()
    if os.path.exists(dst_path):
        raise SystemExit(f"refusing to overwrite existing {dst_path}")
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True, timeout=30)
    src.text_factory = lambda raw: raw.decode("utf-8", "replace")
    dst = sqlite3.connect(dst_path)
    dst.execute("PRAGMA journal_mode=OFF")
    dst.execute("PRAGMA synchronous=OFF")

    tables, deferred = copySchemaObjects(src, dst)

    total_lost = 0
    print(f"{'table':40s} {'src_count':>10s} {'copied':>10s} {'lost':>6s}")
    for table in tables:
        count, copied = copyTableRows(src, dst, table)
        lost = max(0, count - copied)
        total_lost += lost
        print(
            f"{table:40s} {count:>10,} {copied:>10,} {lost:>6,}"
            f"{'  <-- LOSS' if lost else ''}"
        )

    for label, sql in deferred:
        try:
            dst.execute(sql)
        except sqlite3.DatabaseError as exc:
            print(f"skipped {label}: {exc}")

    restoreSequences(src, dst)
    try:
        user_version = src.execute("PRAGMA user_version").fetchone()[0]
        dst.execute(f"PRAGMA user_version = {int(user_version)}")
    except sqlite3.DatabaseError:
        pass

    dst.commit()
    dst.execute("PRAGMA journal_mode=WAL")
    check = dst.execute("PRAGMA integrity_check").fetchall()
    src.close()
    dst.close()

    print(f"\nintegrity_check: {check}")
    print(f"total rows lost: {total_lost}")
    print(f"elapsed: {time.time() - started:.1f}s")
    return 0 if check == [("ok",)] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src", help="corrupted database (opened read-only)")
    parser.add_argument("dst", help="output path for the rebuilt database")
    args = parser.parse_args()
    return salvage(args.src, args.dst)


if __name__ == "__main__":
    sys.exit(main())
