from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class MachineLot(Base):
    """A collection of pieces that came in together (a box bought second hand,
    a customer's bulk order), as the machine keeps it in its lots table.

    Synced whole with the machine's sorting runs (data type sorting_runs):
    each send replaces the machine's lots and runs."""

    __tablename__ = "machine_lots"

    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True)
    # The machine's own id for the lot.
    lot_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    # When the machine made it.
    created_at = Column(DateTime(timezone=True), nullable=True)


class MachineSortingRun(Base):
    """One stretch of sorting, as the machine keeps it in its sorting_runs
    table: from started_at until the next run's started_at. A piece belongs to
    the run whose stretch holds its seen_at. A run can name a lot and either
    add its pieces to it (a first pass) or not (another pass over pieces the
    lot already counted), so a lot's pieces are those seen in the stretches of
    its runs that add to it.

    Not machine_pieces.run_id, which is one backend process on the machine."""

    __tablename__ = "machine_sorting_runs"

    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True)
    # The machine's own id for the run.
    run_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    note = Column(String, nullable=True)
    # The machine's id of the lot it names, if any (machine_lots.lot_id).
    lot_id = Column(String, nullable=True)
    adds_to_lot = Column(Boolean, nullable=False, default=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=True)
