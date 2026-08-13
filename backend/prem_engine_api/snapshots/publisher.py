"""Build sanitized API responses from committed database state and publish them."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from prem_engine_api.api.forecasts import (
    MatchForecastResponse,
    UpcomingMatchResponse,
    build_match_forecast_response,
    list_upcoming_match_responses,
)
from prem_engine_api.api.insights import (
    build_evaluation_overview,
    build_standings_overview,
)
from prem_engine_api.config import Settings
from prem_engine_api.domain.enums import FixtureStatus, PredictionState
from prem_engine_api.domain.models import Match, PredictionVersion, StoredSimulation
from prem_engine_api.snapshots.storage import PublicSnapshotStore, create_public_snapshot_store

_UPCOMING_ADAPTER = TypeAdapter(list[UpcomingMatchResponse])


@dataclass(frozen=True)
class SnapshotPublicationSummary:
    published: int
    disabled: bool = False


@dataclass(frozen=True)
class ForecastPublicationMetadata:
    prediction_version_uuid: UUID
    reveal_at: datetime


class PublicSnapshotPublisher:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        settings: Settings,
        store: PublicSnapshotStore | None = None,
    ) -> None:
        self._sessions = session_factory
        self._settings = settings
        self._store = store if store is not None else create_public_snapshot_store(settings)

    @property
    def enabled(self) -> bool:
        return self._store is not None

    async def close(self) -> None:
        if self._store is not None:
            await asyncio.to_thread(self._store.close)

    async def publish_forecast(
        self,
        *,
        match_uuid: UUID,
        now: datetime,
    ) -> SnapshotPublicationSummary:
        if self._store is None:
            return SnapshotPublicationSummary(0, disabled=True)
        async with self._sessions() as session:
            response = await build_match_forecast_response(
                session,
                match_uuid=match_uuid,
                now=now,
            )
        if response is None:
            return SnapshotPublicationSummary(0)
        expiry = now + timedelta(seconds=self._settings.public_snapshot_ttl_seconds)
        if response.presentation.started_at is not None and not response.presentation.complete:
            reveal_at = response.presentation.started_at + timedelta(
                seconds=response.presentation.duration_seconds
            )
            expiry = min(expiry, reveal_at)
        elif response.lifecycle_state == "countdown":
            expiry = min(expiry, response.prediction_due_at)
        expiry = max(expiry, now + timedelta(seconds=1))
        await self._publish(
            logical_key=f"forecast/{match_uuid}",
            payload=response.model_dump_json().encode(),
            now=now,
            expires_at=expiry,
            cache_seconds=self._settings.public_snapshot_forecast_cache_seconds,
        )
        return SnapshotPublicationSummary(1)

    async def publish_standings(self, *, now: datetime) -> SnapshotPublicationSummary:
        if self._store is None:
            return SnapshotPublicationSummary(0, disabled=True)
        async with self._sessions() as session:
            response = await build_standings_overview(session, now=now)
        await self._publish(
            logical_key="standings/default",
            payload=response.model_dump_json().encode(),
            now=now,
            expires_at=now + timedelta(seconds=self._settings.public_snapshot_ttl_seconds),
            cache_seconds=self._settings.public_snapshot_default_cache_seconds,
        )
        return SnapshotPublicationSummary(1)

    async def publish_all(self, *, now: datetime) -> SnapshotPublicationSummary:
        if self._store is None:
            return SnapshotPublicationSummary(0, disabled=True)
        async with self._sessions() as session:
            upcoming = await list_upcoming_match_responses(session, now=now, limit=10)
            standings = await build_standings_overview(session, now=now)
            evaluation = await build_evaluation_overview(session, now=now)
            forecast_match_uuids = tuple(
                await session.scalars(
                    select(Match.match_uuid)
                    .where(
                        Match.current_kickoff_at >= now,
                        Match.prediction_due_at
                        <= now + timedelta(days=self._settings.public_snapshot_horizon_days),
                        Match.status.in_((FixtureStatus.SCHEDULED, FixtureStatus.POSTPONED)),
                    )
                    .order_by(Match.current_kickoff_at, Match.match_uuid)
                )
            )
            forecasts: list[MatchForecastResponse] = []
            for match_uuid in forecast_match_uuids:
                response = await build_match_forecast_response(
                    session,
                    match_uuid=match_uuid,
                    now=now,
                )
                if response is not None:
                    forecasts.append(response)
        expiry = now + timedelta(seconds=self._settings.public_snapshot_ttl_seconds)
        publications = [
            self._publish(
                logical_key="upcoming/default",
                payload=_UPCOMING_ADAPTER.dump_json(upcoming),
                now=now,
                expires_at=expiry,
                cache_seconds=self._settings.public_snapshot_default_cache_seconds,
            ),
            self._publish(
                logical_key="standings/default",
                payload=standings.model_dump_json().encode(),
                now=now,
                expires_at=expiry,
                cache_seconds=self._settings.public_snapshot_default_cache_seconds,
            ),
            self._publish(
                logical_key="evaluation/default",
                payload=evaluation.model_dump_json().encode(),
                now=now,
                expires_at=expiry,
                cache_seconds=self._settings.public_snapshot_default_cache_seconds,
            ),
        ]
        for forecast in forecasts:
            forecast_expiry = expiry
            if forecast.lifecycle_state == "countdown":
                forecast_expiry = max(
                    now + timedelta(seconds=1),
                    min(expiry, forecast.prediction_due_at),
                )
            publications.append(
                self._publish(
                    logical_key=f"forecast/{forecast.match_uuid}",
                    payload=forecast.model_dump_json().encode(),
                    now=now,
                    expires_at=forecast_expiry,
                    cache_seconds=self._settings.public_snapshot_forecast_cache_seconds,
                )
            )
        await asyncio.gather(*publications)
        return SnapshotPublicationSummary(len(publications))

    async def forecast_metadata(
        self,
        *,
        match_uuid: UUID,
        prediction_version_uuid: UUID,
    ) -> ForecastPublicationMetadata | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(PredictionVersion, StoredSimulation)
                    .join(
                        StoredSimulation,
                        StoredSimulation.prediction_version_uuid
                        == PredictionVersion.prediction_version_uuid,
                    )
                    .where(
                        PredictionVersion.match_uuid == match_uuid,
                        PredictionVersion.prediction_version_uuid == prediction_version_uuid,
                        PredictionVersion.state.in_(
                            (PredictionState.ACTIVE_LOCKED, PredictionState.EVALUATED)
                        ),
                    )
                )
            ).one_or_none()
        if row is None:
            return None
        _, simulation = row
        return ForecastPublicationMetadata(
            prediction_version_uuid=prediction_version_uuid,
            reveal_at=simulation.presentation_started_at
            + timedelta(seconds=simulation.presentation_duration_seconds),
        )

    async def _publish(
        self,
        *,
        logical_key: str,
        payload: bytes,
        now: datetime,
        expires_at: datetime,
        cache_seconds: int,
    ) -> None:
        if self._store is None:  # pragma: no cover - guarded by public methods
            return
        await asyncio.to_thread(
            self._store.publish,
            logical_key=logical_key,
            payload=payload,
            published_at=now,
            expires_at=expires_at,
            cache_seconds=cache_seconds,
        )
