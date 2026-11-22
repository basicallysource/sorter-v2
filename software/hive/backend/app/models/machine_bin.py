from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.models import JSON_VARIANT, Base


class MachineBinEmptying(Base):
    """One emptying of one bin of a machine: a clear on the machine found the
    bin holding pieces and started it over. The pieces it took are the
    machine's records put in that bin (machine_pieces.bin_*, recorded_at)
    after the bin's emptying before, up to this one.

    Synced from the machine's bin_snapshot_layers (data type bin_emptyings);
    a row never changes."""

    __tablename__ = "machine_bin_emptyings"

    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True)
    # The machine's id for the row: this data type's cursor.
    local_id = Column(BigInteger, primary_key=True)
    # The clear's snapshot on the machine (every bin one clear emptied shares it).
    snapshot_id = Column(String, nullable=True)
    # The bin, numbered from 0 as the machine numbers them (machine_pieces'
    # bin_x, bin_y, bin_z).
    layer = Column(Integer, nullable=False)
    section = Column(Integer, nullable=False)
    bin = Column(Integer, nullable=False)
    # How many times the bin had been emptied before.
    epoch = Column(Integer, nullable=True)
    emptied_at = Column(DateTime(timezone=True), nullable=False)
    # How many pieces the machine counted in the bin.
    piece_count = Column(Integer, nullable=False, default=0)
    # The categories the bin was assigned when it was emptied.
    category_ids = Column(JSON_VARIANT, nullable=True)
    # What the clear covered: "bin", "layer" or "all".
    scope = Column(String, nullable=True)
    # The sorting profile the machine sorted by then.
    profile_id = Column(String, nullable=True)
    profile_name = Column(String, nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # A bin's emptyings in order: the one before a moment, the one after.
        Index("ix_machine_bin_emptyings_bin", "machine_id", "layer", "section", "bin", "emptied_at"),
    )


class MachineBinLayout(Base):
    """A layout a machine ran, from when it changed until the next row: its
    layers (sections and bins), the categories each bin was assigned and what
    the profile called them, the bins flagged not in inventory, and the profile
    it sorted by.

    Synced from the machine's bin_layout_history (data type bin_layouts); a row
    never changes."""

    __tablename__ = "machine_bin_layouts"

    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True)
    # The machine's id for the row: this data type's cursor, in the order the
    # layouts ran.
    local_id = Column(BigInteger, primary_key=True)
    changed_at = Column(DateTime(timezone=True), nullable=False)
    # {layers: [{sections: [[size, ...], ...], enabled, section_enabled,
    # max_dimension_mm, max_pieces_per_bin, ...}], bin_categories:
    # [layer][section][bin] -> [category id], not_in_inventory_bins,
    # category_names: {id: name}, profile: {profile_id, profile_name, ...}}
    layout = Column(JSON_VARIANT, nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # The layout running at a moment: the newest one changed by then.
        Index("ix_machine_bin_layouts_changed_at", "machine_id", "changed_at"),
    )
