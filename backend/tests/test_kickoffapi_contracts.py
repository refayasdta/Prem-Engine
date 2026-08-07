"""Contract tests for both v2 shapes currently published by KickoffAPI."""

from prem_engine_api.providers.kickoffapi.contracts import (
    FixtureEnvelope,
    LeagueEnvelope,
    validate_endpoint_payload,
)


def test_parses_native_v2_fixture_shape() -> None:
    envelope = FixtureEnvelope.model_validate(
        {
            "data": [
                {
                    "id": "fx_native",
                    "date": "2026-08-15T14:00:00Z",
                    "status": {"short": "NS", "long": "Not Started"},
                    "league": {"id": "lg_native", "name": "Premier League", "season": 2026},
                    "home": {"id": "tm_home", "name": "Home"},
                    "away": {"id": "tm_away", "name": "Away"},
                    "score": {"home": None, "away": None},
                }
            ],
            "meta": {"count": 1},
        }
    )
    fixture = envelope.data[0]
    assert fixture.normalized_home.id == "tm_home"
    assert fixture.status_code == "NS"


def test_parses_migration_guide_v2_fixture_shape() -> None:
    envelope = FixtureEnvelope.model_validate(
        {
            "data": [
                {
                    "id": "fx_code",
                    "date": "2026-08-15T14:00:00Z",
                    "status": "finished",
                    "league": {"id": "en.1", "name": "Premier League", "season": 2026},
                    "homeTeam": {"id": "t_home", "name": "Home"},
                    "awayTeam": {"id": "t_away", "name": "Away"},
                    "homeScore": 2,
                    "awayScore": 1,
                }
            ],
            "count": 1,
            "page": 1,
            "totalPages": 1,
        }
    )
    fixture = envelope.data[0]
    assert fixture.normalized_away.id == "t_away"
    assert fixture.normalized_home_score == 2
    assert fixture.status_code == "finished"


def test_endpoint_validator_rejects_unregistered_endpoint() -> None:
    leagues = validate_endpoint_payload(
        "/api/v2/leagues",
        {"data": [{"id": "en.1", "name": "Premier League", "season": 2026}]},
    )
    assert isinstance(leagues, LeagueEnvelope)
    try:
        validate_endpoint_payload("/api/v2/unknown", {"data": []})
    except ValueError as error:
        assert "no contract validator" in str(error)
    else:  # pragma: no cover - required assertion branch
        raise AssertionError("unknown endpoint should not validate")
