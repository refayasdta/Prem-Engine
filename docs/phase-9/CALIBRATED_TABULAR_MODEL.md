# Phase 9 Calibrated Tabular Model

Phase 9 evaluates whether general-purpose tabular classifiers improve Premier
League H/D/A probabilities when trained on the 74 approved Phase 8 features.

The result is intentionally preserved even though the standalone candidate was
rejected: temperature calibration helped, but the calibrated model did not beat
the established Elo and goal-model benchmarks on the untouched holdout.

## Safety and feature contract

The loader first applies the full `prematch-features-v1` validation. It then
selects only `PREMATCH_FEATURE_COLUMNS` in their declared order.

It cannot train on:

- match, team, or provider identities;
- club names;
- timestamps or provenance counts;
- targets or final scores;
- undeclared columns;
- betting odds.

Missing values are imputed separately inside every training fold. Logistic
features are standardized inside the same fold. Validation, calibration, and
holdout rows cannot affect medians or scaling parameters used by an earlier
training period.

## Chronological design

Phase 9 separates algorithm selection from probability calibration:

| Stage | Train | Evaluate/use |
|---|---|---|
| Development fold 1 | 2020/21 | 2021/22 |
| Development fold 2 | 2020/21-2021/22 | 2022/23 |
| Final base fit | 2020/21-2022/23 | Model state |
| Calibration | Base model frozen | 2023/24 |
| Holdout | Model and calibrator frozen | 2024/25-2025/26 |

Candidate selection uses mean log loss across the two development folds. Brier
score and the stable candidate ID are deterministic tie-breakers. The calibration
and holdout targets cannot alter this selection.

## Candidates

Twelve deterministic candidates are evaluated:

- multinomial logistic regression with `C` equal to 0.03, 0.1, 0.3, or 1.0;
- histogram gradient boosting across two learning rates, two leaf limits, and
  two L2 regularization values.

All stochastic operations use seed 42. Gradient boosting disables data-dependent
early stopping so repeated training follows the same path.

The logistic pipeline is:

```text
fold-local median imputation
        -> fold-local standardization
        -> regularized multinomial logistic regression
```

The boosting pipeline uses fold-local median imputation followed by a constrained
histogram gradient-boosting classifier.

## Temperature calibration

The selected base model is frozen before the 2023/24 calibration season.
Temperature scaling applies one positive value `T` to all class logits:

```text
calibrated_probability = softmax(log(raw_probability) / T)
```

- `T > 1` softens overconfident predictions.
- `T < 1` sharpens underconfident predictions.
- `T = 1` leaves them unchanged.

The selected reference temperature is `1.2666685187`, meaning the model needed
less confident probabilities.

## Promotion gate

A Phase 9 model is promoted only when its calibrated holdout result:

1. improves log loss over the best of Phase 6 Elo and Phase 7 goals by at least
   0.005; and
2. also improves Brier score over that same benchmark.

A positive but smaller log-loss improvement becomes an ensemble candidate. A
non-positive improvement is rejected. Holdout metrics determine the deployment
verdict, not candidate selection or calibration.

Rejected artifacts remain loadable for controlled research, but their payload
contains:

```text
promotion_status = rejected
approved_for_official_forecasts = false
```

Downstream production code must not treat a rejected artifact as official.

## Reference result

Feature export SHA-256:

```text
b90c1eb11def7c0fe31d347b95cb9a029e4b1697d8de552f9fff4df3f2a3e6ba
```

Selected candidate:

```text
multinomial logistic regression, C = 0.03
```

### Calibration season

| Version | Accuracy | Log loss | Brier | RPS | ECE |
|---|---:|---:|---:|---:|---:|
| Before calibration | 57.89% | 0.9589 | 0.5616 | 0.1917 | 0.0388 |
| After calibration | 57.89% | 0.9508 | 0.5597 | 0.1915 | 0.0347 |

Calibration improved every probability-quality measure shown while leaving the
most likely class and therefore accuracy unchanged.

### Untouched holdout

| Model | Accuracy | Log loss | Brier | RPS | ECE |
|---|---:|---:|---:|---:|---:|
| Phase 9 calibrated | 48.16% | 1.0871 | 0.6545 | 0.2275 | 0.0995 |
| Phase 9 uncalibrated | 48.16% | 1.1502 | 0.6866 | 0.2406 | 0.1367 |
| Phase 6 Elo | 50.26% | 1.0112 | 0.6071 | 0.2069 | 0.0436 |
| Phase 7 goals | 49.87% | 1.0089 | 0.6043 | 0.2063 | 0.0183 |
| Historical prior | 41.71% | 1.0833 | 0.6560 | 0.2313 | 0.0235 |

The calibrated model is much safer than its uncalibrated version, but its log
loss is 0.0782 worse than Phase 7. It is therefore rejected as a standalone
forecasting model.

This outcome suggests that the current rolling features do not add enough stable
signal beyond the embedded Elo and goal probabilities. The coefficient report
also contains unintuitive effects, a warning that correlated features and
temporal change make interpretation fragile. These coefficients are associations,
not causal claims.

## Human-readable report

The terminal output includes:

- all candidate ranks and development scores;
- selected family and parameters;
- calibration temperature and before/after metrics;
- untouched holdout comparisons;
- season-level metrics;
- top coefficient or permutation influences;
- a plain promotion status and reason;
- artifact paths and checksums;
- current data limitations.

The detailed JSON retains every fold score, calibration bins, complete metrics,
feature contract, influences, benchmarks, and promotion evidence.

## Manual training

Ensure the Phase 8 export exists, then run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
.\scripts\train-tabular-model.ps1
```

Default outputs:

```text
artifacts/models/tabular/<model-version>/model.joblib
artifacts/models/tabular/<model-version>/evaluation.json
```

For machine-readable terminal output:

```powershell
.\scripts\train-tabular-model.ps1 -OutputFormat json
```

Artifacts are immutable. Use a separate root for another manual experiment:

```powershell
.\scripts\train-tabular-model.ps1 -ArtifactRoot artifacts/manual-runs/tabular-run-2
```

Docker and PostgreSQL are not required.

## Limitations

Phase 9 still excludes player ability, injuries, suspensions, transfers, expected
lineups, and tactical inputs. Six seasons and 2,280 matches are also a small
sample for complex machine-learning models. The rejected result must not be
presented as an improvement merely because it uses a more complex algorithm.
