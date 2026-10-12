"""The general job queue, the swatch finder registry, and per-sample swatch readings

Revision ID: 5f4b1adc76ba
Revises: c8f2a6d4e1b3

jobs: background work run by app.services.job_queue (kind, subject, payload,
status, priority, attempts, a lease, a result). A partial unique index keeps
one pending job per (kind, subject); another indexes the claim.

swatch_models: colour-reference palette finders reconciled from
SWATCH_MODEL_DIR, at most one active.

sample_swatch_runs / sample_swatches: one row per finder pass over a sample's
full frame, and one per palette tile it found with its reading.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "5f4b1adc76ba"
down_revision = "c8f2a6d4e1b3"
branch_labels = None
depends_on = None

_PENDING = "status IN ('queued', 'running')"


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(length=128), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('queued', 'running', 'done', 'failed')", name="ck_jobs_status"),
    )
    op.create_index(
        "uq_jobs_pending_kind_subject",
        "jobs",
        ["kind", "subject"],
        unique=True,
        postgresql_where=sa.text(_PENDING),
    )
    op.create_index(
        "ix_jobs_queued_priority",
        "jobs",
        [sa.text("priority DESC"), "run_after"],
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index("ix_jobs_status_finished_at", "jobs", ["status", "finished_at"])

    op.create_table(
        "swatch_models",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("colour_count", sa.Integer(), nullable=False),
        sa.Column("net_long_side", sa.Integer(), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("filename", name="uq_swatch_models_filename"),
    )

    op.create_table(
        "sample_swatch_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sample_id", sa.UUID(), nullable=False),
        sa.Column("model_id", sa.UUID(), nullable=True),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("model_sha256", sa.String(length=64), nullable=False),
        sa.Column("frame_width", sa.Integer(), nullable=False),
        sa.Column("frame_height", sa.Integer(), nullable=False),
        sa.Column("swatch_count", sa.Integer(), nullable=False),
        sa.Column("flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("seconds", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_id"], ["swatch_models.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sample_id", "model_sha256", name="uq_sample_swatch_runs_sample_model"),
    )
    op.create_index("ix_sample_swatch_runs_sample_id", "sample_swatch_runs", ["sample_id"])
    op.create_index("ix_sample_swatch_runs_model_sha256", "sample_swatch_runs", ["model_sha256"])

    op.create_table(
        "sample_swatches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("colour", sa.String(), nullable=False),
        sa.Column("bricklink_color_id", sa.Integer(), nullable=True),
        sa.Column("colour_score", sa.Float(), nullable=False),
        sa.Column("surface_score", sa.Float(), nullable=False),
        sa.Column("pixels", sa.Integer(), nullable=False),
        sa.Column("median_r", sa.Float(), nullable=False),
        sa.Column("median_g", sa.Float(), nullable=False),
        sa.Column("median_b", sa.Float(), nullable=False),
        sa.Column("std_r", sa.Float(), nullable=False),
        sa.Column("std_g", sa.Float(), nullable=False),
        sa.Column("std_b", sa.Float(), nullable=False),
        sa.Column("clipped", sa.Float(), nullable=False),
        sa.Column("centre_x", sa.Float(), nullable=False),
        sa.Column("centre_y", sa.Float(), nullable=False),
        sa.Column("box_x0", sa.Integer(), nullable=False),
        sa.Column("box_y0", sa.Integer(), nullable=False),
        sa.Column("box_x1", sa.Integer(), nullable=False),
        sa.Column("box_y1", sa.Integer(), nullable=False),
        sa.Column("length", sa.Float(), nullable=False),
        sa.Column("width", sa.Float(), nullable=False),
        sa.Column("flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["sample_swatch_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "position", name="uq_sample_swatches_run_position"),
    )


def downgrade() -> None:
    op.drop_table("sample_swatches")
    op.drop_index("ix_sample_swatch_runs_model_sha256", table_name="sample_swatch_runs")
    op.drop_index("ix_sample_swatch_runs_sample_id", table_name="sample_swatch_runs")
    op.drop_table("sample_swatch_runs")
    op.drop_table("swatch_models")
    op.drop_index("ix_jobs_status_finished_at", table_name="jobs")
    op.drop_index("ix_jobs_queued_priority", table_name="jobs")
    op.drop_index("uq_jobs_pending_kind_subject", table_name="jobs")
    op.drop_table("jobs")
