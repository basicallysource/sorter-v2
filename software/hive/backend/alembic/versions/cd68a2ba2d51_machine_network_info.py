"""machines.network_info: where to find a Sorter on its own networks

Revision ID: cd68a2ba2d51
Revises: 8f800313811a

The heartbeat carries a network block (addresses, the .local name, the UI and
API ports). It is stored as network_info, with network_reported_at for when
Hive received it. local_ui_port goes: no Sorter ever sent one, so it held
nothing or the column default "8000", which is the API's port, not the UI's.
The UI port now comes in the network block.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "cd68a2ba2d51"
down_revision = "8f800313811a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "machines",
        sa.Column("network_info", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True),
    )
    op.add_column("machines", sa.Column("network_reported_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_column("machines", "local_ui_port")


def downgrade() -> None:
    op.add_column("machines", sa.Column("local_ui_port", sa.String(), nullable=True))
    op.drop_column("machines", "network_reported_at")
    op.drop_column("machines", "network_info")
