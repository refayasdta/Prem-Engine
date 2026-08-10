# Phase 11 ensemble model

Date: 2026-08-10

## Outcome

Phase 11 implements and evaluates a calibrated convex probability ensemble over
the completed Phase 6, 7, 9, and 10 forecasting components. Training completed,
but the ensemble was **rejected** because it did not improve the Phase 7 goal
model on the holdout. Phase 7 remains the approved forecasting benchmark.

## Components

The ensemble consumes ordered home/draw/away probabilities from:

- Phase 6 Davidson-Elo;
- Phase 7 dynamic Poisson/Dixon-Coles goals;
- Phase 9 calibrated tabular classification;
- Phase 10 calibrated player-impact classification.

Rejected Phase 9 and Phase 10 artifacts may be evaluated as research components,
but they cannot become official independently. The Phase 11 artifact carries its
own promotion status and cannot be loaded as an approved official ensemble after
a rejected evaluation.

## Leakage controls

The 286 non-negative weight combinations use a 0.1 grid and always sum to one.
Weights were selected only from chronological development folds:

1. train 2020/21, validate 2021/22;
2. train 2020/21–2021/22, validate 2022/23.

The selected Phase 9 and Phase 10 components were then fitted on 2020/21–2022/23.
Their individual temperatures and the final ensemble temperature were fitted on
2023/24. The final comparison used 760 fixtures from 2024/25 and 2025/26.

Changing holdout targets cannot change selected weights, calibration
temperatures, or holdout probabilities. Tests enforce that isolation.

## Selected blend

| Component | Weight | Component temperature |
|---|---:|---:|
| Phase 6 Elo | 90% | 1.0000 |
| Phase 7 goals | 0% | 1.0000 |
| Phase 9 tabular | 0% | 1.2667 |
| Phase 10 player | 10% | 1.2665 |

The ensemble temperature was 0.9185. Its mean development-fold log loss was
0.9754. A zero weight is a valid outcome: models are never forced into the blend.

## Holdout result

Lower is better for log loss, Brier, RPS, and ECE. Higher is better for accuracy.

| Model | Accuracy | Log loss | Brier | RPS | ECE |
|---|---:|---:|---:|---:|---:|
| Phase 11 ensemble | 50.00% | 1.0178 | 0.6116 | 0.2088 | 0.0492 |
| Phase 6 Elo | 50.26% | 1.0112 | 0.6071 | 0.2069 | 0.0436 |
| Phase 7 goals | 49.87% | 1.0089 | 0.6043 | 0.2063 | 0.0183 |
| Phase 9 tabular | 48.16% | 1.0871 | 0.6545 | 0.2275 | 0.0995 |
| Phase 10 player | 45.53% | 1.0931 | 0.6548 | 0.2266 | 0.0865 |

The ensemble's log loss was 0.0089 worse than Phase 7. It also had worse Brier,
RPS, and calibration error. Its 0.13 percentage-point accuracy advantage over
Phase 7 is too small to offset the poorer probability quality. Promotion was
therefore rejected.

## Scoreline consistency

The ensemble module includes outcome-partition rescaling for future promoted
ensembles. It rescales the Phase 7 score matrix so that:

- all home-win scorelines sum to the ensemble home-win probability;
- all draw scorelines sum to the ensemble draw probability;
- all away-win scorelines sum to the ensemble away-win probability;
- the relative shape within each result group is preserved.

This prevents a future ensemble result forecast from contradicting the scoreline
distribution used by the simulator.

## Evaluation disclosure

The Phase 11 fitting code did not use 2024/25 or 2025/26 targets for weight
selection or calibration. However, benchmark results for those seasons had
already been inspected during Phases 9 and 10 before this ensemble was designed.
The result is useful historical evidence, but 2026/27 remains the next genuinely
unseen live validation season.

## Reproduction

From the repository root:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\train-ensemble-model.ps1 -OutputFormat human
```

The full model and evaluation are ignored local artifacts under
`artifacts/models/ensemble/ensemble-v1-9380bb2fdd5b/`. The compact committed
result is `data/contracts/models/ensemble-summary.json`.

## Decision

- Training status: `completed_rejected`.
- Approved for official forecasts: false.
- Current approved benchmark: Phase 7 goals.
- Next honest validation: live 2026/27 forecasts.
