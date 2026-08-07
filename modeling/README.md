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
