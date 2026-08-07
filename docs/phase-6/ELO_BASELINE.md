# Phase 6 Elo Baseline

Date: 2026-08-07

## Outcome

Phase 6 establishes the first trained forecasting model and the benchmark that
future models must beat. It is a deterministic, online Elo-style team-strength
model with a Davidson draw extension. It produces home-win, draw, and away-win
probabilities; it does not yet predict goals or scorelines.

A controlled reference run evaluated 432 parameter configurations and selected
`elo-v1-d3b412bf866f`. On the untouched 760-match holdout covering 2024/25 and
2025/26, it achieved 50.26% result accuracy, 1.0112 log loss, and a 0.6071
multiclass Brier score.

## Dataset and chronological split

The model consumes the Phase 5 `historical_training_matches.csv` contract:

| Purpose | Seasons | Matches |
| --- | --- | ---: |
| Establish rating history | 2020/21-2022/23 | 1,140 |
| Select parameters | 2023/24 | 380 |
| Final untouched holdout | 2024/25-2025/26 | 760 |

The loader verifies exact UUIDs, timezone-aware timestamps, nonnegative scores,
result/score agreement, unique matches, chronological ordering, season blocks,
and the `lagged_history_only` flag. It rejects any training export containing
odds columns.

Changing either holdout season cannot change the chosen configuration because
the tuner operates on a dataset prefix that ends with 2023/24. Once this Phase 6
reference run was evaluated, the holdout became consumed benchmark evidence; it
must not be repeatedly consulted to hand-tune the baseline.

## Time-safe walk-forward process

For every fixture, the evaluator performs these operations in order:

1. Apply earlier match results only when `available_after < kickoff_at`.
2. Regress established ratings when a new season begins.
3. Read the home and away pre-match ratings.
4. Generate all three result probabilities.
5. Record the prediction when the fixture belongs to the scored period.
6. Queue the actual result until its `available_after` timestamp.

Consequently, simultaneous fixtures cannot influence one another, and a match
that has kicked off but is not yet available cannot enter another prediction.

## Probability model

Let `d` be the home rating plus home advantage minus the away rating:

```text
q = 10 ** (d / rating_scale)
draw_term = draw_propensity * sqrt(q)

P(home) = q / (q + draw_term + 1)
P(draw) = draw_term / (q + draw_term + 1)
P(away) = 1 / (q + draw_term + 1)
```

This is Davidson's draw extension to a Bradley-Terry strength comparison. The
three values are validated to be within `[0, 1]` and to sum to one.

After a result becomes available, the home rating change is:

```text
delta = K * margin_multiplier * (actual_score - expected_score)
margin_multiplier = 1 + margin_weight * log(1 + absolute_goal_margin)
```

The away rating receives the opposite change, preserving the combined rating.
At a season boundary, each known club is regressed toward the 1500-point league
mean using the season-carryover parameter. Newly promoted clubs begin at 1500.

## Parameter selection

The grid contains 432 configurations:

- K-factor: 12, 20, 28, or 36.
- Home advantage: 40, 60, 80, or 100 rating points.
- Draw propensity: 0.50, 0.65, or 0.80.
- Margin weighting: 0, 0.25, or 0.50.
- Season carryover: 0.75, 0.85, or 0.95.

Configurations are ranked first by 2023/24 log loss, then Brier score, then a
deterministic configuration ordering. The selected configuration is:

| Parameter | Selected value |
| --- | ---: |
| K-factor | 20 |
| Home advantage | 80 |
| Draw propensity | 0.65 |
| Margin weight | 0.50 |
| Season carryover | 0.95 |
| Initial rating | 1500 |
| Rating scale | 400 |

Margin weight and season carryover reached the upper edge of this deliberately
small baseline grid. That is evidence for later experimentation, not permission
to widen the grid using the consumed holdout seasons.

## Reference evaluation

Probability metrics are primary; accuracy discards probability quality and the
uniform comparator's tied pick resolves deterministically to the home outcome.

| Model | Accuracy | Log loss | Brier | Ranked probability |
| --- | ---: | ---: | ---: | ---: |
| Three-outcome Elo | 50.26% | 1.0112 | 0.6071 | 0.2069 |
| Historical league prior | 41.71% | 1.0833 | 0.6560 | 0.2313 |
| Uniform one-third | 41.71% | 1.0986 | 0.6667 | 0.2346 |

Against the historical-prior baseline, Elo improved log loss by approximately
6.7%, Brier score by approximately 7.4%, and picked 8.55 percentage points more
results correctly.

Per-season holdout results:

| Season | Accuracy | Log loss | Brier |
| --- | ---: | ---: | ---: |
| 2024/25 | 52.11% | 0.9926 | 0.5943 |
| 2025/26 | 48.42% | 1.0298 | 0.6199 |

Holdout expected calibration error was 0.0436 using ten probability bins across
the three one-vs-rest outcome observations. The full ignored evaluation report
contains bin counts, mean probabilities, and observed frequencies.

The decline in 2025/26 is retained openly. Elo is a useful baseline, not the
final production forecast.

## Manual training

The reference model binary is deliberately not committed or copied into the
visible repository. Your first run will create it.

From `C:\Users\USER\Documents\Refa\Code\Prem-Engine`:

1. Create a Python 3.12 environment if needed:

   ```powershell
   py -3.12 -m venv .venv
   ```

2. Activate it and install the project:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   python -m pip install -e ".[dev]"
   ```

3. Confirm the ignored Phase 5 export is present:

   ```powershell
   Test-Path .\data\processed\historical_training_matches.csv
   ```

4. Train and evaluate:

   ```powershell
   .\scripts\train-baseline.ps1
   ```

The wrapper checks the environment and dataset, then runs
`modeling/scripts/train_elo_baseline.py`. Docker and PostgreSQL are not needed.

The output directory will be:

```text
artifacts/models/elo/elo-v1-d3b412bf866f/
  model.joblib
  evaluation.json
```

The directory is ignored by Git. The writer never overwrites an existing model
version. To keep another manual run separately:

```powershell
.\scripts\train-baseline.ps1 -ArtifactRoot artifacts/manual-runs/elo
```

The model version is stable for a dataset checksum and selected configuration.
The binary checksum can also depend on the Python/joblib environment, so the
version identifier—not a cross-environment byte comparison—is the primary model
identity.

Only load trusted local `joblib` artifacts. Python serialization is not safe for
untrusted files.

## Automated guarantees

Tests cover:

- probability bounds and sums;
- home-advantage direction;
- zero-sum rating updates and margin behavior;
- season regression and artifact restoration;
- chronological dataset validation;
- unavailable and simultaneous-result leakage;
- test-outcome isolation from parameter selection;
- deterministic repeated training;
- metric calculations and calibration bins;
- immutable artifact paths.

## Current limitations

- Elo models overall result strength, not attacking and defensive goal rates.
- It does not produce expected goals or scoreline probabilities.
- It does not yet use shots, lineups, injuries, transfers, or tactical features.
- Club promotion strength is initialized at the league mean.
- Calibration is measured but not adjusted in this baseline.

Phase 7 will introduce separate home/away Poisson goal models and convert their
score matrix into expected goals, result probabilities, and correct-score
distributions. Elo remains the benchmark that the goals model must outperform.
