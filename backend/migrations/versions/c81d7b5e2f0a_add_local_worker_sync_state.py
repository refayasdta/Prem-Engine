"""add local worker synchronization state

Revision ID: c81d7b5e2f0a
Revises: a6f2c9d4137b
Create Date: 2026-08-14 10:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c81d7b5e2f0a"
down_revision: str | None = "a6f2c9d4137b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("provider_round", sa.String(length=80), nullable=True))
    op.add_column("matches", sa.Column("matchweek", sa.SmallInteger(), nullable=True))
    op.create_index(op.f("ix_matches_matchweek"), "matches", ["matchweek"], unique=False)
    op.create_check_constraint(
        op.f("ck_matches_valid_matchweek"),
        "matches",
        "matchweek IS NULL OR matchweek BETWEEN 1 AND 60",
    )
    op.create_table(
        "local_worker_state",
        sa.Column("worker_state_uuid", sa.Uuid(), nullable=False),
        sa.Column("singleton_key", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_operation", sa.String(length=80), nullable=True),
        sa.Column("lease_owner", sa.String(length=160), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fixture_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fixture_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_full_fixture_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_fixture_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_player_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_player_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=120), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pages_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_unchanged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_pending_review", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "pages_processed >= 0 AND records_received >= 0 AND records_created >= 0 "
            "AND records_updated >= 0 AND records_unchanged >= 0 "
            "AND records_pending_review >= 0",
            name=op.f("ck_local_worker_state_nonnegative_progress"),
        ),
        sa.CheckConstraint(
            "status IN ('idle', 'syncing', 'setup_required', 'error', 'quota_limited')",
            name=op.f("ck_local_worker_state_valid_status"),
        ),
        sa.CheckConstraint(
            "singleton_key = 1", name=op.f("ck_local_worker_state_singleton_key_is_one")
        ),
        sa.PrimaryKeyConstraint("worker_state_uuid"),
        sa.UniqueConstraint("singleton_key"),
    )


def downgrade() -> None:
    op.drop_table("local_worker_state")
    op.drop_constraint(op.f("ck_matches_valid_matchweek"), "matches", type_="check")
    op.drop_index(op.f("ix_matches_matchweek"), table_name="matches")
    op.drop_column("matches", "matchweek")
    op.drop_column("matches", "provider_round")
