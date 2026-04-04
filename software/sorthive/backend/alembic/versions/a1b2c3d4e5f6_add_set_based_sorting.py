"""add set-based sorting

Revision ID: a1b2c3d4e5f6
Revises: c3e1a2d4b5f6
Create Date: 2026-04-04 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "c3e1a2d4b5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sorting_profiles", sa.Column("profile_type", sa.String(), server_default="rule", nullable=False))

    op.add_column("sorting_profile_versions", sa.Column("set_config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.create_table(
        "machine_set_progress",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("machine_id", sa.UUID(), nullable=False),
        sa.Column("assignment_id", sa.UUID(), nullable=False),
        sa.Column("set_num", sa.String(), nullable=False),
        sa.Column("part_num", sa.String(), nullable=False),
        sa.Column("color_id", sa.Integer(), nullable=False),
        sa.Column("quantity_needed", sa.Integer(), nullable=False),
        sa.Column("quantity_found", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignment_id"], ["machine_profile_assignments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "set_num", "part_num", "color_id", name="uq_machine_set_progress_assignment_part"),
    )
    op.create_index("ix_machine_set_progress_machine_id", "machine_set_progress", ["machine_id"], unique=False)
    op.create_index("ix_machine_set_progress_assignment_id", "machine_set_progress", ["assignment_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_machine_set_progress_assignment_id", table_name="machine_set_progress")
    op.drop_index("ix_machine_set_progress_machine_id", table_name="machine_set_progress")
    op.drop_table("machine_set_progress")

    op.drop_column("sorting_profile_versions", "set_config_json")

    op.drop_column("sorting_profiles", "profile_type")
