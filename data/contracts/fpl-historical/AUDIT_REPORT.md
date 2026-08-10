# Historical FPL data audit

Date: 2026-08-10

## Result

The dataset **passes the player-strength source gate**.

It does not by itself complete the historical injury or confirmed-lineup model.

| Season | Available | Fixtures | Player performances | Candidate coverage | Starts field |
|---|---:|---:|---:|---:|---:|
| 2020-21 | Yes | 380 | 10,393 | 100.0% | No |
| 2021-22 | Yes | 380 | 10,485 | 100.0% | No |
| 2022-23 | Yes | 380 | 11,345 | 100.0% | Yes |
| 2023-24 | Yes | 380 | 11,384 | 100.0% | Yes |
| 2024-25 | Yes | 380 | 11,566 | 100.0% | Yes |
| 2025-26 | Yes | 380 | 11,492 | 100.0% | Yes |

## Training gate

- Unique player-match performances: 66,665 (minimum 10,000).
- Candidate-covered fixtures: 2,280 of 2,280 (100.0%; minimum 70.0%).
- Player identity mapping adequate: true.
- Player-strength source ready: true.
- Full availability model ready: false.

## Safe use

- Match outcomes and player performance fields become usable only after that match.
- Same-gameweek `xP`, transfer, popularity, and value fields are excluded from same-fixture features because their observation time is uncertain.
- Missing injury information means unknown, never available.
- Player IDs remain external references and must map to internal `player_uuid` values.

## Remaining limitations

- Historical FPL rows do not preserve reliable 24-hour injury snapshots or confirmed starting status across every season.
- Provider ratings are not expected in FPL records and remain optional.
- Repository and upstream data terms must be reviewed before public redistribution.
- No data was imported and no model was trained during this audit.
