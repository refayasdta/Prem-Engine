# Model Evidence Contracts

This directory contains small, reviewable summaries of completed training runs.
It never contains executable model binaries or full prediction-level reports.

Model binaries and detailed evaluation reports are written under ignored
`artifacts/`. They are versioned by the dataset checksum, model contract, and
selected configuration. Production storage will later upload approved artifacts
to private Cloudflare R2.

Only load `joblib` artifacts created by this project in a trusted environment.
Python serialization formats must not be loaded from untrusted sources.
