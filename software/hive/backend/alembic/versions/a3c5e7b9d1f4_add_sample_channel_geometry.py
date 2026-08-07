"""add sample channel geometry

Revision ID: a3c5e7b9d1f4
Revises: c7e2a9b4f1d3
Create Date: 2026-07-22 12:00:00.000000

Per-sample channel-region geometry: the machine's mask outline (polygon) plus the
annulus/arc model for the channel visible in one sample's full frame. Stored
per-sample on purpose — the user can redraw regions at any time, so carrying the
geometry on each sample makes every frame self-describing (no versioning, no
before/after reconciliation). Lets Hive crop a full frame down to where the
channel actually is, server-side, after upload. Flat typed columns + a native
Postgres float[] for the polygon points — never a JSON blob (migrations only run
on Postgres; the sqlite test shim uses the JSON variant in the model layer).

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a3c5e7b9d1f4"
down_revision: Union[str, None] = "c7e2a9b4f1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ARC_COLS = (
    "drop_start_outer_angle",
    "drop_end_outer_angle",
    "drop_start_inner_angle",
    "drop_end_inner_angle",
    "exit_start_outer_angle",
    "exit_end_outer_angle",
    "exit_start_inner_angle",
    "exit_end_inner_angle",
    "precise_start_outer_angle",
    "precise_end_outer_angle",
    "precise_start_inner_angle",
    "precise_end_inner_angle",
)


def upgrade() -> None:
    op.create_table(
        "sample_channel_geometry",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sample_id", sa.UUID(), nullable=False),
        sa.Column("source_role", sa.String(), nullable=True),
        sa.Column("frame_width", sa.Integer(), nullable=True),
        sa.Column("frame_height", sa.Integer(), nullable=True),
        sa.Column("polygon_x", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("polygon_y", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("center_x", sa.Float(), nullable=True),
        sa.Column("center_y", sa.Float(), nullable=True),
        sa.Column("inner_radius", sa.Float(), nullable=True),
        sa.Column("outer_radius", sa.Float(), nullable=True),
        sa.Column("exit_outer_radius", sa.Float(), nullable=True),
        sa.Column("section_zero_angle_deg", sa.Float(), nullable=True),
        sa.Column("reverse", sa.Boolean(), nullable=True),
        *[sa.Column(c, sa.Float(), nullable=True) for c in _ARC_COLS],
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sample_id", name="uq_sample_channel_geometry_sample"),
    )


def downgrade() -> None:
    op.drop_table("sample_channel_geometry")
