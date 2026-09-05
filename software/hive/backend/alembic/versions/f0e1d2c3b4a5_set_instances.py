"""set instances: progress belongs to a physical set copy

Set progress used to hang off a machine's profile assignment and was wiped
whenever the assignment changed. A set instance is one physical copy of a set
the user is extracting; its progress survives profile edits, machine swaps and
runs, and the same set can be owned several times.

Machines keep reporting absolute per-session counts; set_instance_machine_counts
remembers each machine's last report so only the difference is added to the
instance. No data moves: an assignment-keyed row can only reference an
instance once instances exist, so machine_set_progress stays as is for the
legacy sync path.

Revision ID: f0e1d2c3b4a5
Revises: e1f2a3b4c5d6
"""

import sqlalchemy as sa
from alembic import op

revision = "f0e1d2c3b4a5"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "set_instances",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("set_source", sa.String(), nullable=False, server_default="rebrickable"),
        sa.Column("set_num", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("include_spares", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('open', 'complete', 'archived')", name="ck_set_instances_status"),
    )
    op.create_index("ix_set_instances_user_id", "set_instances", ["user_id"])

    op.create_table(
        "set_instance_progress",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("set_instance_id", sa.UUID(), nullable=False),
        sa.Column("part_num", sa.String(), nullable=False),
        sa.Column("color_id", sa.Integer(), nullable=False),
        sa.Column("quantity_needed", sa.Integer(), nullable=False),
        sa.Column("quantity_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["set_instance_id"], ["set_instances.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("set_instance_id", "part_num", "color_id", name="uq_set_instance_progress_part"),
    )
    op.create_index("ix_set_instance_progress_set_instance_id", "set_instance_progress", ["set_instance_id"])

    op.create_table(
        "set_instance_machine_counts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("set_instance_id", sa.UUID(), nullable=False),
        sa.Column("machine_id", sa.UUID(), nullable=False),
        sa.Column("part_num", sa.String(), nullable=False),
        sa.Column("color_id", sa.Integer(), nullable=False),
        sa.Column("quantity_reported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["set_instance_id"], ["set_instances.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("set_instance_id", "machine_id", "part_num", "color_id", name="uq_set_instance_machine_counts_part"),
    )
    op.create_index("ix_set_instance_machine_counts_set_instance_id", "set_instance_machine_counts", ["set_instance_id"])


def downgrade() -> None:
    op.drop_index("ix_set_instance_machine_counts_set_instance_id", table_name="set_instance_machine_counts")
    op.drop_table("set_instance_machine_counts")
    op.drop_index("ix_set_instance_progress_set_instance_id", table_name="set_instance_progress")
    op.drop_table("set_instance_progress")
    op.drop_index("ix_set_instances_user_id", table_name="set_instances")
    op.drop_table("set_instances")
