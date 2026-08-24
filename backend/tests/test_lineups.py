"""Deterministic expected-lineup coverage fallbacks."""

from uuid import uuid4

from prem_engine_api.forecasting.lineups import (
    FORMATION_REQUIREMENTS,
    _Candidate,
    _complete_lineup,
)


def test_empty_coverage_uses_deterministic_labeled_placeholders() -> None:
    match_uuid = uuid4()
    club_uuid = uuid4()

    def build():
        return _complete_lineup(
            match_uuid=match_uuid,
            club_uuid=club_uuid,
            club_name="Hull City AFC",
            short_name="Hull City",
            formation="4-3-3",
            requirements=FORMATION_REQUIREMENTS,
            starters=[],
            substitutes=[],
            confidence=0.0,
        )

    first = build()
    second = build()

    assert len(first.starters) == 11
    assert len(first.substitutes) == 7
    assert [player.player_uuid for player in first.starters + first.substitutes] == [
        player.player_uuid for player in second.starters + second.substitutes
    ]
    assert all(
        player.name.startswith("[Hull City AFC] player ")
        for player in first.starters + first.substitutes
    )
    assert sum(player.position == "GK" for player in first.starters) == 1


def test_partial_coverage_keeps_real_players_and_fills_only_missing_slots() -> None:
    real_player_uuid = uuid4()
    lineup = _complete_lineup(
        match_uuid=uuid4(),
        club_uuid=uuid4(),
        club_name="Ipswich Town FC",
        short_name="Ipswich",
        formation="4-3-3",
        requirements=FORMATION_REQUIREMENTS,
        starters=[
            _Candidate(
                player_uuid=real_player_uuid,
                name="Real Goalkeeper",
                position="GK",
                shirt_number=1,
                starting_probability=0.8,
                availability_probability=1.0,
                strength=0.0,
                evidence=1.0,
            )
        ],
        substitutes=[],
        confidence=0.1,
    )

    assert lineup.starters[0].player_uuid == real_player_uuid
    assert lineup.starters[0].name == "Real Goalkeeper"
    assert len(lineup.starters) == 11
    assert len(lineup.substitutes) == 7
    assert (
        sum(player.name.startswith("[Ipswich Town FC] player ") for player in lineup.starters) == 10
    )
