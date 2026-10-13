"""Machine predictions from any source

Revision ID: b3d5f7a9c1e4
Revises: a7c9e1b3d5f8
Create Date: 2026-10-13

machine_piece_predictions keeps a piece's predictions from any source: the
machine's own classification while sorting ("live", what every row so far is)
or a later run of a model over the piece's stored images, by the run's label.
New columns: source (NOT NULL, default "live", so sorters that send none keep
syncing), model_name and images (which of the piece's images the prediction
was made from). The natural key gains source.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b3d5f7a9c1e4"
down_revision = "a7c9e1b3d5f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "machine_piece_predictions",
        sa.Column("source", sa.String(), nullable=False, server_default="live"),
    )
    op.add_column("machine_piece_predictions", sa.Column("model_name", sa.String(), nullable=True))
    op.add_column("machine_piece_predictions", sa.Column("images", postgresql.JSONB(), nullable=True))
    op.drop_constraint(
        "uq_machine_piece_predictions_piece_request_kind_rank", "machine_piece_predictions", type_="unique"
    )
    op.create_unique_constraint(
        "uq_machine_piece_predictions_piece_source_request_kind_rank",
        "machine_piece_predictions",
        ["machine_id", "piece_uuid", "source", "request", "kind", "rank"],
    )


def downgrade() -> None:
    op.execute("DELETE FROM machine_piece_predictions WHERE source <> 'live'")
    op.drop_constraint(
        "uq_machine_piece_predictions_piece_source_request_kind_rank", "machine_piece_predictions", type_="unique"
    )
    op.create_unique_constraint(
        "uq_machine_piece_predictions_piece_request_kind_rank",
        "machine_piece_predictions",
        ["machine_id", "piece_uuid", "request", "kind", "rank"],
    )
    op.drop_column("machine_piece_predictions", "images")
    op.drop_column("machine_piece_predictions", "model_name")
    op.drop_column("machine_piece_predictions", "source")
