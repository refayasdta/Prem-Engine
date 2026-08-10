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

Phase 10 adds `player-impact-summary.json`. The player-enhanced training pipeline
is complete, but no model artifact exists because the reference six-season
dataset currently contains zero normalized historical player performances. It
must not be described as a trained or promoted model.
