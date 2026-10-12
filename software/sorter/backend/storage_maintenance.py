"""Keeps everything the machine stores bounded by age and by space on the card.

One thread, hourly (the first pass a few minutes after start):

- Piece history: a piece (its record, predictions, rejection reasons, images
  and their files, link-model guesses) older than PIECE_HISTORY_DAYS goes once
  every enabled Hive target has all of it, or by age alone when no target is
  configured. A target that does not take a kind of data (its telemetry field
  is off) does not hold it back; a target whose state is unknown does. What the
  totals count from a record is folded into rollups first (piece_records.
  foldIntoRollup, sorting_runs.foldPieces), so overview numbers, charts, value,
  runs and lots stay the same.
- Rows that never had a record: predictions and images of pieces that were
  never recorded (torn down mid-classification), by age, once sent.
- piece_cycles and held_pieces after their own 60 days.
- Tombstones: crop, sample and control-data rows whose file retention already
  removed, by age, once every target has them.
- Bin events of pieces no longer in a bin, by age; the base64 pictures older
  versions kept in the bin tables, once.
- Space: SQLite never gives free pages back unless told. The database is
  switched to auto_vacuum=INCREMENTAL once, with a full VACUUM, while the
  machine has been idle a while and the card has room for it; after that each
  pass returns the free pages with incremental_vacuum.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import bin_contents
import db
import held_piece_records
import piece_cycles
import piece_image_store
import piece_predictions
import piece_records
import sorting_runs
from server import hive_sync

log = logging.getLogger(__name__)

PIECE_HISTORY_DAYS = 180.0
INTERVAL_S = 3600.0
FIRST_PASS_DELAY_S = 300.0
# How often the thread looks at whether the machine is sorting.
IDLE_CHECK_S = 60.0
BATCH = 500
# Between batches, so the writer thread and the sync worker get the database.
BATCH_PAUSE_S = 0.2
# The one full VACUUM waits for the machine to have been idle this long ...
VACUUM_IDLE_S = 600.0
# ... and for this much free space beyond twice the database's size (the copy
# VACUUM builds, then the WAL it writes it back through).
VACUUM_FREE_MARGIN_BYTES = 1024 * 1024 * 1024
# Free pages handed back per incremental_vacuum step.
INCREMENTAL_VACUUM_PAGES = 2048

AUTO_VACUUM_INCREMENTAL = 2


def _schema(conn: sqlite3.Connection) -> None:
    sorting_runs._createTables(conn)  # piece_records' and piece_images' too
    piece_predictions._createTables(conn)


def _connection():
    return db.connect(_schema)


def _limit(confirmed: Optional[dict[str, Optional[int]]], data_type: str) -> Optional[int]:
    """Up to which cursor value a data type may go: every target has it. None
    while some target's state is unknown."""
    if confirmed is None:
        return hive_sync.NOT_WANTED
    return confirmed.get(data_type)


def _placeholders(values: list[Any]) -> str:
    return ", ".join("?" for _ in values)


def prunePieceHistory(cutoff: float, confirmed: Optional[dict[str, Optional[int]]]) -> int:
    """Remove pieces seen before `cutoff` that every target has (see the module
    note). Returns how many pieces went."""
    records_wm = _limit(confirmed, hive_sync.DATA_TYPE_RECORDS)
    images_wm = _limit(confirmed, hive_sync.DATA_TYPE_IMAGES)
    predictions_wm = _limit(confirmed, hive_sync.DATA_TYPE_PREDICTIONS)
    if records_wm is None or images_wm is None or predictions_wm is None:
        return 0
    removed = 0
    while True:
        with _connection() as conn:
            rows = conn.execute(
                "SELECT r.id, r.uuid FROM piece_records r WHERE r.seen_at < ? AND r.sync_seq <= ? "
                "AND NOT EXISTS (SELECT 1 FROM piece_images i WHERE i.piece_uuid = r.uuid AND i.sync_seq > ?) "
                "AND NOT EXISTS (SELECT 1 FROM piece_predictions p WHERE p.piece_uuid = r.uuid AND p.id > ?) "
                "ORDER BY r.seen_at LIMIT ?",
                (cutoff, records_wm, images_wm, predictions_wm, BATCH),
            ).fetchall()
            if not rows:
                return removed
            uuids = [str(r["uuid"]) for r in rows]
            image_files = conn.execute(
                f"SELECT file_path FROM piece_images WHERE piece_uuid IN ({_placeholders(uuids)}) "
                "AND deleted_at IS NULL",
                uuids,
            ).fetchall()
            link_files = conn.execute(
                f"SELECT file_path FROM piece_link_images WHERE piece_uuid IN ({_placeholders(uuids)}) "
                "AND deleted_at IS NULL",
                uuids,
            ).fetchall()
        # Files first, with no transaction open (a crash after this leaves rows
        # whose files are gone, which the next pass removes).
        piece_image_store._unlinkEvictedFiles([str(r[0]) for r in image_files], piece_image_store.piece_images_dir())
        piece_image_store._unlinkEvictedFiles([str(r[0]) for r in link_files], piece_image_store.piece_link_images_dir())
        with _connection() as conn:
            # A record written again since the read (a late verdict) waits for
            # its next sync; its images are marked as having no file.
            ids = [
                int(r[0])
                for r in conn.execute(
                    f"SELECT id FROM piece_records WHERE id IN ({_placeholders([r['id'] for r in rows])}) "
                    "AND sync_seq <= ?",
                    [int(r["id"]) for r in rows] + [records_wm],
                ).fetchall()
            ]
            kept = {str(r["uuid"]) for r in rows if int(r["id"]) not in set(ids)}
            gone = [u for u in uuids if u not in kept]
            if kept:
                conn.execute(
                    f"UPDATE piece_images SET deleted_at = ? WHERE piece_uuid IN ({_placeholders(list(kept))}) "
                    "AND deleted_at IS NULL",
                    [time.time(), *kept],
                )
            if ids:
                sorting_runs.foldPieces(conn, ids)
                piece_records.foldIntoRollup(conn, ids)
                for table in ("piece_rejection_reasons", "piece_predictions", "piece_images", "piece_link_images"):
                    conn.execute(f"DELETE FROM {table} WHERE piece_uuid IN ({_placeholders(gone)})", gone)
                conn.execute(f"DELETE FROM piece_records WHERE id IN ({_placeholders(ids)})", ids)
            conn.commit()
        removed += len(ids)
        if len(rows) < BATCH:
            return removed
        time.sleep(BATCH_PAUSE_S)


def _sweepOldRows(
    table: str,
    *,
    cutoff: float,
    columns: str,
    goes: Callable[[sqlite3.Connection, list[sqlite3.Row]], list[sqlite3.Row]],
    files_dir: Optional[Path] = None,
) -> int:
    """Walk `table` from its oldest row in id order (ids follow created_at),
    delete the rows before `cutoff` that `goes` picks (unlinking the files of
    those that still have one, when `files_dir` is given), and stop at the
    first batch that reaches rows after `cutoff`. `columns` are read for
    `goes` besides id and created_at."""
    deleted = 0
    after = 0
    while True:
        with _connection() as conn:
            rows = conn.execute(
                f"SELECT id, created_at AS at, {columns} FROM {table} WHERE id > ? ORDER BY id LIMIT ?",
                (after, BATCH),
            ).fetchall()
            if not rows:
                return deleted
            after = int(rows[-1]["id"])
            old = [r for r in rows if r["at"] is not None and float(r["at"]) < cutoff]
            victims = goes(conn, old) if old else []
        if victims and files_dir is not None:
            piece_image_store._unlinkEvictedFiles(
                [str(r["file_path"]) for r in victims if r["deleted_at"] is None and r["file_path"]],
                files_dir,
            )
        if victims:
            ids = [int(r["id"]) for r in victims]
            with _connection() as conn:
                deleted += conn.execute(f"DELETE FROM {table} WHERE id IN ({_placeholders(ids)})", ids).rowcount
                conn.commit()
        if len(old) < len(rows):
            return deleted
        time.sleep(BATCH_PAUSE_S)


def _withoutRecord(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    if not rows:
        return []
    uuids = list({str(r["piece_uuid"]) for r in rows})
    recorded = {
        str(r[0])
        for r in conn.execute(
            f"SELECT uuid FROM piece_records WHERE uuid IN ({_placeholders(uuids)})", uuids
        ).fetchall()
    }
    return [r for r in rows if str(r["piece_uuid"]) not in recorded]


def pruneUnrecorded(cutoff: float, confirmed: Optional[dict[str, Optional[int]]]) -> int:
    """Remove what pieces that never got a record left behind, by age: their
    predictions once sent, their images (which never sync), and every old
    link-model guess (never sent; a recorded piece's go with it)."""
    deleted = 0
    predictions_wm = _limit(confirmed, hive_sync.DATA_TYPE_PREDICTIONS)
    if predictions_wm is not None:
        deleted += _sweepOldRows(
            "piece_predictions",
            cutoff=cutoff,
            columns="piece_uuid",
            goes=lambda conn, old: _withoutRecord(conn, [r for r in old if int(r["id"]) <= predictions_wm]),
        )
    # Images wait for their record; those still waiting this old never get one.
    with _connection() as conn:
        orphans = conn.execute(
            "SELECT id, file_path, deleted_at FROM piece_images WHERE sync_seq IS NULL AND created_at < ?",
            (cutoff,),
        ).fetchall()
    if orphans:
        piece_image_store._unlinkEvictedFiles(
            [str(r["file_path"]) for r in orphans if r["deleted_at"] is None],
            piece_image_store.piece_images_dir(),
        )
        ids = [int(r["id"]) for r in orphans]
        with _connection() as conn:
            for start in range(0, len(ids), BATCH):
                chunk = ids[start:start + BATCH]
                deleted += conn.execute(
                    f"DELETE FROM piece_images WHERE id IN ({_placeholders(chunk)}) AND sync_seq IS NULL", chunk
                ).rowcount
            conn.commit()
    deleted += _sweepOldRows(
        "piece_link_images",
        cutoff=cutoff,
        columns="file_path, deleted_at",
        goes=lambda conn, old: old,
        files_dir=piece_image_store.piece_link_images_dir(),
    )
    return deleted


def pruneTombstones(cutoff: float, confirmed: Optional[dict[str, Optional[int]]]) -> int:
    """Remove crop, sample and control-data rows whose file is already gone,
    once older than `cutoff` and on every target."""
    deleted = 0
    for table, data_type in (
        ("channel_crops", hive_sync.DATA_TYPE_CROPS),
        ("sample_frames", hive_sync.DATA_TYPE_SAMPLES),
        ("control_data_segments", hive_sync.DATA_TYPE_CONTROL_DATA),
    ):
        wm = _limit(confirmed, data_type)
        if wm is None:
            continue
        with _connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()
        if exists is None:
            continue
        deleted += _sweepOldRows(
            table,
            cutoff=cutoff,
            columns="deleted_at",
            goes=lambda conn, old, wm=wm: [r for r in old if r["deleted_at"] is not None and int(r["id"]) <= wm],
        )
    return deleted


def _dbBytes(path: Path) -> int:
    total = 0
    for suffix in ("", "-wal"):
        try:
            total += (path.parent / (path.name + suffix)).stat().st_size
        except OSError:
            pass
    return total


def _sqlQuote(text: str) -> str:
    return text.replace("'", "''")


def autoVacuumMode() -> int:
    with db.connect() as conn:
        return int(conn.execute("PRAGMA auto_vacuum").fetchone()[0])


def switchToIncrementalVacuum() -> bool:
    """The one full VACUUM that turns on auto_vacuum=INCREMENTAL (and gives back
    every free page). Only when the card has room for it; the caller makes sure
    the machine is idle. Returns True when the database is incremental."""
    path = db.local_state_db_path()
    if autoVacuumMode() == AUTO_VACUUM_INCREMENTAL:
        return True
    size = _dbBytes(path)
    free = shutil.disk_usage(path.parent).free
    if free < 2 * size + VACUUM_FREE_MARGIN_BYTES:
        log.info(
            "storage: not vacuuming the %.0f MB database yet: %.0f MB free on the card",
            size / 1e6, free / 1e6,
        )
        return False
    started = time.monotonic()
    with db.connect() as conn:
        # VACUUM builds its copy in SQLite's temp directory, which can be a RAM
        # disk; keep it on the card next to the database.
        conn.execute("PRAGMA temp_store = FILE")
        conn.execute(f"PRAGMA temp_store_directory = '{_sqlQuote(str(path.parent))}'")
        conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        mode = int(conn.execute("PRAGMA auto_vacuum").fetchone()[0])
    db.note(
        f"[db] vacuumed {size / 1e6:.0f} MB to {_dbBytes(path) / 1e6:.0f} MB in "
        f"{time.monotonic() - started:.0f}s; auto_vacuum={mode}"
    )
    return mode == AUTO_VACUUM_INCREMENTAL


def incrementalVacuum() -> int:
    """Hand the database's free pages back to the card, a step at a time.
    Returns the pages freed (0 unless the database is incremental)."""
    freed = 0
    with db.connect() as conn:
        if int(conn.execute("PRAGMA auto_vacuum").fetchone()[0]) != AUTO_VACUUM_INCREMENTAL:
            return 0
        while True:
            free_pages = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
            if free_pages <= 0:
                break
            step = min(free_pages, INCREMENTAL_VACUUM_PAGES)
            conn.execute(f"PRAGMA incremental_vacuum({step})").fetchall()
            freed += step
            time.sleep(BATCH_PAUSE_S)
    return freed


class StorageMaintenance:
    def __init__(self, gc: Any, sync_worker: Any) -> None:
        self._gc = gc
        self._sync = sync_worker
        self._stop = threading.Event()
        self._last_busy = time.monotonic()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="storage-maintenance")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _idleFor(self) -> float:
        if hive_sync._machineBusy(self._gc):
            self._last_busy = time.monotonic()
        return time.monotonic() - self._last_busy

    def _wait(self, seconds: float) -> None:
        # Sleep in steps, noting whether the machine sorts meanwhile.
        until = time.monotonic() + seconds
        while not self._stop.is_set() and time.monotonic() < until:
            self._idleFor()
            self._stop.wait(min(IDLE_CHECK_S, max(0.0, until - time.monotonic())))

    def _loop(self) -> None:
        self._wait(FIRST_PASS_DELAY_S)
        while not self._stop.is_set():
            try:
                self.runOnce()
            except Exception as exc:
                log.warning("storage maintenance pass failed: %s", exc)
            self._wait(INTERVAL_S)

    def runOnce(self, now: Optional[float] = None) -> dict[str, int]:
        now = time.time() if now is None else now
        cutoff = now - PIECE_HISTORY_DAYS * 86400.0
        confirmed = self._sync.confirmedWatermarks() if self._sync is not None else None
        done = {
            "pieces": prunePieceHistory(cutoff, confirmed),
            "unrecorded": pruneUnrecorded(cutoff, confirmed),
            "tombstones": pruneTombstones(cutoff, confirmed),
            "bin_events": bin_contents.pruneOldEvents(cutoff),
            "piece_cycles": piece_cycles.prune(now),
            "held_pieces": held_piece_records.prune(now),
        }
        # The two that rewrite most of the database wait for an idle machine.
        if self._idleFor() >= VACUUM_IDLE_S:
            bin_contents.clearStoredImages()
            if autoVacuumMode() != AUTO_VACUUM_INCREMENTAL:
                switchToIncrementalVacuum()
        if autoVacuumMode() == AUTO_VACUUM_INCREMENTAL:
            done["pages_freed"] = incrementalVacuum()
        if any(done.values()):
            log.info("storage maintenance: %s", ", ".join(f"{k} {v}" for k, v in done.items() if v))
        return done
