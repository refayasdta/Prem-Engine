"""add player context schema

Revision ID: 7bd3c8f2140a
Revises: 34c9735ae02e
Create Date: 2026-08-10 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7bd3c8f2140a"
down_revision: str | None = "34c9735ae02e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    availability_status = postgresql.ENUM(
        "available",
        "doubtful",
        "out",
        "suspended",
        "unknown",
        name="player_availability_status",
    )
    availability_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "observed_lineups",
        sa.Column("observed_lineup_uuid", sa.Uuid(), nullable=False),
        sa.Column("match_uuid", sa.Uuid(), nullable=False),
        sa.Column("club_uuid", sa.Uuid(), nullable=False),
        sa.Column("formation", sa.String(length=20), nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_payload_key", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
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
            ["match_uuid"],
            ["matches.match_uuid"],
            name=op.f("fk_observed_lineups_match_uuid_matches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["club_uuid"],
            ["clubs.club_uuid"],
            name=op.f("fk_observed_lineups_club_uuid_clubs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("observed_lineup_uuid", name=op.f("pk_observed_lineups")),
        sa.UniqueConstraint(
            "match_uuid",
            "club_uuid",
            "checksum",
            name=op.f("uq_observed_lineups_match_uuid"),
        ),
    )
    op.create_index("ix_observed_lineups_match_uuid", "observed_lineups", ["match_uuid"])
    op.create_index("ix_observed_lineups_club_uuid", "observed_lineups", ["club_uuid"])
    op.create_index("ix_observed_lineups_available_after", "observed_lineups", ["available_after"])

    op.create_table(
        "observed_lineup_players",
        sa.Column("observed_lineup_player_uuid", sa.Uuid(), nullable=False),
        sa.Column("observed_lineup_uuid", sa.Uuid(), nullable=False),
        sa.Column("player_uuid", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("slot", sa.SmallInteger(), nullable=False),
        sa.Column("position", sa.String(length=40), nullable=True),
        sa.Column("shirt_number", sa.SmallInteger(), nullable=True),
        sa.CheckConstraint(
            "role IN ('starter', 'substitute')",
            name=op.f("ck_observed_lineup_players_valid_role"),
        ),
        sa.CheckConstraint("slot > 0", name=op.f("ck_observed_lineup_players_positive_slot")),
        sa.ForeignKeyConstraint(
            ["observed_lineup_uuid"],
            ["observed_lineups.observed_lineup_uuid"],
            name=op.f("fk_observed_lineup_players_observed_lineup_uuid_observed_lineups"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["player_uuid"],
            ["players.player_uuid"],
            name=op.f("fk_observed_lineup_players_player_uuid_players"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "observed_lineup_player_uuid", name=op.f("pk_observed_lineup_players")
        ),
        sa.UniqueConstraint(
            "observed_lineup_uuid",
            "player_uuid",
            name=op.f("uq_observed_lineup_players_observed_lineup_uuid"),
        ),
        sa.UniqueConstraint(
            "observed_lineup_uuid",
            "role",
            "slot",
            name="uq_observed_lineup_players_role_slot",
        ),
    )
    op.create_index(
        "ix_observed_lineup_players_observed_lineup_uuid",
        "observed_lineup_players",
        ["observed_lineup_uuid"],
    )
    op.create_index(
        "ix_observed_lineup_players_player_uuid",
        "observed_lineup_players",
        ["player_uuid"],
    )

    op.create_table(
        "player_match_performances",
        sa.Column("player_match_performance_uuid", sa.Uuid(), nullable=False),
        sa.Column("match_uuid", sa.Uuid(), nullable=False),
        sa.Column("club_uuid", sa.Uuid(), nullable=False),
        sa.Column("player_uuid", sa.Uuid(), nullable=False),
        sa.Column("started", sa.Boolean(), nullable=False),
        sa.Column("position", sa.String(length=40), nullable=True),
        sa.Column("minutes", sa.SmallInteger(), nullable=True),
        sa.Column("rating", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column(
            "statistics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("available_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_payload_key", sa.Text(), nullable=False),
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
            "minutes IS NULL OR minutes BETWEEN 0 AND 130",
            name=op.f("ck_player_match_performances_valid_minutes"),
        ),
        sa.CheckConstraint(
            "rating IS NULL OR rating BETWEEN 0 AND 10",
            name=op.f("ck_player_match_performances_valid_rating"),
        ),
        sa.ForeignKeyConstraint(
            ["match_uuid"],
            ["matches.match_uuid"],
            name=op.f("fk_player_match_performances_match_uuid_matches"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["club_uuid"],
            ["clubs.club_uuid"],
            name=op.f("fk_player_match_performances_club_uuid_clubs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["player_uuid"],
            ["players.player_uuid"],
            name=op.f("fk_player_match_performances_player_uuid_players"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "player_match_performance_uuid", name=op.f("pk_player_match_performances")
        ),
        sa.UniqueConstraint(
            "match_uuid",
            "club_uuid",
            "player_uuid",
            name=op.f("uq_player_match_performances_match_uuid"),
        ),
    )
    op.create_index(
        "ix_player_match_performances_match_uuid", "player_match_performances", ["match_uuid"]
    )
    op.create_index(
        "ix_player_match_performances_club_uuid", "player_match_performances", ["club_uuid"]
    )
    op.create_index(
        "ix_player_match_performances_player_uuid", "player_match_performances", ["player_uuid"]
    )
    op.create_index(
        "ix_player_match_performances_available_after",
        "player_match_performances",
        ["available_after"],
    )

    op.create_table(
        "player_availability_reports",
        sa.Column("availability_report_uuid", sa.Uuid(), nullable=False),
        sa.Column("player_uuid", sa.Uuid(), nullable=False),
        sa.Column("club_uuid", sa.Uuid(), nullable=False),
        sa.Column("match_uuid", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "available",
                "doubtful",
                "out",
                "suspended",
                "unknown",
                name="player_availability_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=240), nullable=True),
        sa.Column("availability_probability", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_return_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_payload_key", sa.Text(), nullable=False),
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
            "availability_probability BETWEEN 0 AND 1",
            name=op.f("ck_player_availability_reports_valid_probability"),
        ),
        sa.ForeignKeyConstraint(
            ["player_uuid"],
            ["players.player_uuid"],
            name=op.f("fk_player_availability_reports_player_uuid_players"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["club_uuid"],
            ["clubs.club_uuid"],
            name=op.f("fk_player_availability_reports_club_uuid_clubs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["match_uuid"],
            ["matches.match_uuid"],
            name=op.f("fk_player_availability_reports_match_uuid_matches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "availability_report_uuid", name=op.f("pk_player_availability_reports")
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_payload_key",
            "player_uuid",
            "match_uuid",
            name="uq_player_availability_report_source",
        ),
    )
    op.create_index(
        "ix_player_availability_reports_player_uuid",
        "player_availability_reports",
        ["player_uuid"],
    )
    op.create_index(
        "ix_player_availability_reports_club_uuid",
        "player_availability_reports",
        ["club_uuid"],
    )
    op.create_index(
        "ix_player_availability_reports_match_uuid",
        "player_availability_reports",
        ["match_uuid"],
    )
    op.create_index(
        "ix_player_availability_reports_observed_at",
        "player_availability_reports",
        ["observed_at"],
    )

    op.create_table(
        "transfer_observations",
        sa.Column("transfer_observation_uuid", sa.Uuid(), nullable=False),
        sa.Column("player_uuid", sa.Uuid(), nullable=False),
        sa.Column("from_club_uuid", sa.Uuid(), nullable=True),
        sa.Column("to_club_uuid", sa.Uuid(), nullable=True),
        sa.Column("transfer_date", sa.Date(), nullable=False),
        sa.Column("transfer_type", sa.String(length=80), nullable=True),
        sa.Column("external_transfer_id", sa.String(length=120), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_payload_key", sa.Text(), nullable=False),
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
            "from_club_uuid IS NULL OR to_club_uuid IS NULL OR from_club_uuid <> to_club_uuid",
            name=op.f("ck_transfer_observations_different_clubs"),
        ),
        sa.ForeignKeyConstraint(
            ["player_uuid"],
            ["players.player_uuid"],
            name=op.f("fk_transfer_observations_player_uuid_players"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["from_club_uuid"],
            ["clubs.club_uuid"],
            name=op.f("fk_transfer_observations_from_club_uuid_clubs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_club_uuid"],
            ["clubs.club_uuid"],
            name=op.f("fk_transfer_observations_to_club_uuid_clubs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("transfer_observation_uuid", name=op.f("pk_transfer_observations")),
    )
    op.create_index(
        "ix_transfer_observations_player_uuid", "transfer_observations", ["player_uuid"]
    )
    op.create_index(
        "ix_transfer_observations_from_club_uuid",
        "transfer_observations",
        ["from_club_uuid"],
    )
    op.create_index(
        "ix_transfer_observations_to_club_uuid",
        "transfer_observations",
        ["to_club_uuid"],
    )
    op.create_index(
        "ix_transfer_observations_transfer_date", "transfer_observations", ["transfer_date"]
    )
    op.create_index(
        "ix_transfer_observations_observed_at", "transfer_observations", ["observed_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_transfer_observations_observed_at", table_name="transfer_observations")
    op.drop_index("ix_transfer_observations_transfer_date", table_name="transfer_observations")
    op.drop_index("ix_transfer_observations_to_club_uuid", table_name="transfer_observations")
    op.drop_index("ix_transfer_observations_from_club_uuid", table_name="transfer_observations")
    op.drop_index("ix_transfer_observations_player_uuid", table_name="transfer_observations")
    op.drop_table("transfer_observations")

    op.drop_index(
        "ix_player_availability_reports_observed_at",
        table_name="player_availability_reports",
    )
    op.drop_index(
        "ix_player_availability_reports_match_uuid",
        table_name="player_availability_reports",
    )
    op.drop_index(
        "ix_player_availability_reports_club_uuid",
        table_name="player_availability_reports",
    )
    op.drop_index(
        "ix_player_availability_reports_player_uuid",
        table_name="player_availability_reports",
    )
    op.drop_table("player_availability_reports")

    op.drop_index(
        "ix_player_match_performances_available_after",
        table_name="player_match_performances",
    )
    op.drop_index(
        "ix_player_match_performances_player_uuid",
        table_name="player_match_performances",
    )
    op.drop_index(
        "ix_player_match_performances_club_uuid",
        table_name="player_match_performances",
    )
    op.drop_index(
        "ix_player_match_performances_match_uuid",
        table_name="player_match_performances",
    )
    op.drop_table("player_match_performances")

    op.drop_index("ix_observed_lineup_players_player_uuid", table_name="observed_lineup_players")
    op.drop_index(
        "ix_observed_lineup_players_observed_lineup_uuid",
        table_name="observed_lineup_players",
    )
    op.drop_table("observed_lineup_players")
    op.drop_index("ix_observed_lineups_available_after", table_name="observed_lineups")
    op.drop_index("ix_observed_lineups_club_uuid", table_name="observed_lineups")
    op.drop_index("ix_observed_lineups_match_uuid", table_name="observed_lineups")
    op.drop_table("observed_lineups")
    postgresql.ENUM(name="player_availability_status").drop(op.get_bind(), checkfirst=True)
