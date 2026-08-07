# Pre-Match Feature Evidence

This directory contains small reviewable contracts and evidence summaries, not
the full historical feature CSV.

Full feature exports live under ignored `data/processed/`. They include training
targets for evaluation, but model code must explicitly select the declared
`PREMATCH_FEATURE_COLUMNS` and must never treat identity, provenance, or targets
as model inputs.

Every version requires an exact cutoff policy, source and output checksums,
missingness summary, coverage counts, and a strict validator before it can be
used by a model-training phase.
