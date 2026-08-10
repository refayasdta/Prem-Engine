# Model Evidence Contracts

This directory contains small, reviewable summaries of completed training runs.
It never contains executable model binaries or full prediction-level reports.

Model binaries and detailed evaluation reports are written under ignored
`artifacts/`. They are versioned by the dataset checksum, model contract, and
selected configuration. Production storage will later upload approved artifacts
to private Cloudflare R2.

Only load `joblib` artifacts created by this project in a trusted environment.
Python serialization formats must not be loaded from untrusted sources.

Committed evidence summaries currently cover the Phase 6 Elo baseline and the
Phase 7 dynamic Poisson goal model. Full reports remain local artifacts.

Phase 9 adds a rejected calibrated tabular candidate as negative research
evidence. A committed summary may describe the experiment, but the binary remains
ignored and its payload explicitly states that it is not approved for official
forecasts.

Phase 10 adds `player-impact-summary.json`. The historical FPL import passed the
coverage gate and the player model was trained, but its artifact remains ignored
and rejected because it did not improve the Phase 7 goal benchmark.

Phase 11 adds `ensemble-summary.json`. It records the selected convex weights,
component and ensemble calibration, holdout metrics, scoreline-reconciliation
contract, and rejected promotion decision. Full artifacts remain ignored under
`artifacts/models/ensemble/`.

Phase 12 adds `match-statistics-summary.json`. It records coverage, per-target
Poisson selection, calibration, holdout comparison, model-or-baseline decisions,
unsupported targets, and the ignored detailed-statistics artifact identity.
