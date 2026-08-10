# Phase 15 tactical-model training result

Date: 2026-08-10

## Decision

Training completed successfully, but the tactical candidate was **rejected for
official forecasts**. Phase 7 goals remains the approved outcome and scoreline
model. The rejected artifact is retained locally for reproducibility and audit;
the production forecast path must not load it as an official model.

## What was trained

- 2,280 chronologically ordered Premier League fixtures from 2020/21 to 2025/26.
- 134 prior-only features: 74 base, 26 player-context, and 34 tactical-proxy
  features.
- 2,768 observed team starting XIs.
- 97.5% two-team style-history coverage.
- 58.7% two-team observed-shape coverage.
- 12 deterministic logistic-regression and histogram-gradient-boosting
  candidates using random seed 42.

Candidate selection used development folds ending in 2021/22 and 2022/23.
Temperature calibration used 2023/24. The final comparison used 760 untouched
fixtures from 2024/25 and 2025/26.

## Candidate selection

The development winner was `logistic-c-0.03`, with mean log loss 1.1093 and mean
Brier score 0.6486. Strong regularization performed better than every more
flexible logistic or gradient-boosting candidate in the configured search.

## Untouched holdout comparison

Lower is better for log loss, Brier, RPS, and ECE. Higher is better for
accuracy.

| Model | Accuracy | Log loss | Brier | RPS | ECE |
|---|---:|---:|---:|---:|---:|
| Phase 15 tactical candidate | 46.32% | 1.0794 | 0.6481 | 0.2243 | 0.0768 |
| Phase 6 Elo | 50.26% | 1.0112 | 0.6071 | 0.2069 | 0.0436 |
| Phase 7 goals | 49.87% | 1.0089 | 0.6043 | 0.2063 | 0.0183 |

Against Phase 7, the tactical candidate was 3.55 percentage points less
accurate and its log loss was 0.0705 worse. It was also worse on Brier score,
ranked probability score, and calibration error. The promotion gate therefore
rejected it automatically.

## Reported tactical associations

The strongest tactical-specific associations reported by the fitted logistic
candidate were:

1. `away_shape_stability` (importance 0.1989)
2. `home_style_sample_count` (importance 0.1937)
3. `home_style_history_coverage` (importance 0.1937)
4. `home_shots_against_per_match` (importance 0.1742)

The two style coverage fields encode the same five-match denominator and
therefore carry duplicate information. These values are associations, not
causal evidence that changing a formation or statistic would change a result.

## Interpretation

The rejection does not show that tactics are irrelevant. It shows that this
specific historical representation did not add sufficiently reliable signal
beyond Phase 7 on unseen seasons. Important limitations include:

- observed starting-state coverage begins partway through 2022/23;
- FPL positions describe broad player groups rather than in-possession and
  out-of-possession structures;
- shots, corners, and fouls are behavioural proxies rather than direct tactical
  measurements;
- player availability history remains incomplete;
- the 2024/25 and 2025/26 holdout has already been inspected across several
  research phases, so live 2026/27 forecasts remain the next honest validation.

The real-data UI and expected-formation inference remain useful product
features. Only the rejected outcome-probability model is withheld.

## Artifact identity

- Model version: `tactical-v1-9f9962f451e7`
- Model type: multinomial logistic regression
- SHA-256: `8d87da6d81834b9e7c1324e8d9ac901d732dd0c951f1cd42f4d96f756a9fd345`
- Promotion status: `rejected`
- Official-forecast use: `false`

The model binary and complete evaluation are ignored local artifacts under
`artifacts/models/tactical/tactical-v1-9f9962f451e7/`; they are not committed to
source control.
