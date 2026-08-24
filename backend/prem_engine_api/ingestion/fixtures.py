"""Normalize KickoffAPI fixture responses into canonical identities and revisions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from prem_engine_modeling.goals import normalize_club_identity
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from prem_engine_api.domain.enums import (
    FixtureStatus,
    IdentityReviewStatus,
    PredictionState,
    ResultKind,
)
from prem_engine_api.domain.lifecycle import cancel_match, postpone_match, reschedule_match
from prem_engine_api.domain.models import (
    ActualResultRevision,
    Club,
    ClubExternalReference,
    Competition,
    CompetitionExternalReference,
    FixtureScheduleRevision,
    IdentityReviewCase,
    Match,
    MatchExternalReference,
    PredictionVersion,
    Season,
    SeasonClub,
)
from prem_engine_api.providers.kickoffapi.contracts import (
    FixtureEnvelope,
    ProviderFixture,
    ProviderLeague,
    ProviderTeam,
)
from prem_engine_api.providers.kickoffapi.status import map_fixture_status

PROVIDER = "kickoffapi"
MATCH_TOLERANCE = timedelta(hours=48)
MATCHWEEK_PATTERN = re.compile(r"(?:matchday|matchweek|round)\s*-?\s*(\d+)", re.IGNORECASE)


def matchweek_from_round(round_label: str | None) -> int | None:
    """Extract an explicit positive matchweek without guessing from kickoff order."""

    if round_label is None:
        return None
    match = MATCHWEEK_PATTERN.search(round_label.strip())
    if match is None:
        return None
    value = int(match.group(1))
    return value if 1 <= value <= 60 else None


@dataclass(frozen=True)
class FixtureIngestionSummary:
    received: int
    created: int
    updated: int
    unchanged: int
    pending_review: int


class FixtureIngestor:
    """Idempotently ingest one provider envelope within the caller's transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ingest(
        self, payload: object, *, observed_at: datetime | None = None
    ) -> FixtureIngestionSummary:
        envelope = FixtureEnvelope.model_validate(payload)
        effective_observed_at = observed_at or datetime.now(UTC)
        created = 0
        updated = 0
        unchanged = 0
        pending_review = 0
        for fixture in envelope.data:
            result = await self._ingest_fixture(fixture, observed_at=effective_observed_at)
            if result == "created":
                created += 1
            elif result == "updated":
                updated += 1
            elif result == "pending_review":
                pending_review += 1
            else:
                unchanged += 1
        return FixtureIngestionSummary(
            received=len(envelope.data),
            created=created,
            updated=updated,
            unchanged=unchanged,
            pending_review=pending_review,
        )

    async def _ingest_fixture(self, fixture: ProviderFixture, *, observed_at: datetime) -> str:
        competition = await self._resolve_competition(fixture.league, observed_at)
        home = await self._resolve_club(fixture.normalized_home, observed_at)
        away = await self._resolve_club(fixture.normalized_away, observed_at)
        if competition is None or home is None or away is None:
            return "pending_review"
        season = await self._resolve_season(competition, fixture.league)
        await self._ensure_season_clubs(season, home, away)
        external_reference = await self._session.scalar(
            select(MatchExternalReference).where(
                MatchExternalReference.provider == PROVIDER,
                MatchExternalReference.external_fixture_id == fixture.id,
            )
        )
        canonical_status = map_fixture_status(fixture.status_code)
        provider_matchweek = matchweek_from_round(fixture.round)
        if external_reference is None:
            match = await self._match_by_identity(
                fixture=fixture,
                season=season,
                home=home,
                away=away,
                observed_at=observed_at,
            )
            if match is None:
                return "pending_review"
            was_created = match.match_uuid is None
            if was_created:
                self._session.add(match)
                await self._session.flush()
                self._session.add(
                    FixtureScheduleRevision(
                        match_uuid=match.match_uuid,
                        revision_number=1,
                        kickoff_at=fixture.date,
                        canonical_status=canonical_status,
                        provider_status=fixture.status_code,
                        observed_at=observed_at,
                    )
                )
            self._session.add(
                MatchExternalReference(
                    match_uuid=match.match_uuid,
                    provider=PROVIDER,
                    external_fixture_id=fixture.id,
                    observed_from=observed_at,
                )
            )
            await self._upsert_actual_result(match, fixture, observed_at)
            match.provider_round = fixture.round
            match.matchweek = provider_matchweek
            await self._session.flush()
            return "created" if was_created else "updated"

        match = await self._session.get(Match, external_reference.match_uuid)
        if match is None:
            raise RuntimeError("match external reference points to a missing match")
        changed = False
        if fixture.round is not None and (
            match.provider_round != fixture.round or match.matchweek != provider_matchweek
        ):
            match.provider_round = fixture.round
            match.matchweek = provider_matchweek
            changed = True
        if canonical_status is FixtureStatus.POSTPONED:
            was_postponed = match.status is FixtureStatus.POSTPONED
            await postpone_match(
                self._session,
                match_uuid=match.match_uuid,
                provider_status=fixture.status_code,
                actor="kickoffapi-ingestion",
                observed_at=observed_at,
            )
            changed = not was_postponed
        elif canonical_status is FixtureStatus.CANCELLED:
            was_cancelled = match.status is FixtureStatus.CANCELLED
            await cancel_match(
                self._session,
                match_uuid=match.match_uuid,
                provider_status=fixture.status_code,
                actor="kickoffapi-ingestion",
                observed_at=observed_at,
            )
            changed = not was_cancelled
        elif fixture.date != match.current_kickoff_at:
            outcome = await reschedule_match(
                self._session,
                match_uuid=match.match_uuid,
                revised_kickoff_at=fixture.date,
                provider_status=fixture.status_code,
                actor="kickoffapi-ingestion",
                observed_at=observed_at,
            )
            revision = await self._session.get(FixtureScheduleRevision, outcome.revision_uuid)
            if revision is not None:
                revision.canonical_status = canonical_status
            match.status = canonical_status
            changed = True
        elif match.status is not canonical_status:
            await self._append_status_revision(
                match, canonical_status, fixture.status_code, observed_at
            )
            match.status = canonical_status
            changed = True
        if await self._upsert_actual_result(match, fixture, observed_at):
            changed = True
        await self._session.flush()
        return "updated" if changed else "unchanged"

    async def _resolve_competition(
        self, league: ProviderLeague, observed_at: datetime
    ) -> Competition | None:
        reference = await self._session.scalar(
            select(CompetitionExternalReference).where(
                CompetitionExternalReference.provider == PROVIDER,
                CompetitionExternalReference.external_competition_id == league.id,
            )
        )
        if reference is not None:
            return await self._session.get(Competition, reference.competition_uuid)
        matches = list(
            await self._session.scalars(
                select(Competition).where(func.lower(Competition.name) == league.name.casefold())
            )
        )
        if len(matches) > 1:
            await self._queue_review(
                entity_type="competition",
                external_id=league.id,
                provider_name=league.name,
                candidate_uuids=[competition.competition_uuid for competition in matches],
            )
            return None
        if matches:
            competition = matches[0]
        else:
            slug = re.sub(r"[^a-z0-9]+", "-", league.name.casefold()).strip("-")
            competition = Competition(
                slug=f"{slug}-{league.id.casefold()}",
                name=league.name,
                country_code="GB" if league.country == "England" else "ZZ",
            )
            self._session.add(competition)
            await self._session.flush()
        self._session.add(
            CompetitionExternalReference(
                competition_uuid=competition.competition_uuid,
                provider=PROVIDER,
                external_competition_id=league.id,
                observed_from=observed_at,
            )
        )
        return competition

    async def _resolve_club(self, team: ProviderTeam, observed_at: datetime) -> Club | None:
        reference = await self._session.scalar(
            select(ClubExternalReference).where(
                ClubExternalReference.provider == PROVIDER,
                ClubExternalReference.external_club_id == team.id,
            )
        )
        if reference is not None:
            return await self._session.get(Club, reference.club_uuid)
        matches = list(
            await self._session.scalars(
                select(Club).where(func.lower(Club.canonical_name) == team.name.casefold())
            )
        )
        if not matches:
            identity = normalize_club_identity(team.name)
            matches = [
                club
                for club in await self._session.scalars(select(Club))
                if normalize_club_identity(club.canonical_name) == identity
            ]
        if len(matches) > 1:
            await self._queue_review(
                entity_type="club",
                external_id=team.id,
                provider_name=team.name,
                candidate_uuids=[club.club_uuid for club in matches],
            )
            return None
        if matches:
            club = matches[0]
        else:
            club = Club(
                canonical_name=team.name,
                short_name=team.name[:80],
                crest_url=team.logo,
            )
            self._session.add(club)
            await self._session.flush()
        self._session.add(
            ClubExternalReference(
                club_uuid=club.club_uuid,
                provider=PROVIDER,
                external_club_id=team.id,
                observed_from=observed_at,
            )
        )
        return club

    async def _resolve_season(self, competition: Competition, league: ProviderLeague) -> Season:
        season_year = league.season or datetime.now(UTC).year
        label = f"{season_year}/{str(season_year + 1)[-2:]}"
        season = await self._session.scalar(
            select(Season).where(
                Season.competition_uuid == competition.competition_uuid,
                Season.label == label,
            )
        )
        if season is None:
            season = Season(
                competition_uuid=competition.competition_uuid,
                label=label,
                start_date=date(season_year, 7, 1),
                end_date=date(season_year + 1, 6, 30),
            )
            self._session.add(season)
            await self._session.flush()
        return season

    async def _ensure_season_clubs(self, season: Season, home: Club, away: Club) -> None:
        existing_club_uuids = set(
            await self._session.scalars(
                select(SeasonClub.club_uuid).where(
                    SeasonClub.season_uuid == season.season_uuid,
                    SeasonClub.club_uuid.in_((home.club_uuid, away.club_uuid)),
                )
            )
        )
        self._session.add_all(
            SeasonClub(season_uuid=season.season_uuid, club_uuid=club.club_uuid)
            for club in (home, away)
            if club.club_uuid not in existing_club_uuids
        )
        await self._session.flush()

    async def _match_by_identity(
        self,
        *,
        fixture: ProviderFixture,
        season: Season,
        home: Club,
        away: Club,
        observed_at: datetime,
    ) -> Match | None:
        candidates = list(
            await self._session.scalars(
                select(Match).where(
                    Match.season_uuid == season.season_uuid,
                    Match.home_club_uuid == home.club_uuid,
                    Match.away_club_uuid == away.club_uuid,
                    Match.current_kickoff_at.between(
                        fixture.date - MATCH_TOLERANCE, fixture.date + MATCH_TOLERANCE
                    ),
                )
            )
        )
        if len(candidates) > 1:
            await self._queue_review(
                entity_type="match",
                external_id=fixture.id,
                provider_name=None,
                candidate_uuids=[candidate.match_uuid for candidate in candidates],
                evidence={
                    "kickoff_at": fixture.date.isoformat(),
                    "observed_at": observed_at.isoformat(),
                },
            )
            return None
        if candidates:
            return candidates[0]
        return Match(
            season_uuid=season.season_uuid,
            home_club_uuid=home.club_uuid,
            away_club_uuid=away.club_uuid,
            status=map_fixture_status(fixture.status_code),
            current_kickoff_at=fixture.date,
            prediction_due_at=fixture.date - timedelta(hours=24),
            provider_round=fixture.round,
            matchweek=matchweek_from_round(fixture.round),
        )

    async def _queue_review(
        self,
        *,
        entity_type: str,
        external_id: str,
        provider_name: str | None,
        candidate_uuids: list[UUID],
        evidence: dict[str, str] | None = None,
    ) -> None:
        existing = await self._session.scalar(
            select(IdentityReviewCase).where(
                IdentityReviewCase.entity_type == entity_type,
                IdentityReviewCase.provider == PROVIDER,
                IdentityReviewCase.external_id == external_id,
                IdentityReviewCase.status == IdentityReviewStatus.PENDING,
            )
        )
        if existing is None:
            self._session.add(
                IdentityReviewCase(
                    entity_type=entity_type,
                    provider=PROVIDER,
                    external_id=external_id,
                    status=IdentityReviewStatus.PENDING,
                    provider_name=provider_name,
                    candidate_uuids=[str(candidate) for candidate in candidate_uuids],
                    evidence=evidence or {},
                )
            )

    async def _append_status_revision(
        self,
        match: Match,
        status: FixtureStatus,
        provider_status: str,
        observed_at: datetime,
    ) -> None:
        """Update status without inventing a new kickoff/schedule revision."""

        current = await self._session.scalar(
            select(FixtureScheduleRevision).where(
                FixtureScheduleRevision.match_uuid == match.match_uuid,
                FixtureScheduleRevision.superseded_at.is_(None),
            )
        )
        if current is not None:
            current.canonical_status = status
            current.provider_status = provider_status
            current.observed_at = observed_at
            return
        self._session.add(
            FixtureScheduleRevision(
                match_uuid=match.match_uuid,
                revision_number=1,
                kickoff_at=match.current_kickoff_at,
                canonical_status=status,
                provider_status=provider_status,
                observed_at=observed_at,
            )
        )

    async def _upsert_actual_result(
        self, match: Match, fixture: ProviderFixture, observed_at: datetime
    ) -> bool:
        if match.status not in (FixtureStatus.FINISHED, FixtureStatus.AWARDED):
            return False
        home_goals = fixture.normalized_home_score
        away_goals = fixture.normalized_away_score
        if home_goals is None or away_goals is None:
            return False
        accepted = await self._session.scalar(
            select(ActualResultRevision).where(
                ActualResultRevision.match_uuid == match.match_uuid,
                ActualResultRevision.accepted.is_(True),
            )
        )
        if (
            accepted is not None
            and accepted.home_goals == home_goals
            and accepted.away_goals == away_goals
        ):
            return False
        if accepted is not None:
            accepted.accepted = False
        revision_number = (
            await self._session.scalar(
                select(func.coalesce(func.max(ActualResultRevision.revision_number), 0)).where(
                    ActualResultRevision.match_uuid == match.match_uuid
                )
            )
            or 0
        ) + 1
        self._session.add(
            ActualResultRevision(
                match_uuid=match.match_uuid,
                revision_number=revision_number,
                home_goals=home_goals,
                away_goals=away_goals,
                result_kind=(
                    ResultKind.AWARDED
                    if match.status is FixtureStatus.AWARDED
                    else ResultKind.REGULAR
                ),
                accepted=True,
                observed_at=observed_at,
            )
        )
        prediction = await self._session.scalar(
            select(PredictionVersion).where(
                PredictionVersion.match_uuid == match.match_uuid,
                PredictionVersion.state == PredictionState.ACTIVE_LOCKED,
            )
        )
        if prediction is not None:
            prediction.state = PredictionState.EVALUATED
        return True
