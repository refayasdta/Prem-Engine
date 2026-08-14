"""Chronological Phase 7 cutoff and revision-selection tests."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from prem_engine_api.config import Settings
from prem_engine_api.domain.enums import FixtureStatus
from prem_engine_api.domain.models import (
    ActualResultRevision,
    Club,
    Competition,
    LocalModelArtifact,
    Match,
    Season,
)
from prem_engine_api.local_training import (
    TrainingCutoff,
    _current_records,
    _write_artifact,
    next_training_cutoff,
)
from prem_engine_modeling.data import HistoricalDataset, MatchRecord
from prem_engine_modeling.goal_artifacts import load_goal_artifact
from prem_engine_modeling.goals import GoalModelConfig
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_season(session: AsyncSession) -> tuple[Season, Club, Club]:
    competition = Competition(slug="local-training", name="Premier League", country_code="GB")
    home = Club(canonical_name="Training Home", short_name="Home")
    away = Club(canonical_name="Training Away", short_name="Away")
    session.add_all((competition, home, away))
    await session.flush()
    season = Season(
        competition_uuid=competition.competition_uuid,
        label="2026/27",
        start_date=date(2026, 7, 1),
        end_date=date(2027, 6, 30),
    )
    session.add(season)
    await session.flush()
    return season, home, away


async def _seed_match(
    session: AsyncSession,
    *,
    season: Season,
    home: Club,
    away: Club,
    matchweek: int,
    kickoff: datetime,
    status: FixtureStatus,
) -> Match:
    match = Match(
        season_uuid=season.season_uuid,
        home_club_uuid=home.club_uuid,
        away_club_uuid=away.club_uuid,
        status=status,
        current_kickoff_at=kickoff,
        prediction_due_at=kickoff - timedelta(hours=24),
        provider_round=f"Matchday {matchweek}",
        matchweek=matchweek,
    )
    session.add(match)
    await session.flush()
    return match


def _result(
    match: Match,
    *,
    revision: int,
    observed_at: datetime,
    home_goals: int,
    accepted: bool,
) -> ActualResultRevision:
    return ActualResultRevision(
        match_uuid=match.match_uuid,
        revision_number=revision,
        home_goals=home_goals,
        away_goals=1,
        accepted=accepted,
        training_eligible=True,
        observed_at=observed_at,
    )


@pytest.mark.asyncio
async def test_postponed_fixture_does_not_block_later_matchweek_cutoffs(
    db_session: AsyncSession,
) -> None:
    season, home, away = await _seed_season(db_session)
    first_kickoff = datetime(2026, 8, 15, 14, tzinfo=UTC)
    first = await _seed_match(
        db_session,
        season=season,
        home=home,
        away=away,
        matchweek=1,
        kickoff=first_kickoff,
        status=FixtureStatus.FINISHED,
    )
    await _seed_match(
        db_session,
        season=season,
        home=away,
        away=home,
        matchweek=1,
        kickoff=first_kickoff + timedelta(hours=2),
        status=FixtureStatus.POSTPONED,
    )
    second = await _seed_match(
        db_session,
        season=season,
        home=away,
        away=home,
        matchweek=2,
        kickoff=first_kickoff + timedelta(days=7),
        status=FixtureStatus.FINISHED,
    )
    first_observed = first_kickoff + timedelta(hours=2)
    second_observed = second.current_kickoff_at + timedelta(hours=2)
    db_session.add_all(
        (
            _result(
                first,
                revision=1,
                observed_at=first_observed,
                home_goals=2,
                accepted=True,
            ),
            _result(
                second,
                revision=1,
                observed_at=second_observed,
                home_goals=1,
                accepted=True,
            ),
        )
    )
    await db_session.flush()

    first_cutoff = await next_training_cutoff(db_session, season_uuid=season.season_uuid)
    assert first_cutoff is not None
    assert first_cutoff.matchweek == 1
    assert first_cutoff.revision == 1
    assert first_cutoff.fixture_uuids == (str(first.match_uuid),)

    db_session.add(
        LocalModelArtifact(
            model_type="dynamic_poisson_dixon_coles",
            model_version="goals-local-test-mw01",
            season_uuid=season.season_uuid,
            cutoff_matchweek=1,
            cutoff_revision=1,
            cutoff_at=first_observed,
            status="succeeded",
            active=False,
            training_data_checksum="a" * 64,
            fixture_set_checksum="b" * 64,
            included_fixture_uuids=[str(first.match_uuid)],
            feature_schema=[],
            runtime_versions={},
            started_at=first_observed,
            completed_at=first_observed,
        )
    )
    await db_session.flush()

    second_cutoff = await next_training_cutoff(db_session, season_uuid=season.season_uuid)
    assert second_cutoff is not None
    assert second_cutoff.matchweek == 2


@pytest.mark.asyncio
async def test_cutoff_replays_the_latest_result_known_at_that_time(
    db_session: AsyncSession,
) -> None:
    season, home, away = await _seed_season(db_session)
    kickoff = datetime(2026, 8, 15, 14, tzinfo=UTC)
    match = await _seed_match(
        db_session,
        season=season,
        home=home,
        away=away,
        matchweek=1,
        kickoff=kickoff,
        status=FixtureStatus.FINISHED,
    )
    original_time = kickoff + timedelta(hours=2)
    correction_time = original_time + timedelta(days=1)
    db_session.add_all(
        (
            _result(
                match,
                revision=1,
                observed_at=original_time,
                home_goals=2,
                accepted=False,
            ),
            _result(
                match,
                revision=2,
                observed_at=correction_time,
                home_goals=3,
                accepted=True,
            ),
        )
    )
    await db_session.flush()
    cutoff = TrainingCutoff(
        season_uuid=season.season_uuid,
        season_label=season.label,
        matchweek=1,
        revision=1,
        cutoff_at=original_time,
        fixture_uuids=(str(match.match_uuid),),
    )

    records = await _current_records(db_session, cutoff=cutoff)

    assert len(records) == 1
    assert records[0].home_goals == 2
    assert records[0].available_after == original_time

    db_session.add(
        LocalModelArtifact(
            model_type="dynamic_poisson_dixon_coles",
            model_version="goals-local-before-correction",
            season_uuid=season.season_uuid,
            cutoff_matchweek=1,
            cutoff_revision=1,
            cutoff_at=original_time,
            status="succeeded",
            active=False,
            training_data_checksum="c" * 64,
            fixture_set_checksum="d" * 64,
            included_fixture_uuids=[str(match.match_uuid)],
            feature_schema=[],
            runtime_versions={},
            started_at=original_time,
            completed_at=original_time,
        )
    )
    await db_session.flush()

    corrected_cutoff = await next_training_cutoff(
        db_session, season_uuid=season.season_uuid
    )
    assert corrected_cutoff is not None
    assert corrected_cutoff.matchweek == 1
    assert corrected_cutoff.revision == 2
    assert corrected_cutoff.cutoff_at == correction_time


def test_local_goal_artifact_is_immutable_verified_and_idempotent(tmp_path: Path) -> None:
    kickoff = datetime(2026, 8, 15, 14, tzinfo=UTC)
    observed = kickoff + timedelta(hours=2)
    fixture_uuid = str(uuid4())
    home_uuid = str(uuid4())
    away_uuid = str(uuid4())
    record = MatchRecord(
        match_uuid=fixture_uuid,
        season="2026/27",
        kickoff_at=kickoff,
        available_after=observed,
        home_club_uuid=home_uuid,
        home_club="Artifact Home",
        away_club_uuid=away_uuid,
        away_club="Artifact Away",
        home_goals=2,
        away_goals=1,
        result="H",
    )
    dataset = HistoricalDataset((record,), "e" * 64, ("2026/27",))
    cutoff = TrainingCutoff(
        season_uuid=uuid4(),
        season_label="2026/27",
        matchweek=1,
        revision=1,
        cutoff_at=observed,
        fixture_uuids=(fixture_uuid,),
    )
    config = GoalModelConfig()
    arguments = {
        "settings": Settings(local_model_root=tmp_path),
        "cutoff": cutoff,
        "dataset": dataset,
        "config": config,
        "attack": {home_uuid: 0.1, away_uuid: -0.1},
        "defence": {home_uuid: -0.05, away_uuid: 0.05},
        "runtime_versions": {"python": "test"},
        "created_at": observed,
    }

    first = _write_artifact(**arguments)  # type: ignore[arg-type]
    second = _write_artifact(**arguments)  # type: ignore[arg-type]

    assert first.version == second.version
    assert first.model_checksum == second.model_checksum
    assert first.report_checksum == second.report_checksum
    assert load_goal_artifact(first.model_path).current_season == "2026/27"
    report = json.loads((first.directory / "provenance.json").read_text())
    assert report["cutoff"] == {
        "matchweek": 1,
        "observed_at": observed.isoformat(),
        "revision": 1,
        "season": "2026/27",
    }
    assert report["included_fixture_uuids"] == [fixture_uuid]
