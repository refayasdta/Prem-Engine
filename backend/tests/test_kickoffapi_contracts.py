"""Contract tests for both v2 shapes currently published by KickoffAPI."""

from prem_engine_api.providers.kickoffapi.contracts import (
    FixtureEnvelope,
    InjuryEnvelope,
    LeagueEnvelope,
    LineupEnvelope,
    PlayerEnvelope,
    SquadEnvelope,
    TransferEnvelope,
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


def test_player_and_squad_contracts_accept_native_ids() -> None:
    players = validate_endpoint_payload(
        "/api/v2/players",
        {"data": [{"id": "pl_1", "name": "Example Player", "nationality": "England"}]},
    )
    squad = validate_endpoint_payload(
        "/api/v2/teams/tm_1/squad",
        {"data": [{"id": "pl_1", "name": "Example Player", "position": "Midfielder"}]},
    )
    assert isinstance(players, PlayerEnvelope)
    assert isinstance(squad, SquadEnvelope)
    assert squad.data[0].position == "Midfielder"


def test_lineup_contract_normalizes_starting_xi_alias() -> None:
    lineup = validate_endpoint_payload(
        "/api/v2/fixtures/fx_1/lineups",
        {
            "data": [
                {
                    "team": {"id": "tm_1", "name": "Home"},
                    "formation": "4-3-3",
                    "startXI": [
                        {
                            "player": {"id": "pl_1", "name": "Goalkeeper"},
                            "pos": "G",
                            "grid": "1:1",
                        }
                    ],
                    "substitutes": [],
                }
            ]
        },
    )
    assert isinstance(lineup, LineupEnvelope)
    assert lineup.data[0].start_xi[0].position == "G"


def test_availability_and_transfer_contracts_allow_sparse_references() -> None:
    injuries = validate_endpoint_payload(
        "/api/v2/injuries",
        {
            "data": [
                {
                    "id": 1,
                    "player": {"id": "pl_1", "name": "Example"},
                    "injury": {"type": "Suspension", "from": None, "until": None},
                }
            ]
        },
    )
    transfers = validate_endpoint_payload(
        "/api/v2/transfers",
        {"data": [{"id": "tr_1", "date": "2026-07-01", "player": {"id": "pl_1"}}]},
    )
    assert isinstance(injuries, InjuryEnvelope)
    assert injuries.data[0].injury is not None
    assert injuries.data[0].injury.type == "Suspension"
    assert isinstance(transfers, TransferEnvelope)
    assert transfers.data[0].date.isoformat() == "2026-07-01"
