# Phase 10 player impact and availability

Date: 2026-08-10

## Outcome

Phase 10 implements the complete player-context ingestion, feature, expected-
lineup, training, calibration, artifact, and reporting path. The historical FPL
import now passes the explicit player-strength coverage gate. The reference
model has still **not been trained**; no Phase 10 model is approved for official
forecasts.

This is a safety decision, not a hidden implementation gap. Training a player-
impact model on empty or selectively available histories would create convincing
but false importance estimates.

## Live KickoffAPI audit

The bounded audit made exactly seven authenticated, read-only requests. All raw
responses and failed responses were captured through the existing quota ledger.
The committed evidence contains shapes and counts only.

| Input | Sample result |
|---|---|
| Player profiles | HTTP 200, five rows, contract valid |
| Historical fixtures | HTTP 200, five rows, contract valid |
| Team squad | HTTP 200, 16 rows, contract valid |
| Sample fixture lineups | HTTP 404 |
| Sample fixture player statistics | HTTP 404 |
| Injuries | HTTP 200, five rows, contract valid after offline schema adaptation |
| Transfers for sampled team | HTTP 200, empty result, contract valid |

The account dashboard confirms two independent limits: 100 requests per day and
30 requests per minute. During this audit, `X-RateLimit-Limit` reported the
30-request minute window and `X-RateLimit-Remaining` decreased from 29 to 23.
This does not contradict the daily plan. Prem Engine continues to enforce its
configured 100/day hard limit and 85/day operational ceiling while also honoring
the provider's observed short-window remaining count and reset time.

A 404 for one sampled historical fixture does not prove that the endpoint is
universally unavailable. It proves that coverage cannot be assumed fixture by
fixture. Every normalized observation therefore carries provenance and coverage
state.

## Canonical persistence

The migration adds:

- `observed_lineups` and `observed_lineup_players` for versioned confirmed lineup
  snapshots;
- `player_match_performances` for normalized post-match minutes, starting state,
  rating, and statistics;
- `player_availability_reports` for append-oriented injury, doubt, suspension,
  available, and unknown observations;
- `transfer_observations` for observed movements between internal club UUIDs.

Provider player IDs are mapped through `player_external_references`. They never
replace `player_uuid`. Raw responses remain append-only, so a later provider
correction does not erase the original evidence.

## Player strength

Strength uses only a player's ten most recent performances available before the
fixture cutoff. Recent observations receive exponentially greater weight.

The transparent reference calculation combines:

- weighted starting and minutes probability;
- rating relative to a neutral 6.5 reference when ratings exist;
- goals and assists per 90;
- a minutes-based reliability factor capped after 900 minutes;
- a further confidence reduction when evidence comes from a previous club.

The score is a modeling feature, not a public claim that one player is objectively
better than another. Feature effects remain associational.

## Expected lineup

The deterministic reference selector uses a 4-3-3 structure:

- one goalkeeper;
- four defenders;
- three midfielders;
- three attackers.

Selection ranks prior starting probability multiplied by the latest known
availability probability. If an endpoint supplies no report, the probability is
0.75 and its coverage flag remains unknown. Missing data never becomes a false
confirmation of availability.

The stored expected-lineup result contains starters, seven substitutes, formation,
per-player starting and availability probabilities, strength, and an aggregate
confidence score. Future predicted lineups can be serialized into the existing
`predicted_lineups` table when the 24-hour forecast service is implemented.

## Added features

Phase 10 adds 26 numeric features, 13 per team:

- candidate squad size;
- player-history coverage;
- availability-report coverage;
- expected-XI strength;
- expected-XI availability;
- missing-player impact;
- replacement drop-off;
- bench strength;
- lineup stability;
- expected-lineup confidence;
- known absence count;
- suspension count;
- transfer uncertainty.

Together with the 74 Phase 8 features, a player-enhanced row has 100 model-ready
features.

## Coverage and promotion gates

Training is allowed only when:

1. at least 10,000 player-match performance rows exist; and
2. at least 70% of fixtures have both teams represented by at least 15 candidates
   and at least 50% player-history coverage.

When the gate opens, the training command uses the same chronological design as
Phase 9:

- development folds: 2020/21 through 2022/23;
- calibration: 2023/24;
- untouched holdout: 2024/25 and 2025/26;
- deterministic logistic and histogram-gradient-boosting candidates;
- temperature calibration;
- comparison with Phase 6 Elo and Phase 7 goals;
- promotion only after holdout log-loss and Brier improvement.

## Reference result

- Fixtures: 2,280 across six seasons.
- Base features: 74.
- Player features: 26.
- Available normalized historical player performances: 66,665.
- Adequately covered fixtures: 2,189 of 2,280 (96.0%).
- Training status: `ready_for_manual_training`.
- Official model allowed: false.
- Generated model artifact: none.

The reference export exists only as an ignored local audit artifact. The compact,
committed result is `data/contracts/models/player-impact-summary.json`.

## Manual workflow

Reproduce every ignored input and readiness artifact with:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\prepare-player-training.ps1
```

The preparation script refreshes canonical match identities, rebuilds the base
features, exports player context, and creates the 100-feature player dataset. It
does not train a model. After reviewing the readiness report, run the trainer as
a separate, explicitly approved manual action.

## Remaining limitations

- Historical 24-hour injury, suspension, and transfer snapshots remain absent.
  The first player model therefore trains player-strength and expected-lineup
  effects, while availability-effect columns remain explicit but unobserved.
- The sampled lineup and fixture-player endpoints returned 404.
- Injury records are present, but absence of a record cannot confirm fitness.
- The sampled transfer result was empty.
- Tactical inference is intentionally deferred to a later phase.
