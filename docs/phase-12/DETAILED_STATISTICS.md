# Phase 12 detailed match statistics

Date: 2026-08-10

## Outcome

Phase 12 implements chronological count models and safe fallbacks for the match
statistics required by the quick-match simulator. The six-season source contains
complete labels for 2,280 fixtures and 14 home/away targets. Seven targets passed
both holdout promotion measures; the remaining seven use historical-mean
fallbacks rather than publishing weaker model output.

## Historical coverage

Every target below is present for all 380 fixtures in each season from 2020/21
through 2025/26:

- half-time home and away goals;
- home and away shots;
- home and away shots on target;
- home and away corners;
- home and away fouls;
- home and away yellow cards;
- home and away red cards.

Possession and provider-measured expected goals are not present. Phase 7's
model-produced expected goals remain available, but they are forecasts and cannot
serve as historical labels for a provider-xG model. Phase 12 does not manufacture
either missing target.

## Training design

Each target has an independent regularized Poisson regression using the 74
leakage-safe Phase 8 features. Regularization candidates are 0.01, 0.1, 1.0, and
10.0. Selection uses two chronological development folds:

1. train 2020/21, validate 2021/22;
2. train 2020/21–2021/22, validate 2022/23.

The selected model is fitted on 2020/21–2022/23. A multiplicative mean
calibration and a 90% absolute-residual interval are fitted on 2023/24. Final
evaluation uses 760 fixtures from 2024/25 and 2025/26.

A target is promoted only when it improves both mean absolute error and mean
Poisson deviance over a historical-mean baseline. Otherwise, official inference
uses the baseline mean for that target.

## Holdout decisions

| Target | Model MAE | Baseline MAE | Official source |
|---|---:|---:|---|
| Home half-time goals | 0.662 | 0.691 | Model |
| Away half-time goals | 0.649 | 0.659 | Model |
| Home shots | 4.178 | 4.126 | Baseline |
| Away shots | 3.507 | 3.920 | Model |
| Home shots on target | 1.954 | 1.906 | Baseline |
| Away shots on target | 1.678 | 1.742 | Model |
| Home corners | 2.287 | 2.428 | Model |
| Away corners | 2.125 | 2.264 | Model |
| Home fouls | 2.713 | 2.725 | Baseline |
| Away fouls | 2.850 | 2.811 | Baseline |
| Home yellow cards | 1.052 | 1.066 | Model |
| Away yellow cards | 1.120 | 1.099 | Baseline |
| Home red cards | 0.120 | 0.107 | Baseline |
| Away red cards | 0.130 | 0.114 | Baseline |

The raw models' average target MAE was 1.7877 versus 1.8327 for using baselines
everywhere. After choosing the safer source independently for every target, the
official mixed system's average target MAE is 1.7749.

## Inference contract

For every fixture, the artifact returns:

- one non-negative mean per supported statistic;
- one non-negative 90% plausible interval per statistic;
- the selected model or baseline source encoded in the immutable artifact.

Shots on target are capped at total shots for the same team. Phase 13 remains
responsible for sampling integers, building one correlated event sequence, and
ensuring the final event totals match the stored simulation statistics.

## Reproduction

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\train-match-statistics.ps1 -OutputFormat human
```

The full artifact is ignored under
`artifacts/models/match-statistics/detailed-statistics-v1-42e73adec486/`.
The compact committed evidence is
`data/contracts/models/match-statistics-summary.json`.

## Limitations

- Possession needs a new historically licensed or live-collected target source.
- Provider xG needs a distinct historical target source and must remain clearly
  separated from Phase 7 model-produced expected goals.
- Independent target models do not learn correlations such as shots leading to
  corners or cards following fouls.
- Phase 13 must enforce joint match consistency when it generates events.
