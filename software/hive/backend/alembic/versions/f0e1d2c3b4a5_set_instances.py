"""set instances: progress belongs to a physical set copy

Set progress used to hang off a machine's profile assignment and was wiped
whenever the assignment changed. A set instance is one physical copy of a set
the user is extracting; its progress survives profile edits, machine swaps and
runs, and the same set can be owned several times.

Assignment-keyed progress rows whose profile rules already name an instance
(``set_instance_id`` on a set rule) move over; the rest stay in
machine_set_progress for the legacy sync path.

Revision ID: f0e1d2c3b4a5
Revises: e1f2a3b4c5d6
"""

import json
from uuid import UUID, uuid4

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

    _migrate_assignment_progress()


def _instance_bound_sets(rules) -> dict[str, str]:
    """set_num -> set_instance_id for every set rule in the tree that names an instance."""
    bound: dict[str, str] = {}
    stack = list(rules) if isinstance(rules, list) else []
    while stack:
        rule = stack.pop()
        if not isinstance(rule, dict):
            continue
        stack.extend(rule.get("children") or [])
        instance_id = rule.get("set_instance_id")
        set_num = rule.get("set_num")
        if rule.get("rule_type") == "set" and instance_id and set_num:
            bound[str(set_num)] = str(instance_id)
    return bound


def _migrate_assignment_progress() -> None:
    # Typed binds and result columns: uuids are native on postgres and 32-hex
    # strings on sqlite, and the rule JSON carries them dashed.
    bind = op.get_bind()
    uuid_param = lambda name: sa.bindparam(name, type_=sa.UUID())  # noqa: E731
    assignments = bind.execute(
        sa.text(
            "SELECT a.id AS assignment_id, v.rules_json AS rules_json "
            "FROM machine_profile_assignments a "
            "JOIN sorting_profile_versions v ON v.id = COALESCE(a.active_version_id, a.desired_version_id)"
        ).columns(assignment_id=sa.UUID())
    ).mappings().all()
    instance_known = sa.text("SELECT 1 FROM set_instances WHERE id = :iid").bindparams(uuid_param("iid"))
    select_rows = sa.text(
        "SELECT id, part_num, color_id, quantity_needed, quantity_found, updated_at "
        "FROM machine_set_progress WHERE assignment_id = :aid AND set_num = :set_num"
    ).bindparams(uuid_param("aid")).columns(id=sa.UUID(), updated_at=sa.DateTime(timezone=True))
    upsert_row = sa.text(
        "INSERT INTO set_instance_progress "
        "(id, set_instance_id, part_num, color_id, quantity_needed, quantity_found, updated_at) "
        "VALUES (:id, :iid, :part_num, :color_id, :needed, :found, :updated_at) "
        "ON CONFLICT (set_instance_id, part_num, color_id) DO UPDATE SET "
        "quantity_needed = excluded.quantity_needed, "
        "quantity_found = excluded.quantity_found, "
        "updated_at = excluded.updated_at"
    ).bindparams(uuid_param("id"), uuid_param("iid"), sa.bindparam("updated_at", type_=sa.DateTime(timezone=True)))
    delete_row = sa.text("DELETE FROM machine_set_progress WHERE id = :id").bindparams(uuid_param("id"))

    for assignment in assignments:
        rules = assignment["rules_json"]
        if isinstance(rules, str):
            rules = json.loads(rules)
        for set_num, instance_id in _instance_bound_sets(rules).items():
            instance_uuid = UUID(instance_id)
            if not bind.execute(instance_known, {"iid": instance_uuid}).scalar():
                continue
            rows = bind.execute(select_rows, {"aid": assignment["assignment_id"], "set_num": set_num}).mappings().all()
            for row in rows:
                bind.execute(
                    upsert_row,
                    {
                        "id": uuid4(),
                        "iid": instance_uuid,
                        "part_num": row["part_num"],
                        "color_id": row["color_id"],
                        "needed": row["quantity_needed"],
                        "found": row["quantity_found"],
                        "updated_at": row["updated_at"],
                    },
                )
                bind.execute(delete_row, {"id": row["id"]})


def downgrade() -> None:
    op.drop_index("ix_set_instance_progress_set_instance_id", table_name="set_instance_progress")
    op.drop_table("set_instance_progress")
    op.drop_index("ix_set_instances_user_id", table_name="set_instances")
    op.drop_table("set_instances")
