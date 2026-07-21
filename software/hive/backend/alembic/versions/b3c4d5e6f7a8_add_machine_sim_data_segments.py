"""add machine sim data segments

Revision ID: b3c4d5e6f7a8
Revises: d1f3b5c7e9a2
Create Date: 2026-07-21 12:00:00.000000

Machine -> Hive sync of feeder-dynamics ("sim data") capture segments. Each
row is one gzipped JSONL file of timestamped records — perception piece
states, stepper commands, config changes, dispense events — captured while
the machine was actively sorting, plus the summary columns needed to filter
segments without opening files (the full context snapshot is the meta record
inside the file). Synced via the same watermark table (machine_sync_state,
data_type "sim_data_segments"). Segments evicted from the machine's local
store before syncing ride up metadata-only (data_key NULL, evicted_locally
true).

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "d1f3b5c7e9a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "machine_sim_data_segments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("machine_id", sa.UUID(), nullable=False),
        sa.Column("local_id", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records", sa.Integer(), nullable=True),
        sa.Column("bytes", sa.BigInteger(), nullable=True),
        sa.Column("machine_setup", sa.String(), nullable=True),
        sa.Column("feeder_mode", sa.String(), nullable=True),
        sa.Column("classification_mode", sa.String(), nullable=True),
        sa.Column("autotune_mode", sa.String(), nullable=True),
        sa.Column("data_key", sa.String(), nullable=True),
        sa.Column("evicted_locally", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("machine_id", "local_id", name="uq_machine_sim_data_segments_machine_local"),
    )
    op.create_index(
        "ix_machine_sim_data_segments_machine_local_id",
        "machine_sim_data_segments",
        ["machine_id", "local_id"],
    )
    op.create_index(
        "ix_machine_sim_data_segments_machine_started",
        "machine_sim_data_segments",
        ["machine_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_machine_sim_data_segments_machine_started", table_name="machine_sim_data_segments")
    op.drop_index("ix_machine_sim_data_segments_machine_local_id", table_name="machine_sim_data_segments")
    op.drop_table("machine_sim_data_segments")
