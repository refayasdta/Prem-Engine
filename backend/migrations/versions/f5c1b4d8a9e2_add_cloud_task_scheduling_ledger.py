"""add cloud task scheduling ledger

Revision ID: f5c1b4d8a9e2
Revises: d72d120a14aa
Create Date: 2026-08-13 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f5c1b4d8a9e2"
down_revision: str | None = "d72d120a14aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    state = postgresql.ENUM(
        "pending",
        "enqueued",
        "processing",
        "succeeded",
        "stale",
        "failed",
        name="forecast_task_state",
        create_type=False,
    )
    postgresql.ENUM(
        "pending",
        "enqueued",
        "processing",
        "succeeded",
        "stale",
        "failed",
        name="forecast_task_state",
    ).create(op.get_bind(), checkfirst=True)
    op.create_table(
        "forecast_task_schedules",
        sa.Column("schedule_uuid", sa.Uuid(), nullable=False),
        sa.Column("match_uuid", sa.Uuid(), nullable=False),
        sa.Column("schedule_revision_uuid", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.String(length=240), nullable=False),
        sa.Column("state", state, nullable=False),
        sa.Column("schedule_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cloud_task_name", sa.String(length=500), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_count", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "delivery_count >= 0", name=op.f("ck_forecast_task_schedules_nonnegative_deliveries")
        ),
        sa.ForeignKeyConstraint(["match_uuid"], ["matches.match_uuid"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["schedule_revision_uuid"],
            ["fixture_schedule_revisions.revision_uuid"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("schedule_uuid"),
        sa.UniqueConstraint("schedule_revision_uuid"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index(
        op.f("ix_forecast_task_schedules_match_uuid"), "forecast_task_schedules", ["match_uuid"]
    )
    op.create_index(
        op.f("ix_forecast_task_schedules_schedule_time"),
        "forecast_task_schedules",
        ["schedule_time"],
    )
    op.create_index(op.f("ix_forecast_task_schedules_state"), "forecast_task_schedules", ["state"])


def downgrade() -> None:
    op.drop_index(op.f("ix_forecast_task_schedules_state"), table_name="forecast_task_schedules")
    op.drop_index(
        op.f("ix_forecast_task_schedules_schedule_time"), table_name="forecast_task_schedules"
    )
    op.drop_index(
        op.f("ix_forecast_task_schedules_match_uuid"), table_name="forecast_task_schedules"
    )
    op.drop_table("forecast_task_schedules")
    postgresql.ENUM(name="forecast_task_state").drop(op.get_bind(), checkfirst=True)
