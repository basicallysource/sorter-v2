"""Counts kept so requests stop counting: crops per machine, samples per week, datasets per machine

Revision ID: b9d3f5a7c1e2
Revises: a6e1c3b5d7f9
Create Date: 2026-10-12

  * machine_stats_cache.channel_crops: a machine's upstream channel crops. The
    machine's crops page counted all of them (millions) on every page.
  * sample_diversity_weekly: one row per machine, week, capture reason and
    source, with the samples per piece-count bucket. The samples diversity
    overview counted, and fetched the upload time of, every sample per request.
  * model_dataset_machines: how many of a model's recorded dataset samples
    came from each machine. The model page joined the whole dataset to the
    samples table on every view. Filled here from what is recorded; kept as
    samples are recorded.
  * machine_stats_cache.control_data: a machine's control-data segments summed
    per combination of modes, and an index on the segments' created_at for the
    newest ones. The admin inventory read and sorted every segment.

The worker-kept ones are filled by the stats worker's next pass (hourly, and
once at start): until then the crops page counts 0, and the diversity overview
and the control-data inventory are empty.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b9d3f5a7c1e2"
down_revision = "a6e1c3b5d7f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default so the previous release, which does not know the column,
    # can still insert cache rows during the deploy and on a rollback.
    op.add_column(
        "machine_stats_cache",
        sa.Column("channel_crops", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "machine_stats_cache",
        sa.Column("control_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.create_index(
        "ix_machine_control_data_segments_created_at", "machine_control_data_segments", ["created_at"]
    )
    op.create_table(
        "sample_diversity_weekly",
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("machines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("week", sa.Date(), nullable=False),
        sa.Column("capture_reason", sa.String(), nullable=False),
        sa.Column("source_role", sa.String(), nullable=False),
        sa.Column("buckets", postgresql.JSONB(), nullable=False),
        sa.Column("samples", sa.Integer(), nullable=False),
        sa.Column("score_sum", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("scored", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("first_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("machine_id", "week", "capture_reason", "source_role"),
    )
    op.create_table(
        "model_dataset_machines",
        sa.Column("model_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("detection_models.id", ondelete="CASCADE"), nullable=False),
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("machines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("train", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("val", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("model_id", "machine_id"),
    )
    op.execute(
        """
        INSERT INTO model_dataset_machines (model_id, machine_id, train, val)
        SELECT d.model_id, s.machine_id, count(*) FILTER (WHERE d.split <> 'val'), count(*) FILTER (WHERE d.split = 'val')
        FROM model_dataset_samples d JOIN samples s ON s.id = d.sample_id
        GROUP BY d.model_id, s.machine_id
        """
    )


def downgrade() -> None:
    op.drop_table("model_dataset_machines")
    op.drop_table("sample_diversity_weekly")
    op.drop_index("ix_machine_control_data_segments_created_at", table_name="machine_control_data_segments")
    op.drop_column("machine_stats_cache", "control_data")
    op.drop_column("machine_stats_cache", "channel_crops")
