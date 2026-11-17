"""The stats worker's kept answers equal the full scans they replaced.

Every piece number the cache serves used to be a grouped scan of all of
machine_pieces, and every crop count a count of all of machine_channel_crops.
The worker now keeps partial answers per machine-day that triggers mark stale
(services/piece_days.py) and crop deltas the triggers count. These tests change
pieces and crops every way the app does (new, re-sent with other values, moved
to another day, without a time, deleted, a machine deleted) and check after
each pass that the cache, the daily table and the per-part totals are what the
old full scans give.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, update

from app.models.machine import Machine
from app.models.machine_channel_crop import (
    PG_CROP_DELTA_FUNCTION,
    PG_CROP_DELTA_TRIGGERS,
    MachineChannelCrop,
    MachineChannelCropDelta,
)
from app.models.machine_daily_stats import MachineDailyStats
from app.models.machine_piece import MachinePiece
from app.models.machine_piece_day import (
    KIND_COLOR,
    KIND_COMBO,
    KIND_PART,
    PG_PIECE_MARK_FUNCTION,
    PG_PIECE_MARK_TRIGGERS,
    MachinePieceDay,
    MachinePieceDayKey,
    MachinePieceDayMark,
    MachinePieceKey,
)
from app.models.machine_stats_cache import MachineStatsCache
from app.models.user import User
from app.services import fleet_mass, fleet_records, machine_stats

IDLE = 60.0
T0 = datetime(2026, 11, 14, 23, 58, 0, tzinfo=timezone.utc)


# --- The full scans the worker used to run, kept here as the reference ------------------


def reference(db, machine_id) -> dict:
    """One machine's piece numbers as the old pass computed them."""
    pieces = db.execute(
        select(
            MachinePiece.seen_at,
            MachinePiece.local_id,
            MachinePiece.bin_x,
            MachinePiece.classification_status,
            MachinePiece.part_id,
            MachinePiece.part_name,
            MachinePiece.color_id,
            MachinePiece.color_name,
        ).where(MachinePiece.machine_id == machine_id)
    ).all()
    timed = sorted((p for p in pieces if p.seen_at is not None), key=lambda p: (p.seen_at, p.local_id))
    active = 0.0
    daily: dict = {}
    prev = None
    for p in timed:
        cell = daily.setdefault(p.seen_at.date(), [0, 0, 0.0])
        cell[0] += 1
        cell[1] += p.bin_x is not None
        if prev is not None:
            gap = (p.seen_at - prev).total_seconds()
            if 0 < gap <= IDLE:
                active += gap
                cell[2] += gap
        prev = p.seen_at
    status: dict = {}
    parts: dict = {}
    colors: dict = {}
    for p in pieces:
        key = p.classification_status or "unknown"
        status[key] = status.get(key, 0) + 1
        for target, value, name in ((parts, p.part_id, p.part_name), (colors, p.color_id, p.color_name)):
            if value is None:
                continue
            n, best = target.get(value, [0, None])
            target[value] = [n + 1, name if best is None or (name is not None and name > best) else best]
    first = min((p.seen_at for p in timed), default=None)
    last = max((p.seen_at for p in timed), default=None)
    return {
        "pieces_seen": len(pieces),
        "distributed": sum(p.bin_x is not None for p in pieces),
        "classified": sum(p.classification_status == "classified" for p in pieces),
        "unique_parts": len(parts),
        "unique_colors": len(colors),
        "first_seen": first,
        "last_seen": last,
        "active_seconds": active,
        "distributions": {"status": status, "parts": parts, "colors": colors},
        "daily": {d: (c[0], c[1], c[2]) for d, c in daily.items()},
    }


def reference_firsts(db, machine_id, kind) -> dict:
    """A machine's earliest classified sighting per part, colour or combo."""
    out: dict = {}
    for p in db.execute(select(MachinePiece).where(MachinePiece.machine_id == machine_id)).scalars():
        if p.classification_status != "classified" or p.seen_at is None:
            continue
        if kind == KIND_PART:
            key = p.part_id
        elif kind == KIND_COLOR:
            key = p.color_id
        else:
            real = (p.part_id, p.color_id)
            if None in real or set(real) & {"", "any_color"}:
                continue
            key = f"{p.part_id}\t{p.color_id}"
        if key is None:
            continue
        out[key] = min(out.get(key, p.seen_at), p.seen_at)
    return out


def _naive(dt):
    return dt.replace(tzinfo=None) if dt is not None and dt.tzinfo is not None else dt


def check(db, machine_id) -> None:
    db.expire_all()
    want = reference(db, machine_id)
    row = db.get(MachineStatsCache, machine_id)
    assert row is not None
    for name in ("pieces_seen", "distributed", "classified", "unique_parts", "unique_colors"):
        assert getattr(row, name) == want[name], name
    assert _naive(row.first_seen) == _naive(want["first_seen"])
    assert _naive(row.last_seen) == _naive(want["last_seen"])
    assert row.active_seconds == pytest.approx(want["active_seconds"])
    dist = row.distributions
    assert dist["status"] == want["distributions"]["status"]
    assert dist["parts"] == want["distributions"]["parts"]
    assert dist["colors"] == want["distributions"]["colors"]
    daily = {
        r.day: (r.pieces_seen, r.distributed, r.active_seconds)
        for r in db.execute(select(MachineDailyStats).where(MachineDailyStats.machine_id == machine_id)).scalars()
    }
    assert set(daily) == set(want["daily"])
    for day, (pieces, distributed, active) in want["daily"].items():
        assert daily[day][:2] == (pieces, distributed), day
        assert daily[day][2] == pytest.approx(active), day
    for kind in (KIND_PART, KIND_COLOR, KIND_COMBO):
        kept = {
            k: _naive(f)
            for k, f in db.execute(
                select(MachinePieceKey.key, MachinePieceKey.first_classified).where(
                    MachinePieceKey.machine_id == machine_id,
                    MachinePieceKey.kind == kind,
                    MachinePieceKey.first_classified.isnot(None),
                )
            )
        }
        assert kept == {k: _naive(v) for k, v in reference_firsts(db, machine_id, kind).items()}, kind


# --- Fixtures ------------------------------------------------------------------------------


@pytest.fixture()
def owner(db):
    user = User(email=f"{uuid.uuid4().hex}@example.com", display_name="Owner", role="member")
    db.add(user)
    db.commit()
    return user


def _machine(db, owner, name="m") -> Machine:
    m = Machine(owner_id=owner.id, token_hash=f"hash-{uuid.uuid4().hex}", token_prefix=name[:8], name=name)
    db.add(m)
    db.commit()
    return m


_local = iter(range(1, 1_000_000))


def _piece(machine, seen_at, *, part="3001", color="5", status="classified", bin_x=1, name=None, cname=None):
    lid = next(_local)
    return MachinePiece(
        machine_id=machine.id,
        piece_uuid=f"p{lid}",
        local_id=lid,
        seen_at=seen_at,
        classification_status=status,
        part_id=part,
        part_name=name if name is not None else (f"Part {part}" if part else None),
        color_id=color,
        color_name=cname if cname is not None else (f"Color {color}" if color else None),
        bin_x=bin_x,
        dead=False,
    )


def _refresh(db):
    machine_stats.refresh_all(db)


# --- The tests ----------------------------------------------------------------------------


def test_numbers_follow_every_kind_of_change(db, owner):
    a = _machine(db, owner, "a")
    b = _machine(db, owner, "b")
    t = T0
    pieces = [
        _piece(a, t, part="3001", color="5"),  # 23:58:00
        _piece(a, t + timedelta(seconds=30), part="3001", color="11"),
        _piece(a, t + timedelta(seconds=100), part="3002", color="5"),  # 70 s on: idle, not counted
        # 23:59:40 to 00:00:10: a gap across midnight, counted on the later day.
        _piece(a, t + timedelta(seconds=130), part="3003", color="any_color", status="multi_drop_fail", bin_x=None),
        _piece(a, t + timedelta(seconds=130), part="3003", color="11"),  # the same instant: a gap of 0
        _piece(a, t + timedelta(days=2), part="", color="", status="unknown", bin_x=None),
        _piece(a, None, part=None, color=None, status=None, bin_x=None),
        _piece(b, t + timedelta(hours=1), part="3001", color="5", name="Brick 2 x 4"),
        _piece(b, t + timedelta(hours=1, seconds=10), part="3001", color="5", name="Brick 2x4"),
    ]
    db.add_all(pieces)
    db.commit()
    _refresh(db)
    check(db, a.id)
    check(db, b.id)

    # Re-sent with other values: reclassified, put in a bin, renamed.
    db.execute(
        update(MachinePiece)
        .where(MachinePiece.piece_uuid == pieces[0].piece_uuid)
        .values(part_id="3010", part_name="Brick 1 x 4", bin_x=None, classification_status="low_confidence")
    )
    # Moved to another day.
    db.execute(
        update(MachinePiece)
        .where(MachinePiece.piece_uuid == pieces[5].piece_uuid)
        .values(seen_at=t + timedelta(seconds=200))
    )
    # Given a time it lacked.
    db.execute(
        update(MachinePiece)
        .where(MachinePiece.piece_uuid == pieces[6].piece_uuid)
        .values(seen_at=t + timedelta(days=3))
    )
    # A column the stats do not read: marks nothing.
    db.execute(update(MachinePiece).where(MachinePiece.piece_uuid == pieces[7].piece_uuid).values(confidence=0.5))
    db.commit()
    _refresh(db)
    check(db, a.id)
    check(db, b.id)

    # More pieces, some deleted (the last of a day, so the day goes).
    db.add_all([_piece(a, t + timedelta(days=1, seconds=s), part="3005", color="1") for s in (0, 20, 100)])
    db.execute(delete(MachinePiece).where(MachinePiece.piece_uuid == pieces[6].piece_uuid))
    db.commit()
    _refresh(db)
    check(db, a.id)
    check(db, b.id)
    assert db.execute(select(func.count()).select_from(MachinePieceDayMark)).scalar() == 0


def test_a_pass_reads_only_the_days_that_changed(db, owner):
    a = _machine(db, owner, "a")
    db.add_all([_piece(a, T0 + timedelta(days=d, seconds=s)) for d in range(5) for s in (0, 30)])
    db.commit()
    _refresh(db)
    built = {r.day: r.computed_at for r in db.execute(select(MachinePieceDay)).scalars()}
    assert len(built) == 5

    db.add(_piece(a, T0 + timedelta(days=4, seconds=45)))
    db.commit()
    marks = {d for (d,) in db.execute(select(MachinePieceDayMark.day))}
    assert marks == {(T0 + timedelta(days=4)).date()}
    _refresh(db)
    db.expire_all()
    after = {r.day: r.computed_at for r in db.execute(select(MachinePieceDay)).scalars()}
    changed = {d for d in after if after[d] != built[d]}
    assert changed == {(T0 + timedelta(days=4)).date()}
    check(db, a.id)


def test_a_machine_from_before_the_triggers_is_counted_in_full_once(db, owner):
    a = _machine(db, owner, "a")
    db.add_all([_piece(a, T0 + timedelta(hours=h, seconds=s), part=str(h)) for h in range(0, 60, 7) for s in (0, 40)])
    db.add_all([MachineChannelCrop(machine_id=a.id, local_id=i, channel=2) for i in range(1, 8)])
    db.commit()
    # As production finds it after the migration: pieces and crops, none of
    # them marked or counted, and a cache row from the old full scan.
    for table in (MachinePieceDayMark, MachineChannelCropDelta, MachinePieceDay, MachinePieceDayKey, MachinePieceKey):
        db.execute(delete(table))
    db.add(MachineStatsCache(machine_id=a.id, pieces_seen=1, channel_crops=3, distributions={}, control_data={}))
    db.commit()

    _refresh(db)
    check(db, a.id)
    row = db.get(MachineStatsCache, a.id)
    assert row.channel_crops == 7
    assert row.incremental_since is not None

    db.add_all([MachineChannelCrop(machine_id=a.id, local_id=i, channel=3) for i in range(8, 11)])
    db.commit()
    _refresh(db)
    db.expire_all()
    assert db.get(MachineStatsCache, a.id).channel_crops == 10


def test_crop_counts_follow_inserts_resends_and_deletes(db, owner):
    a = _machine(db, owner, "a")
    b = _machine(db, owner, "b")
    db.add_all([MachineChannelCrop(machine_id=a.id, local_id=i, channel=2) for i in range(1, 6)])
    db.add_all([MachineChannelCrop(machine_id=b.id, local_id=i, channel=2) for i in range(1, 3)])
    db.commit()
    _refresh(db)

    def counts():
        db.expire_all()
        return {m.id: db.get(MachineStatsCache, m.id).channel_crops for m in (a, b)}

    assert counts() == {a.id: 5, b.id: 2}

    # A re-sent crop updates its row and adds nothing.
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    stmt = insert(MachineChannelCrop).values(
        id=uuid.uuid4(), machine_id=a.id, local_id=3, channel=3, evicted_locally=False,
        created_at=datetime.now(timezone.utc),
    )
    db.execute(stmt.on_conflict_do_update(index_elements=["machine_id", "local_id"], set_={"channel": 3}))
    db.add(MachineChannelCrop(machine_id=a.id, local_id=6, channel=2))
    db.execute(delete(MachineChannelCrop).where(MachineChannelCrop.machine_id == b.id, MachineChannelCrop.local_id == 1))
    db.commit()
    _refresh(db)
    assert counts() == {a.id: 6, b.id: 1}
    assert db.execute(select(func.count()).select_from(MachineChannelCropDelta)).scalar() == 0


def test_a_deleted_machine_leaves_nothing_behind(db, owner):
    a = _machine(db, owner, "a")
    keep = _machine(db, owner, "keep")
    db.add_all([_piece(a, T0), _piece(a, T0 + timedelta(seconds=5)), _piece(keep, T0)])
    db.add(MachineChannelCrop(machine_id=a.id, local_id=1, channel=2))
    db.commit()
    _refresh(db)

    # sqlite does not cascade unless asked; delete what Postgres would.
    db.execute(delete(MachineChannelCrop).where(MachineChannelCrop.machine_id == a.id))
    db.execute(delete(MachinePiece).where(MachinePiece.machine_id == a.id))
    for table in (MachinePieceDay, MachinePieceDayKey, MachinePieceKey, MachineDailyStats, MachineStatsCache):
        db.execute(delete(table).where(table.machine_id == a.id))
    db.execute(delete(Machine).where(Machine.id == a.id))
    db.commit()
    _refresh(db)
    assert db.execute(select(func.count()).select_from(MachinePieceDayMark)).scalar() == 0
    assert db.execute(select(func.count()).select_from(MachineChannelCropDelta)).scalar() == 0
    check(db, keep.id)


def test_fleet_mass_and_records_read_the_kept_numbers(db, owner, monkeypatch):
    monkeypatch.setattr(fleet_records, "FLEET_MILESTONES", (2, 3))
    monkeypatch.setattr(fleet_records, "FLEET_MILESTONE_STEP", 10)
    fleet_records.reset_cache()
    a = _machine(db, owner, "a")
    b = _machine(db, owner, "b")
    db.add_all([
        _piece(a, T0, part="3001", color="5"),
        _piece(a, T0 + timedelta(seconds=10), part="3002", color="11"),
        _piece(b, T0 + timedelta(seconds=20), part="3001", color="11"),
        _piece(b, T0 + timedelta(seconds=30), part="3009", color="any_color"),
        _piece(b, T0 + timedelta(seconds=40), part="3010", color="7", status="unknown"),
        _piece(b, None, part="3001", color="5", status="unknown"),
    ])
    db.commit()
    _refresh(db)
    ids = [a.id, b.id]
    computed = fleet_records._compute(db, ids, datetime.now(timezone.utc))
    assert computed["fleet_pieces"] == 5
    assert computed["distinct_parts"] == 3  # 3001, 3002, 3009 classified; 3010 is not
    assert computed["distinct_colors"] == 2  # 5, 11; any_color is not a colour
    assert computed["distinct_combos"] == 3
    assert [p["part_id"] for p in computed["newest_parts"]] == ["3009", "3002", "3001"]
    assert [c["color_id"] for c in computed["newest_colors"]] == ["11", "5"]
    assert [(c["part_id"], c["color_id"]) for c in computed["newest_combos"]] == [
        ("3001", "11"), ("3002", "11"), ("3001", "5"),
    ]
    assert computed["newest_combos"][0]["machine_id"] == str(b.id)
    mass = fleet_mass._compute(db, ids)
    assert mass["total_pieces"] == 6
    fleet_records.reset_cache()


def test_the_migration_creates_the_same_triggers():
    """The Postgres triggers are written twice, in the models (for create_all)
    and in a migration (for production): a change to one needs the other."""
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    texts = []
    for path in sorted(versions.glob("*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if "TRIGGERS" not in path.read_text():
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        texts.append(module)
    migration = texts[-1]
    assert migration.PIECE_MARK_FUNCTION == PG_PIECE_MARK_FUNCTION
    assert tuple(migration.PIECE_MARK_TRIGGERS) == PG_PIECE_MARK_TRIGGERS
    assert migration.CROP_DELTA_FUNCTION == PG_CROP_DELTA_FUNCTION
    assert tuple(migration.CROP_DELTA_TRIGGERS) == PG_CROP_DELTA_TRIGGERS


def test_a_low_disk_is_told_once_a_day(monkeypatch):
    import shutil

    from app.config import settings
    from app.services import admin_alert

    sent = []
    monkeypatch.setattr(admin_alert, "send_in_background", lambda **kw: sent.append(kw))
    monkeypatch.setattr(settings, "DISK_ALERT_FREE_PCT", 12.0)
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(100, 85, 15))
    assert machine_stats.warn_if_disk_low() == 15.0
    assert sent == []
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(100, 92, 8))
    machine_stats.warn_if_disk_low()
    machine_stats.warn_if_disk_low()
    assert len(sent) == 2 and sent[0]["request_id"] == sent[1]["request_id"]
    assert sent[0]["request_id"].startswith("hive-disk-low-")
