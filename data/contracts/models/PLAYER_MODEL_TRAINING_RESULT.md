# Phase 10 player-impact training result

Date: 2026-08-10

## Decision

Training completed successfully, but the candidate was **rejected for official
forecasts**. The existing Phase 7 goal model remains the best established model.
The rejected artifact is retained locally for reproducibility and audit only.

## What was trained

- 2,280 chronologically ordered Premier League fixtures from 2020/21 to 2025/26.
- 100 pre-match features: 74 team, form, Elo, and goal-model features plus 26
  player-context and expected-lineup features.
- 66,665 normalized player-match records.
- 2,189 adequately covered fixtures (96.0%).
- 12 deterministic logistic-regression and histogram-gradient-boosting
  candidates using random seed 42.

The development folds used 2020/21 through 2022/23, calibration used 2023/24,
and the final test used 760 untouched fixtures from 2024/25 and 2025/26.

## Candidate selection

The development winner was `logistic-c-0.03`, with mean log loss 1.0959 and
mean Brier score 0.6385. Its strong regularization outperformed every more
flexible candidate, including all tested gradient-boosting configurations.

## Untouched holdout comparison

Lower is better for log loss, Brier, RPS, and ECE. Higher is better for
accuracy.

| Model | Accuracy | Log loss | Brier | RPS | ECE |
|---|---:|---:|---:|---:|---:|
| Player-impact candidate | 45.53% | 1.0931 | 0.6548 | 0.2266 | 0.0865 |
| Phase 6 Elo | 50.26% | 1.0112 | 0.6071 | 0.2069 | 0.0436 |
| Phase 7 goals | 49.87% | 1.0089 | 0.6043 | 0.2063 | 0.0183 |

Against the Phase 7 goal model, the player candidate was 4.34 percentage points
less accurate and its log loss was 0.0842 worse. It was also worse on Brier,
ranked probability score, and calibration error. The promotion gate therefore
rejected it automatically.

## Player-feature signal

The two player-specific features appearing among the strongest reported
associations were:

1. `home_replacement_dropoff` (importance 0.1680)
2. `away_expected_lineup_confidence` (importance 0.1649)

These values describe model association, not causal player effects. They do not
show that changing either feature would cause a result to change.

## Interpretation and limitations

The result does not mean player quality is irrelevant. It means this particular
historical representation did not add reliable predictive value beyond the
existing team and goal features on unseen seasons. Important limitations are:

- no historical 24-hour injury, suspension, or transfer observations;
- 20,878 player records without a known starting state;
- expected historical availability falls back to an explicit unknown value;
- public FPL history is useful for appearances and performance, but is not a
  complete reconstruction of the information available 24 hours before kickoff;
- tactical inference remains outside Phase 10.

The correct next action is to keep the Phase 7 goal model active and improve the
historical player/availability evidence before testing a new player model.

## Artifact identity

- Model version: `player-impact-v1-c5b7fdfa272d`
- Model type: multinomial logistic regression
- SHA-256: `a0ce7b0938ea15c9f8740bff6087fd7eb1fcb251fcb471c9ce45872edb9291a1`
- Promotion status: `rejected`
- Official-forecast use: `false`

The model binary and full evaluation are ignored local artifacts under
`artifacts/models/player-impact/player-impact-v1-c5b7fdfa272d/`; they are not
committed to source control.
