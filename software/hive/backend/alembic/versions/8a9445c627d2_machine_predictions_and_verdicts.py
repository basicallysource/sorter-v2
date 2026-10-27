"""Machine predictions, Hive feedback state on label rows, verdict views

Revision ID: 8a9445c627d2
Revises: 5f4b1adc76ba

- machine_piece_predictions: every ranked part and colour answer a machine
  got for a piece (data type piece_predictions).
- piece_color_labels.brickognize_feedback_at, piece_part_labels.part_correct
  and .brickognize_feedback_at: Hive's own Brickognize feedback state lives on
  the labeler's row; machine_pieces' verdict columns are the machine
  operator's alone.
- Views piece_color_verdicts and piece_part_verdicts: one row per verdict,
  machine operator's and Hive labelers' alike, with its source, for training.
  The SQL works on Postgres and SQLite (the tests build the views from it).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8a9445c627d2"
down_revision: Union[str, None] = "5f4b1adc76ba"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PIECE_COLOR_VERDICTS_SQL = """
CREATE VIEW piece_color_verdicts AS
SELECT 'machine' AS source,
       m.owner_id AS verdict_by,
       p.machine_id AS machine_id,
       p.piece_uuid AS piece_uuid,
       p.color_corrected_id AS color_id,
       (1 = 0) AS cant_tell,
       p.correction_updated_at AS verdict_at,
       p.color_id AS machine_color_id,
       p.color_provider AS machine_color_provider,
       p.color_confidence AS machine_color_confidence
FROM machine_pieces p
JOIN machines m ON m.id = p.machine_id
WHERE p.color_corrected_id IS NOT NULL
UNION ALL
SELECT 'hive' AS source,
       l.labeler_id AS verdict_by,
       l.machine_id AS machine_id,
       l.piece_uuid AS piece_uuid,
       CAST(l.color_id AS VARCHAR) AS color_id,
       l.cant_tell AS cant_tell,
       l.updated_at AS verdict_at,
       p.color_id AS machine_color_id,
       p.color_provider AS machine_color_provider,
       p.color_confidence AS machine_color_confidence
FROM piece_color_labels l
LEFT JOIN machine_pieces p ON p.machine_id = l.machine_id AND p.piece_uuid = l.piece_uuid
"""

PIECE_PART_VERDICTS_SQL = """
CREATE VIEW piece_part_verdicts AS
SELECT 'machine' AS source,
       m.owner_id AS verdict_by,
       p.machine_id AS machine_id,
       p.piece_uuid AS piece_uuid,
       CASE WHEN p.part_correct THEN p.part_id END AS part_num,
       p.part_correct AS part_correct,
       (1 = 0) AS cant_tell,
       p.correction_updated_at AS verdict_at,
       p.part_id AS machine_part_id,
       p.mold_provider AS machine_mold_provider,
       p.confidence AS machine_confidence
FROM machine_pieces p
JOIN machines m ON m.id = p.machine_id
WHERE p.part_correct IS NOT NULL
UNION ALL
SELECT 'hive' AS source,
       l.labeler_id AS verdict_by,
       l.machine_id AS machine_id,
       l.piece_uuid AS piece_uuid,
       l.part_num AS part_num,
       COALESCE(l.part_correct, CASE WHEN l.part_num IS NOT NULL AND p.part_id IS NOT NULL
                                     THEN l.part_num = p.part_id END) AS part_correct,
       l.cant_tell AS cant_tell,
       l.updated_at AS verdict_at,
       p.part_id AS machine_part_id,
       p.mold_provider AS machine_mold_provider,
       p.confidence AS machine_confidence
FROM piece_part_labels l
LEFT JOIN machine_pieces p ON p.machine_id = l.machine_id AND p.piece_uuid = l.piece_uuid
"""


def upgrade() -> None:
    op.create_table(
        "machine_piece_predictions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "machine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("machines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("piece_uuid", sa.String(), nullable=False),
        sa.Column("local_id", sa.BigInteger(), nullable=False),
        sa.Column("request", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("value_id", sa.String(), nullable=False),
        sa.Column("value_name", sa.String(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("predicted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "machine_id", "piece_uuid", "request", "kind", "rank",
            name="uq_machine_piece_predictions_piece_request_kind_rank",
        ),
    )
    op.add_column("piece_color_labels", sa.Column("brickognize_feedback_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("piece_part_labels", sa.Column("part_correct", sa.Boolean(), nullable=True))
    op.add_column("piece_part_labels", sa.Column("brickognize_feedback_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(PIECE_COLOR_VERDICTS_SQL)
    op.execute(PIECE_PART_VERDICTS_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS piece_part_verdicts")
    op.execute("DROP VIEW IF EXISTS piece_color_verdicts")
    op.drop_column("piece_part_labels", "brickognize_feedback_at")
    op.drop_column("piece_part_labels", "part_correct")
    op.drop_column("piece_color_labels", "brickognize_feedback_at")
    op.drop_table("machine_piece_predictions")
