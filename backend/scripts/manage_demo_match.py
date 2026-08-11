"""Create, replay, or remove the isolated Prem Engine UI demo match."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from prem_engine_api.config import get_settings
from prem_engine_api.db.session import create_engine, create_session_factory
from prem_engine_api.domain.enums import (
    FixtureStatus,
    IdentityReviewState,
    KickoffPrecision,
    PredictionState,
)
from prem_engine_api.domain.models import (
    Club,
    ClubExternalReference,
    LifecycleEvent,
    Match,
    PredictedLineup,
    PredictionVersion,
    Season,
    SeasonClub,
    StoredSimulation,
)
from sqlalchemy import delete, select

DEMO_HOME_UUID = UUID("de000000-0000-4000-8000-000000000001")
DEMO_AWAY_UUID = UUID("de000000-0000-4000-8000-000000000002")
DEMO_MATCH_UUID = UUID("de000000-0000-4000-8000-000000000003")
DEMO_PREDICTION_UUID = UUID("de000000-0000-4000-8000-000000000004")
DEMO_LINEUP_UUID = UUID("de000000-0000-4000-8000-000000000005")
DEMO_SIMULATION_UUID = UUID("de000000-0000-4000-8000-000000000006")
DEMO_CLUB_UUIDS = (DEMO_HOME_UUID, DEMO_AWAY_UUID)


def _checksum(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(body).hexdigest()


def _crest(initials: str, primary: str, accent: str) -> str:
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
<path fill="{primary}" d="M60 4 106 20v36c0 29-18 49-46 60C32 105 14 85 14 56V20z"/>
<path fill="{accent}" d="M60 12 96 25v30c0 22-12 39-36 50C36 94 24 77 24 55V25z"/>
<circle cx="60" cy="54" r="27" fill="{primary}"/>
<text x="60" y="62" text-anchor="middle" font-family="Arial" font-size="24"
 font-weight="700" fill="#fff">{initials}</text>
</svg>"""
    encoded = base64.b64encode(svg.encode()).decode()
    return f"data:image/svg+xml;base64,{encoded}"


def _player(side: str, index: int, position: str) -> dict[str, Any]:
    prefix = "Northstar" if side == "home" else "Harbor"
    return {
        "player_uuid": str(uuid5(NAMESPACE_URL, f"prem-engine-demo:{side}:{index}")),
        "name": f"{prefix} Player {index:02d}",
        "position": position,
        "shirt_number": index,
        "shirt_number_source": "presentation_slot",
        "starting_probability": 0.82 if index <= 11 else 0.28,
        "availability_probability": 0.97,
    }


def _team_lineup(club_uuid: UUID, club_name: str, short_name: str, side: str) -> dict[str, Any]:
    positions = ["GK", "DEF", "DEF", "DEF", "DEF", "MID", "MID", "MID", "FWD", "FWD", "FWD"]
    bench_positions = ["GK", "DEF", "DEF", "MID", "MID", "FWD"]
    return {
        "club_uuid": str(club_uuid),
        "club_name": club_name,
        "short_name": short_name,
        "formation": "4-3-3",
        "confidence": 0.84,
        "starters": [_player(side, index, position) for index, position in enumerate(positions, 1)],
        "substitutes": [
            _player(side, index, position) for index, position in enumerate(bench_positions, 12)
        ],
    }


def _event(
    event_id: str,
    minute: int,
    second: int,
    event_type: str,
    commentary: str,
    home_score: int,
    away_score: int,
    *,
    team: str | None = None,
    player_index: int | None = None,
) -> dict[str, Any]:
    player_side = team if team in ("home", "away") else None
    player_name = None
    player_uuid = None
    if player_side and player_index:
        prefix = "Northstar" if player_side == "home" else "Harbor"
        player_name = f"{prefix} Player {player_index:02d}"
        player_uuid = str(uuid5(NAMESPACE_URL, f"prem-engine-demo:{player_side}:{player_index}"))
    return {
        "event_id": event_id,
        "minute": minute,
        "second": second,
        "event_type": event_type,
        "team": team,
        "player_uuid": player_uuid,
        "player_name": player_name,
        "secondary_player_uuid": None,
        "secondary_player_name": None,
        "commentary": commentary,
        "home_score": home_score,
        "away_score": away_score,
    }


def _events() -> list[dict[str, Any]]:
    return [
        _event("demo-00", 0, 0, "kickoff", "The temporary showcase match begins.", 0, 0),
        _event(
            "demo-01",
            7,
            12,
            "shot",
            "Northstar test the Harbor back line early.",
            0,
            0,
            team="home",
            player_index=9,
        ),
        _event(
            "demo-02",
            15,
            40,
            "corner",
            "Harbor win the first corner of the match.",
            0,
            0,
            team="away",
            player_index=8,
        ),
        _event(
            "demo-03",
            23,
            18,
            "goal",
            "Northstar Player 10 finishes a quick move.",
            1,
            0,
            team="home",
            player_index=10,
        ),
        _event(
            "demo-04",
            31,
            5,
            "yellow_card",
            "A late Harbor challenge draws a booking.",
            1,
            0,
            team="away",
            player_index=4,
        ),
        _event(
            "demo-05",
            39,
            44,
            "shot_on_target",
            "Harbor force a sharp save before the break.",
            1,
            0,
            team="away",
            player_index=9,
        ),
        _event("demo-06", 45, 0, "half_time", "Northstar lead at the interval.", 1, 0),
        _event(
            "demo-07",
            52,
            21,
            "foul",
            "Northstar concede a free kick in midfield.",
            1,
            0,
            team="home",
            player_index=6,
        ),
        _event(
            "demo-08",
            61,
            9,
            "goal",
            "Harbor Player 11 levels with a low finish.",
            1,
            1,
            team="away",
            player_index=11,
        ),
        _event(
            "demo-09",
            72,
            33,
            "corner",
            "Northstar increase the pressure with another corner.",
            1,
            1,
            team="home",
            player_index=7,
        ),
        _event(
            "demo-10",
            81,
            47,
            "shot_on_target",
            "The Harbor keeper keeps the scores level.",
            1,
            1,
            team="home",
            player_index=11,
        ),
        _event(
            "demo-11",
            87,
            26,
            "goal",
            "Northstar Player 09 scores the late winner.",
            2,
            1,
            team="home",
            player_index=9,
        ),
        _event("demo-12", 90, 0, "full_time", "The temporary simulation finishes 2-1.", 2, 1),
    ]


async def _cleanup(session: Any) -> None:
    await session.execute(
        delete(LifecycleEvent).where(
            LifecycleEvent.aggregate_uuid.in_((DEMO_MATCH_UUID, DEMO_PREDICTION_UUID))
        )
    )
    prediction = await session.get(PredictionVersion, DEMO_PREDICTION_UUID)
    if prediction is not None:
        prediction.state = PredictionState.GENERATING
        await session.flush()
    await session.execute(delete(Match).where(Match.match_uuid == DEMO_MATCH_UUID))
    await session.flush()
    await session.execute(delete(SeasonClub).where(SeasonClub.club_uuid.in_(DEMO_CLUB_UUIDS)))
    await session.execute(
        delete(ClubExternalReference).where(ClubExternalReference.club_uuid.in_(DEMO_CLUB_UUIDS))
    )
    await session.execute(delete(Club).where(Club.club_uuid.in_(DEMO_CLUB_UUIDS)))
    await session.flush()


async def _seed(session: Any, now: datetime) -> dict[str, Any]:
    await _cleanup(session)
    season = await session.scalar(select(Season).order_by(Season.end_date.desc()).limit(1))
    if season is None:
        raise RuntimeError("A canonical season must be loaded before creating the demo match")

    home = Club(
        club_uuid=DEMO_HOME_UUID,
        canonical_name="Northstar Athletic",
        short_name="Northstar",
        crest_url=_crest("NA", "#39245f", "#f6a800"),
    )
    away = Club(
        club_uuid=DEMO_AWAY_UUID,
        canonical_name="Harbor City",
        short_name="Harbor",
        crest_url=_crest("HC", "#0d4d66", "#45d6c5"),
    )
    session.add_all((home, away))
    await session.flush()

    kickoff = now + timedelta(hours=2)
    due_at = kickoff - timedelta(hours=24)
    match = Match(
        match_uuid=DEMO_MATCH_UUID,
        season_uuid=season.season_uuid,
        home_club_uuid=home.club_uuid,
        away_club_uuid=away.club_uuid,
        status=FixtureStatus.SCHEDULED,
        identity_review_state=IdentityReviewState.RESOLVED,
        current_kickoff_at=kickoff,
        kickoff_precision=KickoffPrecision.EXACT,
        prediction_due_at=due_at,
    )
    session.add(match)
    await session.flush()

    events = _events()
    lineups = {
        "schema_version": "predicted-lineups-v1",
        "home": _team_lineup(home.club_uuid, home.canonical_name, home.short_name, "home"),
        "away": _team_lineup(away.club_uuid, away.canonical_name, away.short_name, "away"),
    }
    statistics = {
        "home_shots": 12,
        "away_shots": 9,
        "home_shots_on_target": 6,
        "away_shots_on_target": 4,
        "home_corners": 5,
        "away_corners": 4,
        "home_fouls": 8,
        "away_fouls": 11,
        "home_yellow_cards": 1,
        "away_yellow_cards": 2,
        "home_red_cards": 0,
        "away_red_cards": 0,
    }
    prediction = PredictionVersion(
        prediction_version_uuid=DEMO_PREDICTION_UUID,
        match_uuid=match.match_uuid,
        version_number=1,
        state=PredictionState.GENERATING,
        feature_cutoff_at=due_at,
        model_version="OptiMatch Demo",
        feature_snapshot_checksum=_checksum({"demo": True, "match": str(match.match_uuid)}),
        home_win_probability=Decimal("0.51200000"),
        draw_probability=Decimal("0.26700000"),
        away_win_probability=Decimal("0.22100000"),
        expected_home_goals=Decimal("1.7400"),
        expected_away_goals=Decimal("1.0800"),
        statistics_distribution={"statistics_model_version": "demo-v1"},
        locked_at=None,
    )
    session.add(prediction)
    await session.flush()

    lineup = PredictedLineup(
        predicted_lineup_uuid=DEMO_LINEUP_UUID,
        prediction_version_uuid=prediction.prediction_version_uuid,
        formation="dual",
        lineup_payload=lineups,
        checksum=_checksum(lineups),
    )
    simulation = StoredSimulation(
        simulation_uuid=DEMO_SIMULATION_UUID,
        prediction_version_uuid=prediction.prediction_version_uuid,
        random_seed=46246955,
        home_goals=2,
        away_goals=1,
        statistics=statistics,
        events=events,
        checksum=_checksum({"events": events, "statistics": statistics}),
        presentation_started_at=now,
        presentation_duration_seconds=60,
    )
    session.add_all((lineup, simulation))
    await session.flush()
    prediction.state = PredictionState.ACTIVE_LOCKED
    prediction.locked_at = due_at
    await session.flush()
    return {
        "action": "seeded",
        "match_uuid": str(match.match_uuid),
        "home": home.canonical_name,
        "away": away.canonical_name,
        "kickoff_at": kickoff,
        "replay_started_at": now,
        "replay_duration_seconds": 60,
    }


async def _replay(session: Any, now: datetime) -> dict[str, Any]:
    prediction = await session.get(PredictionVersion, DEMO_PREDICTION_UUID)
    simulation = await session.get(StoredSimulation, DEMO_SIMULATION_UUID)
    if prediction is None or simulation is None:
        raise RuntimeError("The demo match is not seeded")
    prediction.state = PredictionState.GENERATING
    await session.flush()
    simulation.presentation_started_at = now
    await session.flush()
    prediction.state = PredictionState.ACTIVE_LOCKED
    await session.flush()
    return {
        "action": "restarted",
        "match_uuid": str(DEMO_MATCH_UUID),
        "replay_started_at": now,
        "replay_duration_seconds": simulation.presentation_duration_seconds,
    }


async def run(action: str) -> dict[str, Any]:
    engine = create_engine(get_settings())
    sessions = create_session_factory(engine)
    try:
        async with sessions.begin() as session:
            now = datetime.now(UTC)
            if action == "seed":
                return await _seed(session, now)
            if action == "replay":
                return await _replay(session, now)
            await _cleanup(session)
            return {"action": "cleaned", "match_uuid": str(DEMO_MATCH_UUID)}
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seed", "replay", "cleanup"))
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.action)), indent=2, default=str))


if __name__ == "__main__":
    main()
