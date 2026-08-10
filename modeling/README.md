# Prem Engine Modeling

Production modeling code lives in `prem_engine_modeling`; notebooks are not a
runtime dependency. The Phase 6 baseline provides:

- a strict loader for the Phase 5 historical export;
- deterministic three-outcome Davidson-Elo probabilities;
- chronological outcome availability and season carryover;
- validation-only parameter selection;
- untouched two-season holdout evaluation;
- accuracy, log loss, Brier, ranked probability, and calibration metrics;
- immutable, versioned inference artifacts.

From the repository root, run the baseline yourself with:

```powershell
.\scripts\train-baseline.ps1
```

The command does not require Docker or a database. It reads the ignored Phase 5
training export and writes the trained model plus its full evaluation report to
ignored `artifacts/models/elo/`.

See `docs/phase-6/ELO_BASELINE.md` for the split policy, formulas, reference
results, limitations, and manual setup instructions.

Phase 7 adds a dynamic Poisson attack/defence model, an evaluated Dixon-Coles
low-score correction, expected goals, normalized scoreline distributions, and
derived H/D/A probabilities. Train it with the human-readable default report:

```powershell
.\scripts\train-goal-model.ps1
```

Use `-OutputFormat json` for machine-readable terminal output. The detailed
evaluation is always stored under ignored `artifacts/models/goals/`. See
`docs/phase-7/GOAL_MODEL.md` for formulas, metric definitions, reference results,
limitations, and manual-training instructions.

Phase 8 replays the historical dataset with an exact 24-hour prediction cutoff
and exports 74 model-ready Elo, goal-strength, rolling-form, venue, schedule,
promotion, confidence, and missingness features. Generate and validate it with:

```powershell
.\scripts\build-features.ps1
```

The default human report explains coverage and cutoff safety. Use `-OutputFormat
json` for automation and `-Force` to explicitly replace an existing ignored
export. See `docs/phase-8/FEATURE_ENGINEERING.md` for the complete contract.

Phase 9 tests regularized multinomial logistic regression and constrained
histogram gradient boosting with chronological selection and a separate
temperature-calibration season. Run the human-readable comparison with:

```powershell
.\scripts\train-tabular-model.ps1
```

The reference candidate is rejected because it does not beat the established
holdout benchmarks. Its immutable artifact remains research evidence and carries
an explicit non-approved promotion status. See
`docs/phase-9/CALIBRATED_TABULAR_MODEL.md` for the full decision.

Phase 10 adds 26 player-history, expected-lineup, availability, replacement,
bench, suspension, and transfer-uncertainty features. Build the 100-feature
dataset and run the coverage-gated trainer with:

```powershell
.\scripts\export-player-context.ps1
.\scripts\build-player-features.ps1
.\scripts\train-player-impact-model.ps1
```

The historical FPL import now supplies 66,665 player performances and passes the
coverage gate at 96.0%. The reference player model trained successfully but was
rejected because it did not improve the Phase 7 goal benchmark. See
`docs/phase-10/PLAYER_IMPACT_AVAILABILITY.md`.

Phase 11 evaluates non-negative convex blends of the Elo, goal, tabular, and
player forecasts. Run its chronological weight selection and calibration with:

```powershell
.\scripts\train-ensemble-model.ps1
```

The selected reference blend was also rejected, leaving Phase 7 as the approved
forecasting benchmark. Scoreline outcome-partition rescaling is implemented for
any future ensemble that passes promotion. See `docs/phase-11/ENSEMBLE_MODEL.md`.

Phase 12 trains independent regularized Poisson models for 14 supported
home/away count targets and falls back to historical means wherever a model does
not improve both MAE and Poisson deviance. Run it with:

```powershell
.\scripts\train-match-statistics.ps1
```

The artifact returns non-negative means and 90% plausible ranges. Possession and
provider xG are explicitly unsupported because the historical source has no
labels for them. See `docs/phase-12/DETAILED_STATISTICS.md`.

Phase 15 appends 34 prior-only formation, continuity, shot, corner, and foul
features to the base and player feature contracts. It never assigns subjective
tactical labels. Build the readiness export and then train manually with:

```powershell
.\scripts\build-tactical-features.ps1 -Force
.\scripts\train-tactical-model.ps1
```

The human report compares the candidate with Phase 6 Elo and Phase 7 goals on
the untouched holdout. The reference candidate was rejected at 1.0794 log loss
versus Phase 7's 1.0089, so Phase 7 remains official. See
`docs/phase-15/TACTICAL_INFERENCE_AND_REAL_UI.md`.
