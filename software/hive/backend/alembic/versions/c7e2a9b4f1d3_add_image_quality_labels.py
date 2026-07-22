"""add image quality labels

Revision ID: c7e2a9b4f1d3
Revises: e7f8a9b0c1d2
Create Date: 2026-07-21 12:00:00.000000

Per-image, per-labeler quality judgement on a single crop: a `high_quality` star
plus "not good enough for classification" reason flags (low_resolution /
motion_blur / not_contained / no_piece_in_frame / other_bad). Boolean columns so
the flags are directly queryable — the point is to later filter e.g. every
motion-blurred crop as training data for an image-quality model.

Covers two crop entities via `crop_kind` (no FK to either, like
piece_crop_link_members.crop_local_id): 'piece_image' → machine_piece_images
keyed (machine_id, piece_uuid, seq); 'channel_crop' → machine_channel_crops keyed
(machine_id, crop_local_id). A partial unique index per kind enforces one row per
(image, labeler) while the other kind's key columns stay NULL.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7e2a9b4f1d3"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_BOOL_COLS = (
    "high_quality",
    "low_resolution",
    "motion_blur",
    "not_contained",
    "no_piece_in_frame",
    "other_bad",
)


def upgrade() -> None:
    op.create_table(
        "image_quality_labels",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("machine_id", sa.UUID(), nullable=False),
        sa.Column("labeler_id", sa.UUID(), nullable=False),
        sa.Column("crop_kind", sa.String(), nullable=False),
        sa.Column("piece_uuid", sa.String(), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=True),
        sa.Column("crop_local_id", sa.BigInteger(), nullable=True),
        *[sa.Column(c, sa.Boolean(), nullable=False, server_default=sa.false()) for c in _BOOL_COLS],
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["labeler_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # New rows get the boolean defaults from the app-side model, like the other
    # label tables (b7d1e2f3a4c5 / d3f5a7b9c1e4).
    for c in _BOOL_COLS:
        op.alter_column("image_quality_labels", c, server_default=None)
    # One row per (image, labeler), per crop kind. Partial because the unused
    # key columns are NULL for the other kind, and NULLs would defeat a single
    # combined unique constraint.
    op.create_index(
        "uq_image_quality_labels_piece_image",
        "image_quality_labels",
        ["machine_id", "piece_uuid", "seq", "labeler_id"],
        unique=True,
        postgresql_where=sa.text("crop_kind = 'piece_image'"),
        sqlite_where=sa.text("crop_kind = 'piece_image'"),
    )
    op.create_index(
        "uq_image_quality_labels_channel_crop",
        "image_quality_labels",
        ["machine_id", "crop_local_id", "labeler_id"],
        unique=True,
        postgresql_where=sa.text("crop_kind = 'channel_crop'"),
        sqlite_where=sa.text("crop_kind = 'channel_crop'"),
    )
    op.create_index(
        "ix_image_quality_labels_machine_piece", "image_quality_labels", ["machine_id", "piece_uuid"]
    )
    op.create_index(
        "ix_image_quality_labels_machine_crop", "image_quality_labels", ["machine_id", "crop_local_id"]
    )
    op.create_index("ix_image_quality_labels_labeler_id", "image_quality_labels", ["labeler_id"])


def downgrade() -> None:
    op.drop_index("ix_image_quality_labels_labeler_id", table_name="image_quality_labels")
    op.drop_index("ix_image_quality_labels_machine_crop", table_name="image_quality_labels")
    op.drop_index("ix_image_quality_labels_machine_piece", table_name="image_quality_labels")
    op.drop_index("uq_image_quality_labels_channel_crop", table_name="image_quality_labels")
    op.drop_index("uq_image_quality_labels_piece_image", table_name="image_quality_labels")
    op.drop_table("image_quality_labels")
