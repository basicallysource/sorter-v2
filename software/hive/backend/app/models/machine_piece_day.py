"""What the stats worker keeps of machine_pieces, one machine-day at a time.

Every piece number the stats surfaces serve (a machine's piece count, its
distinct parts and colours, its active time, the fleet's mass and records) is
a sum or a union over pieces. Rescanning every piece to answer them each pass
stopped scaling at two million pieces: the grouped scans ran past the worker's
statement limit and the cache froze. So the worker keeps partial answers per
machine and UTC day of ``seen_at``, and recomputes only the days that changed
(``services/piece_days.py``):

- ``machine_piece_days``: one row per machine-day, its counts, first and last
  piece and active time within the day.
- ``machine_piece_day_keys``: per machine-day, each status, part, colour and
  classified part-in-a-colour seen, with its count, name and first classified
  sighting.
- ``machine_piece_keys``: the same per machine, summed over its days.
- ``machine_piece_day_marks``: the machine-days whose pieces changed since the
  worker last looked. Database triggers on machine_pieces append them, so every
  write path (a sync, a correction, a cascade from a deleted machine) is
  caught without the code that writes having to know.

Pieces with no ``seen_at`` are kept under ``NULL_DAY``, a day no piece has.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    DDL,
    BigInteger,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    event,
)
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base

# The day pieces without a seen_at are kept under. No real piece has it.
NULL_DAY = date(1, 1, 1)

# Exact seconds on Postgres (the sum of exact gaps, as the old full scan gave);
# sqlite, the tests, has no exact decimal.
_SECONDS = Float().with_variant(Numeric(asdecimal=True), "postgresql")
# An autoincrementing key on both: sqlite only increments an INTEGER key.
_SERIAL = BigInteger().with_variant(Integer(), "sqlite")


class MachinePieceDay(Base):
    __tablename__ = "machine_piece_days"

    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True)
    day = Column(Date, primary_key=True)
    pieces = Column(BigInteger, nullable=False, default=0)
    distributed = Column(BigInteger, nullable=False, default=0)
    classified = Column(BigInteger, nullable=False, default=0)
    first_seen = Column(DateTime(timezone=True), nullable=True)
    last_seen = Column(DateTime(timezone=True), nullable=True)
    # Gaps of up to ACTIVE_GAP_IDLE_S between consecutive pieces of this day.
    # The gap from the previous day's last piece to this day's first is added
    # when the days are folded, from first_seen and last_seen.
    active_within = Column(_SECONDS, nullable=False, default=0)
    computed_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


# What a key row counts. A status is NULL-safe ("unknown"); a combo is a
# classified part in a colour, "<part_id>\t<color_id>", kept for the fleet's
# newest finds only.
KIND_STATUS = "s"
KIND_PART = "p"
KIND_COLOR = "c"
KIND_COMBO = "pc"


class MachinePieceDayKey(Base):
    __tablename__ = "machine_piece_day_keys"

    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True)
    kind = Column(String(2), primary_key=True)
    key = Column(String, primary_key=True)
    day = Column(Date, primary_key=True)
    n = Column(BigInteger, nullable=False)
    # max(part_name) / max(color_name) of the pieces, as the full scan read it.
    name = Column(String, nullable=True)
    # The earliest seen_at of a classified piece with this key.
    first_classified = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_machine_piece_day_keys_machine_day", "machine_id", "day"),)


class MachinePieceKey(Base):
    __tablename__ = "machine_piece_keys"

    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True)
    kind = Column(String(2), primary_key=True)
    key = Column(String, primary_key=True)
    n = Column(BigInteger, nullable=False)
    name = Column(String, nullable=True)
    first_classified = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # The fleet's firsts: every machine's earliest classified sighting of a kind.
        Index("ix_machine_piece_keys_kind_first", "kind", "first_classified"),
    )


class MachinePieceDayMark(Base):
    """A machine-day whose pieces changed. Appended by triggers, taken (deleted)
    by the stats worker. No foreign key: a machine being deleted cascades to its
    pieces, whose trigger marks days of a machine that is going away."""

    __tablename__ = "machine_piece_day_marks"

    id = Column(_SERIAL, primary_key=True, autoincrement=True)
    machine_id = Column(UUID(as_uuid=True), nullable=False)
    day = Column(Date, nullable=False)

    __table_args__ = (Index("ix_machine_piece_day_marks_machine", "machine_id"),)


# --- The triggers -------------------------------------------------------------------
#
# The migration creates them on Postgres; these create them wherever
# ``Base.metadata.create_all`` builds the tables (the tests). The Postgres text
# here and in the migration is the same.

# The columns a piece's stats read. An update that changes none of them (a
# correction, a training label, a re-sent record) marks nothing.
_STAT_COLUMNS = ("machine_id", "seen_at", "classification_status", "part_id", "part_name", "color_id", "color_name", "bin_x")

PG_DAY = "COALESCE((({r}.seen_at) AT TIME ZONE 'UTC')::date, DATE '0001-01-01')"


def _pg_changed() -> str:
    cols = ", ".join(f"n.{c}" for c in _STAT_COLUMNS)
    old = ", ".join(f"o.{c}" for c in _STAT_COLUMNS)
    return f"({cols}) IS DISTINCT FROM ({old})"


PG_PIECE_MARK_FUNCTION = f"""
CREATE OR REPLACE FUNCTION machine_piece_days_mark() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO machine_piece_day_marks (machine_id, day)
        SELECT DISTINCT n.machine_id, {PG_DAY.format(r='n')} FROM new_rows n;
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO machine_piece_day_marks (machine_id, day)
        SELECT n.machine_id, {PG_DAY.format(r='n')}
          FROM new_rows n JOIN old_rows o ON o.id = n.id WHERE {_pg_changed()}
        UNION
        SELECT o.machine_id, {PG_DAY.format(r='o')}
          FROM new_rows n JOIN old_rows o ON o.id = n.id WHERE {_pg_changed()};
    ELSE
        INSERT INTO machine_piece_day_marks (machine_id, day)
        SELECT DISTINCT o.machine_id, {PG_DAY.format(r='o')} FROM old_rows o;
    END IF;
    RETURN NULL;
END
$$
"""

# One trigger per event: Postgres allows transition tables on a single event only.
PG_PIECE_MARK_TRIGGERS = (
    "CREATE OR REPLACE TRIGGER machine_pieces_mark_days_insert AFTER INSERT ON machine_pieces "
    "REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT EXECUTE FUNCTION machine_piece_days_mark()",
    "CREATE OR REPLACE TRIGGER machine_pieces_mark_days_update AFTER UPDATE ON machine_pieces "
    "REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT EXECUTE FUNCTION machine_piece_days_mark()",
    "CREATE OR REPLACE TRIGGER machine_pieces_mark_days_delete AFTER DELETE ON machine_pieces "
    "REFERENCING OLD TABLE AS old_rows FOR EACH STATEMENT EXECUTE FUNCTION machine_piece_days_mark()",
)

_SQLITE_DAY = "COALESCE(date({r}.seen_at), '0001-01-01')"
_SQLITE_CHANGED = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in _STAT_COLUMNS)

SQLITE_PIECE_MARK_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS machine_pieces_mark_days_insert AFTER INSERT ON machine_pieces BEGIN "
    f"INSERT INTO machine_piece_day_marks (machine_id, day) VALUES (NEW.machine_id, {_SQLITE_DAY.format(r='NEW')}); END",
    f"CREATE TRIGGER IF NOT EXISTS machine_pieces_mark_days_update AFTER UPDATE ON machine_pieces WHEN {_SQLITE_CHANGED} BEGIN "
    f"INSERT INTO machine_piece_day_marks (machine_id, day) VALUES (NEW.machine_id, {_SQLITE_DAY.format(r='NEW')}); "
    f"INSERT INTO machine_piece_day_marks (machine_id, day) VALUES (OLD.machine_id, {_SQLITE_DAY.format(r='OLD')}); END",
    "CREATE TRIGGER IF NOT EXISTS machine_pieces_mark_days_delete AFTER DELETE ON machine_pieces BEGIN "
    f"INSERT INTO machine_piece_day_marks (machine_id, day) VALUES (OLD.machine_id, {_SQLITE_DAY.format(r='OLD')}); END",
)

for _statement in (PG_PIECE_MARK_FUNCTION, *PG_PIECE_MARK_TRIGGERS):
    event.listen(Base.metadata, "after_create", DDL(_statement).execute_if(dialect="postgresql"))
for _statement in SQLITE_PIECE_MARK_TRIGGERS:
    event.listen(Base.metadata, "after_create", DDL(_statement).execute_if(dialect="sqlite"))
