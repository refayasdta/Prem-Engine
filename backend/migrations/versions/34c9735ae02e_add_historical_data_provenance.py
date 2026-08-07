"""add historical data provenance

Revision ID: 34c9735ae02e
Revises: 43a723a183f9
Create Date: 2026-08-07 14:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "34c9735ae02e"
down_revision: str | None = "43a723a183f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    kickoff_precision = postgresql.ENUM("exact", "date_only", name="kickoff_precision")
    kickoff_precision.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "matches",
        sa.Column(
            "kickoff_precision",
            sa.Enum("exact", "date_only", name="kickoff_precision"),
            server_default="exact",
            nullable=False,
        ),
    )
    op.alter_column("matches", "kickoff_precision", server_default=None)

    op.create_table(
        "historical_source_files",
        sa.Column("source_file_uuid", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("competition_code", sa.String(length=20), nullable=False),
        sa.Column("season_label", sa.String(length=20), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_checksum", sa.String(length=64), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "row_count >= 0", name=op.f("ck_historical_source_files_nonnegative_row_count")
        ),
        sa.PrimaryKeyConstraint("source_file_uuid", name="pk_historical_source_files"),
        sa.UniqueConstraint("object_key", name="uq_historical_source_files_object_key"),
        sa.UniqueConstraint(
            "provider",
            "source_url",
            "response_checksum",
            name="uq_historical_source_files_provider",
        ),
    )
    op.create_index("ix_historical_source_files_provider", "historical_source_files", ["provider"])
    op.create_index(
        "ix_historical_source_files_season_label", "historical_source_files", ["season_label"]
    )

    op.create_table(
        "club_aliases",
        sa.Column("alias_uuid", sa.Uuid(), nullable=False),
        sa.Column("club_uuid", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("alias", sa.String(length=160), nullable=False),
        sa.Column("normalized_alias", sa.String(length=160), nullable=False),
        sa.Column("reviewed_by", sa.String(length=120), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["club_uuid"],
            ["clubs.club_uuid"],
            name="fk_club_aliases_club_uuid_clubs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("alias_uuid", name="pk_club_aliases"),
        sa.UniqueConstraint("provider", "normalized_alias", name="uq_club_aliases_provider"),
    )
    op.create_index("ix_club_aliases_club_uuid", "club_aliases", ["club_uuid"])

    op.create_table(
        "historical_match_records",
        sa.Column("historical_match_record_uuid", sa.Uuid(), nullable=False),
        sa.Column("source_file_uuid", sa.Uuid(), nullable=False),
        sa.Column("match_uuid", sa.Uuid(), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("row_checksum", sa.String(length=64), nullable=False),
        sa.Column("available_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("half_time_home_goals", sa.SmallInteger(), nullable=True),
        sa.Column("half_time_away_goals", sa.SmallInteger(), nullable=True),
        sa.Column("referee", sa.String(length=160), nullable=True),
        sa.Column("statistics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("benchmark_odds", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("odds_timing", sa.String(length=40), nullable=False),
        sa.Column("odds_training_eligible", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "half_time_away_goals IS NULL OR half_time_away_goals >= 0",
            name=op.f("ck_historical_match_records_nonnegative_half_time_away_goals"),
        ),
        sa.CheckConstraint(
            "half_time_home_goals IS NULL OR half_time_home_goals >= 0",
            name=op.f("ck_historical_match_records_nonnegative_half_time_home_goals"),
        ),
        sa.CheckConstraint(
            "source_row_number > 1",
            name=op.f("ck_historical_match_records_valid_source_row_number"),
        ),
        sa.ForeignKeyConstraint(
            ["match_uuid"],
            ["matches.match_uuid"],
            name="fk_historical_match_records_match_uuid_matches",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_file_uuid"],
            ["historical_source_files.source_file_uuid"],
            name="fk_hist_records_source_file",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("historical_match_record_uuid", name="pk_historical_match_records"),
        sa.UniqueConstraint(
            "source_file_uuid",
            "source_row_number",
            name="uq_historical_match_records_source_file_uuid",
        ),
    )
    op.create_index(
        "ix_historical_match_records_available_after",
        "historical_match_records",
        ["available_after"],
    )
    op.create_index(
        "ix_historical_match_records_match_uuid", "historical_match_records", ["match_uuid"]
    )
    op.create_index(
        "ix_historical_match_records_source_file_uuid",
        "historical_match_records",
        ["source_file_uuid"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_historical_match_records_source_file_uuid", table_name="historical_match_records"
    )
    op.drop_index("ix_historical_match_records_match_uuid", table_name="historical_match_records")
    op.drop_index(
        "ix_historical_match_records_available_after", table_name="historical_match_records"
    )
    op.drop_table("historical_match_records")
    op.drop_index("ix_club_aliases_club_uuid", table_name="club_aliases")
    op.drop_table("club_aliases")
    op.drop_index("ix_historical_source_files_season_label", table_name="historical_source_files")
    op.drop_index("ix_historical_source_files_provider", table_name="historical_source_files")
    op.drop_table("historical_source_files")
    op.drop_column("matches", "kickoff_precision")
    postgresql.ENUM(name="kickoff_precision").drop(op.get_bind(), checkfirst=True)
