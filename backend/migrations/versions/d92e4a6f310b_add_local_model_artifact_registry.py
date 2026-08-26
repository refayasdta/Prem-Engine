"""add local model artifact registry

Revision ID: d92e4a6f310b
Revises: c81d7b5e2f0a
Create Date: 2026-08-14 10:35:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d92e4a6f310b"
down_revision: str | None = "c81d7b5e2f0a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "local_worker_state",
        sa.Column("last_training_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "local_worker_state",
        sa.Column("next_training_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "actual_result_revisions",
        sa.Column("training_eligible", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "actual_result_revisions",
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "local_model_artifacts",
        sa.Column("artifact_uuid", sa.Uuid(), nullable=False),
        sa.Column("model_type", sa.String(length=80), nullable=False),
        sa.Column("model_version", sa.String(length=120), nullable=False),
        sa.Column("season_uuid", sa.Uuid(), nullable=False),
        sa.Column("cutoff_matchweek", sa.SmallInteger(), nullable=False),
        sa.Column("cutoff_revision", sa.SmallInteger(), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("training_data_checksum", sa.String(length=64), nullable=False),
        sa.Column("fixture_set_checksum", sa.String(length=64), nullable=False),
        sa.Column(
            "included_fixture_uuids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("feature_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("runtime_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("artifact_path", sa.Text(), nullable=True),
        sa.Column("model_checksum", sa.String(length=64), nullable=True),
        sa.Column("report_checksum", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(training_data_checksum) = 64 AND length(fixture_set_checksum) = 64",
            name=op.f("ck_local_model_artifacts_dataset_checksums_are_sha256"),
        ),
        sa.CheckConstraint(
            "cutoff_matchweek BETWEEN 1 AND 60",
            name=op.f("ck_local_model_artifacts_valid_matchweek"),
        ),
        sa.CheckConstraint(
            "cutoff_revision >= 1",
            name=op.f("ck_local_model_artifacts_valid_cutoff_revision"),
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name=op.f("ck_local_model_artifacts_valid_status"),
        ),
        sa.ForeignKeyConstraint(["season_uuid"], ["seasons.season_uuid"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("artifact_uuid"),
        sa.UniqueConstraint("model_type", "season_uuid", "cutoff_matchweek", "cutoff_revision"),
        sa.UniqueConstraint("model_version"),
    )
    op.create_index(
        op.f("ix_local_model_artifacts_model_type"),
        "local_model_artifacts",
        ["model_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_local_model_artifacts_season_uuid"),
        "local_model_artifacts",
        ["season_uuid"],
        unique=False,
    )
    op.create_index(
        op.f("ix_local_model_artifacts_status"),
        "local_model_artifacts",
        ["status"],
        unique=False,
    )
    op.create_index(
        "uq_local_model_artifacts_active_type",
        "local_model_artifacts",
        ["model_type"],
        unique=True,
        postgresql_where=sa.text("active IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index("uq_local_model_artifacts_active_type", table_name="local_model_artifacts")
    op.drop_index(op.f("ix_local_model_artifacts_status"), table_name="local_model_artifacts")
    op.drop_index(op.f("ix_local_model_artifacts_season_uuid"), table_name="local_model_artifacts")
    op.drop_index(op.f("ix_local_model_artifacts_model_type"), table_name="local_model_artifacts")
    op.drop_table("local_model_artifacts")
    op.drop_column("actual_result_revisions", "voided_at")
    op.drop_column("actual_result_revisions", "training_eligible")
    op.drop_column("local_worker_state", "next_training_at")
    op.drop_column("local_worker_state", "last_training_at")
