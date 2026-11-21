from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class MachineSentBackPiece(Base):
    """A piece the machine sent back to be sorted again: a bin's pieces went
    back in the hopper. Its record (machine_pieces) stays, but no run or lot
    counts it; the piece's next sighting is a new record, and that one counts.

    Synced from the machine's sent_back_pieces table (data type
    sent_back_pieces); a row never changes."""

    __tablename__ = "machine_sent_back_pieces"

    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True)
    piece_uuid = Column(String, primary_key=True)
    # The machine's id for the row: this data type's cursor.
    local_id = Column(BigInteger, nullable=False)
    # The machine's id of the lot that no longer counts the piece.
    lot_id = Column(String, nullable=True)
    sent_back_at = Column(DateTime(timezone=True), nullable=False)
    # Why, as the operator put it.
    note = Column(String, nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=False)
