# Phase 7 Goal Model

Phase 7 adds a deterministic, leakage-safe model for home goals, away goals,
scorelines, and match outcomes. It complements the Phase 6 Elo benchmark: Elo
models overall result strength, while this model separately tracks attacking and
defensive goal strength.

## What the model uses

For every club, the model maintains two pre-match values:

- attack strength, updated from goals scored versus expectation;
- defence strength, updated from goals conceded versus expectation.

It also uses a league base goal rate, home advantage, learning rate, seasonal
carryover, and an optional Dixon-Coles correction for low scores. Its form signal
is implicit in the chronological online updates: recent surprises change the
current attack and defence values.

It does not yet use injuries, suspensions, transfers, players, expected lineups,
tactics, betting odds, or post-match statistics as prediction features.

## Expected-goal equations

Before a fixture, the unbounded scoring intensities are:

```text
home_xg = base_rate * exp(home_advantage + home_attack - away_defence)
away_xg = base_rate * exp(away_attack - home_defence)
```

The production implementation bounds each intensity between 0.05 and 8.0 goals
for numerical safety. Independent Poisson probabilities are calculated for each
home/away score combination from 0 through 10 goals.

The Dixon-Coles factor can adjust 0-0, 0-1, 1-0, and 1-1 probabilities. All
score probabilities are then normalized. The home-win, draw, and away-win
probabilities are sums over the relevant parts of that matrix.

## Chronological update policy

A result can update strengths only when:

```text
completed_match.available_after < target_fixture.kickoff_at
```

Consequences:

- the current match can never be one of its own features;
- future matches cannot affect earlier predictions;
- simultaneous or overlapping fixtures cannot leak results into one another;
- a completed result can affect later fixtures in the same season;
- strengths regress toward neutral between seasons using the selected carryover.

For a home-team scoring error, half the update changes the home attack and half
changes the away defence. Away scoring updates the reciprocal pair. Individual
updates and strengths are bounded to keep extreme scores numerically stable.

## Model selection and holdout

The six seasons keep the Phase 6 split:

| Purpose | Seasons | Used for parameter selection? |
|---|---|---:|
| Historical state | 2020/21-2022/23 | Indirectly |
| Validation | 2023/24 | Yes |
| Untouched holdout | 2024/25-2025/26 | No |

The default grid tests 162 configurations across:

- learning rate: 0.015, 0.03, 0.06;
- base goal rate: 1.25, 1.35, 1.45;
- home advantage: 0.10, 0.18, 0.26 log-goal units;
- Dixon-Coles rho: -0.12, -0.06, 0.0;
- season carryover: 0.80, 0.95.

Validation scoreline negative log-likelihood chooses the configuration. Outcome
log loss is the deterministic tie-breaker. Test seasons cannot affect either
decision.

## Metrics

The human report uses the following measures:

| Label | Meaning | Better direction |
|---|---|---:|
| Goal MAE | Average absolute goal error per team | Lower |
| RMSE | Goal error with extra penalty for large misses | Lower |
| Exact score | Top scoreline equals the real score | Higher |
| Score NLL | Negative log probability of the real score | Lower |
| Outcome acc | Highest H/D/A probability is correct | Higher |
| Outcome NLL | Negative log probability of the real H/D/A result | Lower |

The detailed JSON also contains Brier score, ranked probability score,
calibration error, and calibration bins for the derived H/D/A probabilities.

## Reference run

The reference dataset contains 2,280 matches with SHA-256:

```text
9cee9fad4b81f79a3c665872d7b24de2973d4e4195122813ccb6aabbbfd93929
```

The selected model is `goals-v1-156511483a94`:

| Parameter | Selected value |
|---|---:|
| Learning rate | 0.03 |
| Base goal rate | 1.45 |
| Home advantage | 0.18 |
| Dixon-Coles rho | 0.0 |
| Season carryover | 0.95 |

The zero rho means the Dixon-Coles correction was evaluated but did not improve
validation scoreline likelihood for this dataset and model family.

### Holdout comparison

| Model | Goal MAE | RMSE | Exact score | Score NLL | Outcome accuracy | Outcome NLL |
|---|---:|---:|---:|---:|---:|---:|
| Phase 7 goals | 0.915 | 1.138 | 11.45% | 2.933 | 49.87% | 1.009 |
| League-average goals | 0.971 | 1.184 | 12.11% | 3.009 | 41.71% | 1.080 |
| Phase 6 Elo | N/A | N/A | N/A | N/A | 50.26% | 1.011 |

The goal model improves mean error, RMSE, scoreline likelihood, and outcome
probability likelihood. Its single most likely exact score is 0.66 percentage
points worse than the league baseline, and outcome accuracy is 0.39 points below
Elo. This is a transparent mixed result: probability quality improves, but the
top discrete pick does not improve on every metric.

## Manual training

From the repository root, activate the Python 3.12 environment and ensure the
project is installed:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Run Phase 7:

```powershell
.\scripts\train-goal-model.ps1
```

The default terminal output is formatted for a human. It shows progress,
chronological splits, selected parameters, comparable metric rows, a plain-
language verdict, paths, checksums, and limitations.

For machine-readable terminal output instead:

```powershell
.\scripts\train-goal-model.ps1 -OutputFormat json
```

The immutable outputs are written to:

```text
artifacts/models/goals/<model-version>/model.joblib
artifacts/models/goals/<model-version>/evaluation.json
```

The artifact directory is ignored by Git. A repeated run with identical inputs
selects the same configuration and version, but the writer refuses to overwrite
an existing version. Use a separate root for an experiment:

```powershell
.\scripts\train-goal-model.ps1 -ArtifactRoot artifacts/manual-runs/goals-run-2
```

Docker and PostgreSQL are not required for model training.

## Artifact contents

`model.joblib` contains only the trusted inference state:

- schema and model versions;
- dataset checksum and training cutoff;
- selected configuration;
- current attack and defence strengths;
- club UUID-to-name mapping.

`evaluation.json` contains the full configuration, validation and holdout
metrics, season-level metrics, calibration bins, baseline comparisons, feature
policy, limitations, artifact checksum, and creation time.

Only load `joblib` files produced by this project in a trusted environment.

## Next model step

Later phases can add player availability, expected lineups, injuries,
suspensions, transfers, and tactical context as explicit adjustments to these
base scoring intensities. Phase 7 deliberately establishes a measurable team-
level goal foundation first.
