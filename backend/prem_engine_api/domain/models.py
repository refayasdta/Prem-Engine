"""Relational core for identities, fixtures, forecasts, standings, and operations."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from prem_engine_api.db.base import Base, TimestampMixin
from prem_engine_api.domain.enums import (
    FixtureStatus,
    IdentityReviewState,
    IdentityReviewStatus,
    JobStatus,
    KickoffPrecision,
    PlayerAvailabilityStatus,
    PredictionState,
    ProviderRequestStatus,
    ResultKind,
    StandingsKind,
)


def enum_values(enum_class: type[Any]) -> list[str]:
    """Persist string-enum values rather than Python member names."""

    return [str(member.value) for member in enum_class]


class Competition(Base, TimestampMixin):
    __tablename__ = "competitions"

    competition_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    country_code: Mapped[str] = mapped_column(String(2))
    rules_version: Mapped[str] = mapped_column(String(40), default="premier-league-v1")


class CompetitionExternalReference(Base, TimestampMixin):
    __tablename__ = "competition_external_references"
    __table_args__ = (UniqueConstraint("provider", "external_competition_id"),)

    reference_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    competition_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("competitions.competition_uuid", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40))
    external_competition_id: Mapped[str] = mapped_column(String(120))
    observed_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Season(Base, TimestampMixin):
    __tablename__ = "seasons"
    __table_args__ = (
        UniqueConstraint("competition_uuid", "label"),
        CheckConstraint("end_date > start_date", name="date_order"),
    )

    season_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    competition_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("competitions.competition_uuid", ondelete="RESTRICT"), index=True
    )
    label: Mapped[str] = mapped_column(String(20))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)


class Club(Base, TimestampMixin):
    __tablename__ = "clubs"

    club_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    canonical_name: Mapped[str] = mapped_column(String(160), unique=True)
    short_name: Mapped[str] = mapped_column(String(80))
    crest_url: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ClubExternalReference(Base, TimestampMixin):
    __tablename__ = "club_external_references"
    __table_args__ = (UniqueConstraint("provider", "external_club_id"),)

    reference_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    club_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("clubs.club_uuid", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40))
    external_club_id: Mapped[str] = mapped_column(String(120))
    observed_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Player(Base, TimestampMixin):
    __tablename__ = "players"

    player_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    canonical_name: Mapped[str] = mapped_column(String(180), index=True)
    birth_date: Mapped[date | None] = mapped_column(Date)
    nationality_code: Mapped[str | None] = mapped_column(String(3))
    photo_url: Mapped[str | None] = mapped_column(Text)


class PlayerExternalReference(Base, TimestampMixin):
    __tablename__ = "player_external_references"
    __table_args__ = (UniqueConstraint("provider", "external_player_id"),)

    reference_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    player_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("players.player_uuid", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40))
    external_player_id: Mapped[str] = mapped_column(String(120))
    observed_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SeasonClub(Base, TimestampMixin):
    __tablename__ = "season_clubs"
    __table_args__ = (UniqueConstraint("season_uuid", "club_uuid"),)

    season_club_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    season_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("seasons.season_uuid", ondelete="CASCADE"), index=True
    )
    club_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("clubs.club_uuid", ondelete="RESTRICT"), index=True
    )


class SquadMembership(Base, TimestampMixin):
    __tablename__ = "squad_memberships"
    __table_args__ = (
        CheckConstraint("left_on IS NULL OR left_on >= joined_on", name="membership_date_order"),
    )

    membership_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    season_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("seasons.season_uuid", ondelete="CASCADE"), index=True
    )
    club_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("clubs.club_uuid", ondelete="RESTRICT"), index=True
    )
    player_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("players.player_uuid", ondelete="RESTRICT"), index=True
    )
    joined_on: Mapped[date] = mapped_column(Date)
    left_on: Mapped[date | None] = mapped_column(Date)
    shirt_number: Mapped[int | None] = mapped_column(SmallInteger)
    primary_position: Mapped[str | None] = mapped_column(String(40))


class ObservedLineup(Base, TimestampMixin):
    __tablename__ = "observed_lineups"
    __table_args__ = (
        UniqueConstraint("match_uuid", "club_uuid", "checksum"),
        Index("ix_observed_lineups_available_after", "available_after"),
    )

    observed_lineup_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    match_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("matches.match_uuid", ondelete="CASCADE"), index=True
    )
    club_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("clubs.club_uuid", ondelete="RESTRICT"), index=True
    )
    formation: Mapped[str | None] = mapped_column(String(20))
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    available_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(40))
    provider_payload_key: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64))


class ObservedLineupPlayer(Base):
    __tablename__ = "observed_lineup_players"
    __table_args__ = (
        UniqueConstraint("observed_lineup_uuid", "player_uuid"),
        UniqueConstraint(
            "observed_lineup_uuid",
            "role",
            "slot",
            name="uq_observed_lineup_players_role_slot",
        ),
        CheckConstraint("role IN ('starter', 'substitute')", name="valid_role"),
        CheckConstraint("slot > 0", name="positive_slot"),
    )

    observed_lineup_player_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    observed_lineup_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("observed_lineups.observed_lineup_uuid", ondelete="CASCADE"), index=True
    )
    player_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("players.player_uuid", ondelete="RESTRICT"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    slot: Mapped[int] = mapped_column(SmallInteger)
    position: Mapped[str | None] = mapped_column(String(40))
    shirt_number: Mapped[int | None] = mapped_column(SmallInteger)


class PlayerMatchPerformance(Base, TimestampMixin):
    __tablename__ = "player_match_performances"
    __table_args__ = (
        UniqueConstraint("match_uuid", "club_uuid", "player_uuid"),
        CheckConstraint("minutes IS NULL OR minutes BETWEEN 0 AND 130", name="valid_minutes"),
        CheckConstraint("rating IS NULL OR rating BETWEEN 0 AND 10", name="valid_rating"),
        CheckConstraint(
            "starting_status_source IN ('observed', 'inferred', 'unknown')",
            name="valid_starting_status_source",
        ),
        CheckConstraint(
            "(source_file_uuid IS NULL AND source_row_number IS NULL AND row_checksum IS NULL) "
            "OR (source_file_uuid IS NOT NULL AND source_row_number IS NOT NULL "
            "AND row_checksum IS NOT NULL)",
            name="complete_performance_provenance",
        ),
        UniqueConstraint("source_file_uuid", "source_row_number"),
        Index("ix_player_match_performances_available_after", "available_after"),
    )

    player_match_performance_uuid: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4
    )
    match_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("matches.match_uuid", ondelete="CASCADE"), index=True
    )
    club_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("clubs.club_uuid", ondelete="RESTRICT"), index=True
    )
    player_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("players.player_uuid", ondelete="RESTRICT"), index=True
    )
    started: Mapped[bool | None] = mapped_column(Boolean)
    starting_status_source: Mapped[str] = mapped_column(String(20), default="observed")
    position: Mapped[str | None] = mapped_column(String(40))
    minutes: Mapped[int | None] = mapped_column(SmallInteger)
    rating: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    statistics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    available_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(40), default="legacy")
    provider_payload_key: Mapped[str] = mapped_column(Text)
    source_file_uuid: Mapped[UUID | None] = mapped_column(
        ForeignKey("historical_source_files.source_file_uuid", ondelete="RESTRICT"), index=True
    )
    source_row_number: Mapped[int | None] = mapped_column(Integer)
    row_checksum: Mapped[str | None] = mapped_column(String(64))


class PlayerAvailabilityReport(Base, TimestampMixin):
    __tablename__ = "player_availability_reports"
    __table_args__ = (
        CheckConstraint("availability_probability BETWEEN 0 AND 1", name="valid_probability"),
        UniqueConstraint(
            "provider",
            "provider_payload_key",
            "player_uuid",
            "match_uuid",
            name="uq_player_availability_report_source",
        ),
        Index("ix_player_availability_reports_observed_at", "observed_at"),
    )

    availability_report_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    player_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("players.player_uuid", ondelete="RESTRICT"), index=True
    )
    club_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("clubs.club_uuid", ondelete="RESTRICT"), index=True
    )
    match_uuid: Mapped[UUID | None] = mapped_column(
        ForeignKey("matches.match_uuid", ondelete="CASCADE"), index=True
    )
    status: Mapped[PlayerAvailabilityStatus] = mapped_column(
        Enum(
            PlayerAvailabilityStatus,
            name="player_availability_status",
            values_callable=enum_values,
        )
    )
    reason: Mapped[str | None] = mapped_column(String(240))
    availability_probability: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_return_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(40))
    provider_payload_key: Mapped[str] = mapped_column(Text)


class TransferObservation(Base, TimestampMixin):
    __tablename__ = "transfer_observations"
    __table_args__ = (
        CheckConstraint(
            "from_club_uuid IS NULL OR to_club_uuid IS NULL OR from_club_uuid <> to_club_uuid",
            name="different_clubs",
        ),
        Index("ix_transfer_observations_transfer_date", "transfer_date"),
        Index("ix_transfer_observations_observed_at", "observed_at"),
    )

    transfer_observation_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    player_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("players.player_uuid", ondelete="RESTRICT"), index=True
    )
    from_club_uuid: Mapped[UUID | None] = mapped_column(
        ForeignKey("clubs.club_uuid", ondelete="RESTRICT"), index=True
    )
    to_club_uuid: Mapped[UUID | None] = mapped_column(
        ForeignKey("clubs.club_uuid", ondelete="RESTRICT"), index=True
    )
    transfer_date: Mapped[date] = mapped_column(Date)
    transfer_type: Mapped[str | None] = mapped_column(String(80))
    external_transfer_id: Mapped[str | None] = mapped_column(String(120))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(40))
    provider_payload_key: Mapped[str] = mapped_column(Text)


class Match(Base, TimestampMixin):
    __tablename__ = "matches"
    __table_args__ = (
        CheckConstraint("home_club_uuid <> away_club_uuid", name="different_clubs"),
        Index("ix_matches_season_kickoff", "season_uuid", "current_kickoff_at"),
    )

    match_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    season_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("seasons.season_uuid", ondelete="RESTRICT"), index=True
    )
    home_club_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("clubs.club_uuid", ondelete="RESTRICT"), index=True
    )
    away_club_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("clubs.club_uuid", ondelete="RESTRICT"), index=True
    )
    status: Mapped[FixtureStatus] = mapped_column(
        Enum(FixtureStatus, name="fixture_status", values_callable=enum_values),
        default=FixtureStatus.SCHEDULED,
    )
    identity_review_state: Mapped[IdentityReviewState] = mapped_column(
        Enum(IdentityReviewState, name="identity_review_state", values_callable=enum_values),
        default=IdentityReviewState.RESOLVED,
    )
    current_kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kickoff_precision: Mapped[KickoffPrecision] = mapped_column(
        Enum(KickoffPrecision, name="kickoff_precision", values_callable=enum_values),
        default=KickoffPrecision.EXACT,
    )
    prediction_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class MatchExternalReference(Base, TimestampMixin):
    __tablename__ = "match_external_references"
    __table_args__ = (UniqueConstraint("provider", "external_fixture_id"),)

    reference_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    match_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("matches.match_uuid", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40))
    external_fixture_id: Mapped[str] = mapped_column(String(120))
    observed_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FixtureScheduleRevision(Base):
    __tablename__ = "fixture_schedule_revisions"
    __table_args__ = (
        UniqueConstraint("match_uuid", "revision_number"),
        Index(
            "uq_fixture_schedule_current",
            "match_uuid",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )

    revision_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    match_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("matches.match_uuid", ondelete="CASCADE"), index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    canonical_status: Mapped[FixtureStatus] = mapped_column(
        Enum(FixtureStatus, name="fixture_status", values_callable=enum_values)
    )
    provider_status: Mapped[str | None] = mapped_column(String(80))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActualResultRevision(Base, TimestampMixin):
    __tablename__ = "actual_result_revisions"
    __table_args__ = (
        UniqueConstraint("match_uuid", "revision_number"),
        CheckConstraint("home_goals >= 0 AND away_goals >= 0", name="nonnegative_score"),
        Index(
            "uq_actual_result_accepted",
            "match_uuid",
            unique=True,
            postgresql_where=text("accepted IS TRUE"),
        ),
    )

    actual_result_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    match_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("matches.match_uuid", ondelete="CASCADE"), index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    home_goals: Mapped[int] = mapped_column(SmallInteger)
    away_goals: Mapped[int] = mapped_column(SmallInteger)
    result_kind: Mapped[ResultKind] = mapped_column(
        Enum(ResultKind, name="result_kind", values_callable=enum_values),
        default=ResultKind.REGULAR,
    )
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    provider_payload_key: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PredictionVersion(Base, TimestampMixin):
    __tablename__ = "prediction_versions"
    __table_args__ = (
        UniqueConstraint("match_uuid", "version_number"),
        CheckConstraint(
            "home_win_probability >= 0 AND draw_probability >= 0 AND away_win_probability >= 0",
            name="nonnegative_probabilities",
        ),
        CheckConstraint(
            "home_win_probability + draw_probability + away_win_probability "
            "BETWEEN 0.999999 AND 1.000001",
            name="probability_sum",
        ),
        CheckConstraint(
            "expected_home_goals >= 0 AND expected_away_goals >= 0", name="nonnegative_xg"
        ),
        Index(
            "uq_prediction_versions_active_match",
            "match_uuid",
            unique=True,
            postgresql_where=text("state IN ('active_locked', 'evaluated')"),
        ),
    )

    prediction_version_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    match_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("matches.match_uuid", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    state: Mapped[PredictionState] = mapped_column(
        Enum(PredictionState, name="prediction_state", values_callable=enum_values), index=True
    )
    feature_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model_version: Mapped[str] = mapped_column(String(120))
    feature_snapshot_checksum: Mapped[str] = mapped_column(String(64))
    home_win_probability: Mapped[Decimal] = mapped_column(Numeric(9, 8))
    draw_probability: Mapped[Decimal] = mapped_column(Numeric(9, 8))
    away_win_probability: Mapped[Decimal] = mapped_column(Numeric(9, 8))
    expected_home_goals: Mapped[Decimal] = mapped_column(Numeric(7, 4))
    expected_away_goals: Mapped[Decimal] = mapped_column(Numeric(7, 4))
    statistics_distribution: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(String(120))


class PredictedLineup(Base):
    __tablename__ = "predicted_lineups"

    predicted_lineup_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    prediction_version_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("prediction_versions.prediction_version_uuid", ondelete="CASCADE"), unique=True
    )
    formation: Mapped[str] = mapped_column(String(20))
    lineup_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    checksum: Mapped[str] = mapped_column(String(64))


class StoredSimulation(Base):
    __tablename__ = "stored_simulations"
    __table_args__ = (
        CheckConstraint("home_goals >= 0 AND away_goals >= 0", name="nonnegative_score"),
    )

    simulation_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    prediction_version_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("prediction_versions.prediction_version_uuid", ondelete="CASCADE"), unique=True
    )
    random_seed: Mapped[int] = mapped_column(Integer)
    home_goals: Mapped[int] = mapped_column(SmallInteger)
    away_goals: Mapped[int] = mapped_column(SmallInteger)
    statistics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    events: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    checksum: Mapped[str] = mapped_column(String(64))


class StandingsSnapshot(Base):
    __tablename__ = "standings_snapshots"
    __table_args__ = (UniqueConstraint("season_uuid", "kind", "as_of"),)

    snapshot_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    season_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("seasons.season_uuid", ondelete="CASCADE"), index=True
    )
    kind: Mapped[StandingsKind] = mapped_column(
        Enum(StandingsKind, name="standings_kind", values_callable=enum_values)
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    calculation_version: Mapped[str] = mapped_column(String(80))
    source_fixture_count: Mapped[int] = mapped_column(Integer)


class StandingsRow(Base):
    __tablename__ = "standings_rows"
    __table_args__ = (
        UniqueConstraint("snapshot_uuid", "club_uuid", name="uq_standings_rows_snapshot_club"),
        UniqueConstraint("snapshot_uuid", "position", name="uq_standings_rows_snapshot_position"),
        CheckConstraint("position > 0 AND played >= 0 AND points >= 0", name="valid_totals"),
        CheckConstraint("won + drawn + lost = played", name="result_total"),
    )

    standings_row_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    snapshot_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("standings_snapshots.snapshot_uuid", ondelete="CASCADE"), index=True
    )
    club_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("clubs.club_uuid", ondelete="RESTRICT"), index=True
    )
    position: Mapped[int] = mapped_column(SmallInteger)
    played: Mapped[int] = mapped_column(SmallInteger)
    won: Mapped[int] = mapped_column(SmallInteger)
    drawn: Mapped[int] = mapped_column(SmallInteger)
    lost: Mapped[int] = mapped_column(SmallInteger)
    goals_for: Mapped[int] = mapped_column(SmallInteger)
    goals_against: Mapped[int] = mapped_column(SmallInteger)
    goal_difference: Mapped[int] = mapped_column(SmallInteger)
    points: Mapped[int] = mapped_column(SmallInteger)


class RawFetch(Base):
    __tablename__ = "raw_fetches"

    raw_fetch_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider_request_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("provider_requests.provider_request_uuid", ondelete="RESTRICT"), unique=True
    )
    provider: Mapped[str] = mapped_column(String(40), index=True)
    endpoint: Mapped[str] = mapped_column(String(240))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    response_status: Mapped[int] = mapped_column(SmallInteger)
    response_checksum: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(Text, unique=True)
    schema_version: Mapped[str] = mapped_column(String(40))


class ProviderRequestBudget(Base, TimestampMixin):
    __tablename__ = "provider_request_budgets"
    __table_args__ = (
        UniqueConstraint("provider", "budget_date"),
        CheckConstraint(
            "request_count >= 0 AND operational_limit > 0 "
            "AND hard_limit >= operational_limit AND request_count <= hard_limit",
            name="valid_budget",
        ),
    )

    budget_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(40))
    budget_date: Mapped[date] = mapped_column(Date)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    operational_limit: Mapped[int] = mapped_column(Integer, default=85)
    hard_limit: Mapped[int] = mapped_column(Integer, default=100)


class ProviderRequest(Base):
    __tablename__ = "provider_requests"

    provider_request_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    endpoint: Mapped[str] = mapped_column(String(240))
    query_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[ProviderRequestStatus] = mapped_column(
        Enum(ProviderRequestStatus, name="provider_request_status", values_callable=enum_values),
        index=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_status: Mapped[int | None] = mapped_column(SmallInteger)
    rate_limit: Mapped[int | None] = mapped_column(Integer)
    rate_remaining: Mapped[int | None] = mapped_column(Integer)
    rate_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_request_id: Mapped[str | None] = mapped_column(String(160))
    error_code: Mapped[str | None] = mapped_column(String(120))


class IdentityReviewCase(Base, TimestampMixin):
    __tablename__ = "identity_review_cases"
    __table_args__ = (
        Index(
            "uq_identity_review_pending_external",
            "entity_type",
            "provider",
            "external_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    review_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    entity_type: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(40))
    external_id: Mapped[str] = mapped_column(String(120))
    status: Mapped[IdentityReviewStatus] = mapped_column(
        Enum(IdentityReviewStatus, name="identity_review_status", values_callable=enum_values),
        default=IdentityReviewStatus.PENDING,
        index=True,
    )
    provider_name: Mapped[str | None] = mapped_column(String(180))
    candidate_uuids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    resolved_uuid: Mapped[UUID | None] = mapped_column(Uuid)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class HistoricalSourceFile(Base, TimestampMixin):
    __tablename__ = "historical_source_files"
    __table_args__ = (
        UniqueConstraint("provider", "source_url", "response_checksum"),
        CheckConstraint("row_count >= 0", name="nonnegative_row_count"),
    )

    source_file_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    competition_code: Mapped[str] = mapped_column(String(20))
    season_label: Mapped[str] = mapped_column(String(20), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    response_checksum: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(Text, unique=True)
    schema_fingerprint: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(Integer, default=0)


class ClubAlias(Base, TimestampMixin):
    __tablename__ = "club_aliases"
    __table_args__ = (UniqueConstraint("provider", "normalized_alias"),)

    alias_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    club_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("clubs.club_uuid", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40))
    alias: Mapped[str] = mapped_column(String(160))
    normalized_alias: Mapped[str] = mapped_column(String(160))
    reviewed_by: Mapped[str] = mapped_column(String(120))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class HistoricalMatchRecord(Base, TimestampMixin):
    __tablename__ = "historical_match_records"
    __table_args__ = (
        UniqueConstraint("source_file_uuid", "source_row_number"),
        CheckConstraint("source_row_number > 1", name="valid_source_row_number"),
        CheckConstraint(
            "half_time_home_goals IS NULL OR half_time_home_goals >= 0",
            name="nonnegative_half_time_home_goals",
        ),
        CheckConstraint(
            "half_time_away_goals IS NULL OR half_time_away_goals >= 0",
            name="nonnegative_half_time_away_goals",
        ),
    )

    historical_match_record_uuid: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4
    )
    source_file_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("historical_source_files.source_file_uuid", ondelete="RESTRICT"), index=True
    )
    match_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("matches.match_uuid", ondelete="CASCADE"), index=True
    )
    source_row_number: Mapped[int] = mapped_column(Integer)
    row_checksum: Mapped[str] = mapped_column(String(64))
    available_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    half_time_home_goals: Mapped[int | None] = mapped_column(SmallInteger)
    half_time_away_goals: Mapped[int | None] = mapped_column(SmallInteger)
    referee: Mapped[str | None] = mapped_column(String(160))
    statistics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    benchmark_odds: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    odds_timing: Mapped[str] = mapped_column(String(40), default="mixed_or_unknown")
    odds_training_eligible: Mapped[bool] = mapped_column(Boolean, default=False)


class JobRun(Base, TimestampMixin):
    __tablename__ = "job_runs"
    __table_args__ = (CheckConstraint("attempt_count >= 0", name="nonnegative_attempts"),)

    job_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(240), unique=True)
    job_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", values_callable=enum_values), index=True
    )
    match_uuid: Mapped[UUID | None] = mapped_column(
        ForeignKey("matches.match_uuid", ondelete="CASCADE"), index=True
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lease_owner: Mapped[str | None] = mapped_column(String(160))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(120))


class LifecycleEvent(Base):
    __tablename__ = "lifecycle_events"

    event_uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    aggregate_type: Mapped[str] = mapped_column(String(60), index=True)
    aggregate_uuid: Mapped[UUID] = mapped_column(Uuid, index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actor: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
