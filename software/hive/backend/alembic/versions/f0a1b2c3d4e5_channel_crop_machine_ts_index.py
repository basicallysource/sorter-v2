"""channel crop machine+ts index

Revision ID: f0a1b2c3d4e5
Revises: f7a1b2c3d4e5
Create Date: 2026-07-13 19:10:00.000000

The piece-labeling grid orders/filters by whether a piece has any "same piece"
candidate crops — a correlated EXISTS over machine_channel_crops filtered by
(machine_id, ts range across all channels). The existing composite index leads
with (machine_id, channel, ...), which can't range-seek ts without a channel, so
this adds a plain (machine_id, ts) index for that probe.

"""

from typing import Sequence, Union

from alembic import op


revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, None] = "f7a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_machine_channel_crops_machine_ts",
        "machine_channel_crops",
        ["machine_id", "ts"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_machine_channel_crops_machine_ts", table_name="machine_channel_crops")
