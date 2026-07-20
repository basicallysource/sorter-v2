"""normalize operator-flagged capture issues into their own table

Revision ID: c2e4a6b8d0f3
Revises: b2d4f6a8c0e1
Create Date: 2026-07-19 14:00:00.000000

Replaces machine_pieces.rejection_reasons (added in a1c3e5f7b9d2 as a JSON list)
with machine_piece_rejection_reasons — one row per (machine, piece, reason), so
the flags can be indexed, grouped and counted instead of scanned and parsed.

The old column is migrated, not dropped blind: any JSON list already stored is
expanded into rows first. In practice it should be empty (the blob shipped and
was normalized the same day), but a blind drop would silently eat operator
verdicts on any machine that did sync in between.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c2e4a6b8d0f3"
down_revision: Union[str, Sequence[str], None] = "b2d4f6a8c0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "machine_piece_rejection_reasons",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("machine_id", sa.UUID(), nullable=False),
        sa.Column("piece_uuid", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "machine_id", "piece_uuid", "reason", name="uq_machine_piece_rejection_reasons_piece_reason"
        ),
    )
    op.create_index(
        "ix_machine_piece_rejection_reasons_machine_piece",
        "machine_piece_rejection_reasons",
        ["machine_id", "piece_uuid"],
        unique=False,
    )
    op.create_index(
        "ix_machine_piece_rejection_reasons_reason",
        "machine_piece_rejection_reasons",
        ["reason"],
        unique=False,
    )

    # Expand any existing JSON list into rows before the column goes away.
    # jsonb_array_elements_text is Postgres-only; sqlite test DBs have no data
    # to migrate, so skip there rather than hand-rolling a JSON1 equivalent.
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            INSERT INTO machine_piece_rejection_reasons
                (id, machine_id, piece_uuid, reason, created_at)
            SELECT gen_random_uuid(), p.machine_id, p.piece_uuid, r.reason, now()
            FROM machine_pieces p
            CROSS JOIN LATERAL jsonb_array_elements_text(p.rejection_reasons) AS r(reason)
            WHERE p.rejection_reasons IS NOT NULL
              AND jsonb_typeof(p.rejection_reasons) = 'array'
            ON CONFLICT DO NOTHING
            """
        )

    op.drop_column("machine_pieces", "rejection_reasons")


def downgrade() -> None:
    op.add_column(
        "machine_pieces",
        sa.Column(
            "rejection_reasons",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            UPDATE machine_pieces p
            SET rejection_reasons = agg.reasons
            FROM (
                SELECT machine_id, piece_uuid, jsonb_agg(reason ORDER BY reason) AS reasons
                FROM machine_piece_rejection_reasons
                GROUP BY machine_id, piece_uuid
            ) agg
            WHERE p.machine_id = agg.machine_id AND p.piece_uuid = agg.piece_uuid
            """
        )
    op.drop_index(
        "ix_machine_piece_rejection_reasons_reason", table_name="machine_piece_rejection_reasons"
    )
    op.drop_index(
        "ix_machine_piece_rejection_reasons_machine_piece",
        table_name="machine_piece_rejection_reasons",
    )
    op.drop_table("machine_piece_rejection_reasons")
