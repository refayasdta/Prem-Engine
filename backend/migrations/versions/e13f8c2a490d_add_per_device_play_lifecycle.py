"""add per-device Play lifecycle

Revision ID: e13f8c2a490d
Revises: d92e4a6f310b
Create Date: 2026-08-14 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e13f8c2a490d"
down_revision: str | None = "d92e4a6f310b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stored_simulations",
        sa.Column(
            "simulation_scope",
            sa.String(length=24),
            server_default="legacy_shared",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_stored_simulations_valid_simulation_scope"),
        "stored_simulations",
        "simulation_scope = 'legacy_shared'",
    )
    op.create_table(
        "device_simulations",
        sa.Column("device_simulation_uuid", sa.Uuid(), nullable=False),
        sa.Column("device_uuid", sa.Uuid(), nullable=False),
        sa.Column("match_uuid", sa.Uuid(), nullable=False),
        sa.Column("schedule_revision_uuid", sa.Uuid(), nullable=False),
        sa.Column("schedule_revision_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("play_classification", sa.String(length=48), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("missed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("void_reason", sa.String(length=120), nullable=True),
        sa.Column("feature_cutoff_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_source_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feature_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("feature_snapshot_checksum", sa.String(length=64), nullable=True),
        sa.Column("model_version", sa.String(length=120), nullable=True),
        sa.Column("statistics_model_version", sa.String(length=120), nullable=True),
        sa.Column("model_artifact_uuid", sa.Uuid(), nullable=True),
        sa.Column("model_artifact_checksum", sa.String(length=64), nullable=True),
        sa.Column("expected_home_goals", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column("expected_away_goals", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column("home_win_probability", sa.Numeric(precision=9, scale=8), nullable=True),
        sa.Column("draw_probability", sa.Numeric(precision=9, scale=8), nullable=True),
        sa.Column("away_win_probability", sa.Numeric(precision=9, scale=8), nullable=True),
        sa.Column(
            "statistics_distribution",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("expected_lineups", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("random_seed", sa.Integer(), nullable=True),
        sa.Column("home_goals", sa.SmallInteger(), nullable=True),
        sa.Column("away_goals", sa.SmallInteger(), nullable=True),
        sa.Column("statistics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("events", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("simulation_checksum", sa.String(length=64), nullable=True),
        sa.Column("presentation_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "presentation_duration_seconds",
            sa.SmallInteger(),
            server_default="60",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "away_goals IS NULL OR away_goals >= 0",
            name=op.f("ck_device_simulations_nonnegative_away_score"),
        ),
        sa.CheckConstraint(
            "home_goals IS NULL OR home_goals >= 0",
            name=op.f("ck_device_simulations_nonnegative_home_score"),
        ),
        sa.CheckConstraint(
            "(state = 'missed' AND generated_at IS NULL AND simulation_checksum IS NULL) "
            "OR (state IN ('played', 'void'))",
            name=op.f("ck_device_simulations_missed_has_no_generated_simulation"),
        ),
        sa.CheckConstraint(
            "play_classification IS NULL OR play_classification IN "
            "('pre_kickoff_user_simulation', 'in_play_user_simulation')",
            name=op.f("ck_device_simulations_valid_play_classification"),
        ),
        sa.CheckConstraint(
            "presentation_duration_seconds > 0",
            name=op.f("ck_device_simulations_positive_presentation_duration"),
        ),
        sa.CheckConstraint(
            "state IN ('played', 'missed', 'void')",
            name=op.f("ck_device_simulations_valid_state"),
        ),
        sa.ForeignKeyConstraint(["match_uuid"], ["matches.match_uuid"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["model_artifact_uuid"],
            ["local_model_artifacts.artifact_uuid"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["schedule_revision_uuid"],
            ["fixture_schedule_revisions.revision_uuid"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("device_simulation_uuid"),
        sa.UniqueConstraint(
            "device_uuid",
            "match_uuid",
            "schedule_revision_uuid",
            name="uq_device_simulations_device_match_revision",
        ),
    )
    op.create_index(
        "ix_device_simulations_device_created",
        "device_simulations",
        ["device_uuid", "created_at"],
        unique=False,
    )
    for column in (
        "device_uuid",
        "match_uuid",
        "model_artifact_uuid",
        "schedule_revision_uuid",
        "state",
    ):
        op.create_index(
            op.f(f"ix_device_simulations_{column}"),
            "device_simulations",
            [column],
            unique=False,
        )


def downgrade() -> None:
    op.drop_table("device_simulations")
    op.drop_constraint(
        op.f("ck_stored_simulations_valid_simulation_scope"),
        "stored_simulations",
        type_="check",
    )
    op.drop_column("stored_simulations", "simulation_scope")
