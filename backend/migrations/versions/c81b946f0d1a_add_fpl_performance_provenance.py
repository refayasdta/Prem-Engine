"""add FPL player-performance provenance

Revision ID: c81b946f0d1a
Revises: 7bd3c8f2140a
Create Date: 2026-08-10 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c81b946f0d1a"
down_revision: str | None = "7bd3c8f2140a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "player_match_performances",
        "started",
        existing_type=sa.Boolean(),
        nullable=True,
    )
    op.add_column(
        "player_match_performances",
        sa.Column(
            "starting_status_source",
            sa.String(length=20),
            server_default="observed",
            nullable=False,
        ),
    )
    op.add_column(
        "player_match_performances",
        sa.Column("provider", sa.String(length=40), server_default="legacy", nullable=False),
    )
    op.add_column(
        "player_match_performances",
        sa.Column("source_file_uuid", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "player_match_performances",
        sa.Column("source_row_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "player_match_performances",
        sa.Column("row_checksum", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_player_match_performances_source_file_uuid_historical_source_files"),
        "player_match_performances",
        "historical_source_files",
        ["source_file_uuid"],
        ["source_file_uuid"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_player_match_performances_source_file_uuid",
        "player_match_performances",
        ["source_file_uuid"],
    )
    op.create_unique_constraint(
        op.f("uq_player_match_performances_source_file_uuid"),
        "player_match_performances",
        ["source_file_uuid", "source_row_number"],
    )
    op.create_check_constraint(
        op.f("ck_player_match_performances_valid_starting_status_source"),
        "player_match_performances",
        "starting_status_source IN ('observed', 'inferred', 'unknown')",
    )
    op.create_check_constraint(
        op.f("ck_player_match_performances_complete_performance_provenance"),
        "player_match_performances",
        "(source_file_uuid IS NULL AND source_row_number IS NULL AND row_checksum IS NULL) "
        "OR (source_file_uuid IS NOT NULL AND source_row_number IS NOT NULL "
        "AND row_checksum IS NOT NULL)",
    )
    op.alter_column(
        "player_match_performances",
        "starting_status_source",
        server_default=None,
    )
    op.alter_column("player_match_performances", "provider", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_player_match_performances_complete_performance_provenance"),
        "player_match_performances",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_player_match_performances_valid_starting_status_source"),
        "player_match_performances",
        type_="check",
    )
    op.drop_constraint(
        op.f("uq_player_match_performances_source_file_uuid"),
        "player_match_performances",
        type_="unique",
    )
    op.drop_index(
        "ix_player_match_performances_source_file_uuid",
        table_name="player_match_performances",
    )
    op.drop_constraint(
        op.f("fk_player_match_performances_source_file_uuid_historical_source_files"),
        "player_match_performances",
        type_="foreignkey",
    )
    op.drop_column("player_match_performances", "row_checksum")
    op.drop_column("player_match_performances", "source_row_number")
    op.drop_column("player_match_performances", "source_file_uuid")
    op.drop_column("player_match_performances", "provider")
    op.drop_column("player_match_performances", "starting_status_source")
    op.execute("UPDATE player_match_performances SET started = FALSE WHERE started IS NULL")
    op.alter_column(
        "player_match_performances",
        "started",
        existing_type=sa.Boolean(),
        nullable=False,
    )
