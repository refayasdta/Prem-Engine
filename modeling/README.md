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

The current reference inputs contain no normalized historical player
performances, so the trainer prints `TRAINING SAFELY BLOCKED` and writes no model
artifact. When coverage passes, the same command performs chronological candidate
selection, calibration, holdout comparison, and promotion. See
`docs/phase-10/PLAYER_IMPACT_AVAILABILITY.md`.
