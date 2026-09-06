"""set instance progress samples: the pace history behind rate, ETA and plateau

A linear ETA from the overall average is misleading: common parts arrive
first, the rate decays, and parts that are not in the pile never come. The
set pages need the rate of the last hour, a rough time to 90 % from that rate,
and a plateau call when the pile has nothing left for a set. That needs a
history: one total_found sample per instance every few minutes while a
machine reports.

Revision ID: b9d1f3a5c7e2
Revises: f0e1d2c3b4a5
"""

import sqlalchemy as sa
from alembic import op

revision = "b9d1f3a5c7e2"
down_revision = "f0e1d2c3b4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "set_instance_progress_samples",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("set_instance_id", sa.UUID(), nullable=False),
        sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_found", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["set_instance_id"], ["set_instances.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_set_instance_progress_samples_instance_time",
        "set_instance_progress_samples",
        ["set_instance_id", "sampled_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_set_instance_progress_samples_instance_time", table_name="set_instance_progress_samples")
    op.drop_table("set_instance_progress_samples")
