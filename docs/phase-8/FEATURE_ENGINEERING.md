# Phase 8 Pre-Match Feature Engineering

Phase 8 creates one deterministic, model-ready feature row for every historical
fixture. Each row represents the information the production system could have
known at its official prediction time: exactly 24 hours before kickoff.

This phase does not train a new forecasting model. It builds the audited input
contract that later tabular, player-impact, and ensemble models will consume.

## Time and leakage contract

For fixture `F`:

```text
feature_cutoff_at = F.kickoff_at - 24 hours
```

A completed result may contribute only when:

```text
source.available_after < feature_cutoff_at
```

The comparison is strict. A result that becomes available exactly at the cutoff
is not eligible. The pipeline also prevents:

- the current fixture from entering its own features;
- future fixtures from changing earlier rows;
- simultaneous results from influencing one another;
- delayed results from being treated as known prematurely.

Every row stores its cutoff, latest eligible input timestamp, and eligible-result
count. The validator rejects any row whose provenance timestamp reaches or
crosses its cutoff.

## Export contract

Contract version: `prematch-features-v1`.

The CSV contains 89 columns:

- 12 identity and provenance columns;
- 74 model-ready feature columns;
- 3 target columns used only as training labels.

The target columns are:

```text
target_home_goals
target_away_goals
target_result
```

They are never included in `PREMATCH_FEATURE_COLUMNS`. Phase 9 must select the
74 declared feature columns explicitly rather than training on every CSV column.

## Feature groups

### Phase 6 result strength

- Home and away pre-match Elo ratings.
- Elo home-win, draw, and away-win probabilities.

The pipeline replays the selected Phase 6 configuration chronologically rather
than reading final ratings backward through history.

### Phase 7 goal strength

- Home and away attack strengths.
- Home and away defence strengths.
- Expected home and away goals.
- Goal-model home-win, draw, and away-win probabilities.

The selected Phase 7 model is likewise replayed from the beginning so each row
contains only its contemporary state.

### Rolling form

For each club:

- points in the last 3, 5, and 10 eligible matches;
- points per match over the last 5;
- goals for and against per match over the last 5 and 10;
- goal difference per match over the last 5;
- win, draw, and loss rates over the last 5;
- clean-sheet and failed-to-score rates over the last 5;
- home-only or away-only points per match over the last 5 at that venue;
- recent three-match points versus the preceding three-match period;
- points above or below the pre-match Elo expectation.

The opponent-adjusted feature is:

```text
actual league points - Elo expected league points
```

This distinguishes a strong result against a favored opponent from an expected
result against a weaker one.

### Schedule and fatigue

- Days since the club's most recent fixture played before the cutoff.
- Fixtures in the previous 7, 14, and 30 days.
- Previous fixtures in the current season.
- Early-season flag for the first five fixtures.

Fixtures whose kickoff has not occurred by the feature cutoff are not counted as
played, even when they were already present in the historical schedule.

### Promotion, history, and missingness

- Promoted/new-to-league flag based on absence from the previous season.
- Promotion-status-known flag because the first source season has no predecessor.
- Total eligible history count.
- Rolling-form sample count.
- History confidence, reaching 1.0 after 20 eligible matches.
- Explicit missing-rest and insufficient-five-match-form flags.

Missing early history remains blank in the CSV. It is not silently replaced with
zero, because zero is a legitimate football value. Later model pipelines must
impute missing values inside their training folds and retain the missingness
flags.

## Reference export

The six-season source contains 2,280 fixtures. The reference feature export has:

| Check | Result |
|---|---:|
| Model-ready features | 74 |
| Total columns | 89 |
| Rows | 2,280 |
| Rows per season | 380 |
| Cutoff violations | 0 |
| Cold-start rows | 20 |
| Rows without five-match history | 91 |

Reference feature SHA-256:

```text
b90c1eb11def7c0fe31d347b95cb9a029e4b1697d8de552f9fff4df3f2a3e6ba
```

The checksum changes if the historical input, feature configuration, column
order, value formatting, or feature logic changes.

## Manual generation

From the repository root, permit scripts in the current PowerShell process if
needed and activate the Python 3.12 environment:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Generate the feature dataset:

```powershell
.\scripts\build-features.ps1
```

Default outputs:

```text
data/processed/prematch_features.csv
data/processed/prematch_features.report.json
```

Both are ignored by Git. The terminal prints a short human report covering row
counts, features, cutoff violations, cold starts, missing early history, feature
groups, paths, checksum, and limitations.

Use machine-readable terminal output with:

```powershell
.\scripts\build-features.ps1 -OutputFormat json
```

The command refuses to overwrite an existing export unless explicitly asked:

```powershell
.\scripts\build-features.ps1 -Force
```

Docker and PostgreSQL are not required.

## Strict validation

`validate_feature_export` reopens a CSV and rejects:

- a changed or reordered schema;
- an unsupported contract version;
- missing or duplicate match UUIDs;
- naive or invalid timestamps;
- any cutoff other than 24 hours;
- any eligible-input timestamp at or after the cutoff;
- non-numeric or non-finite feature values;
- negative goals or invalid result targets;
- target results that contradict their scores;
- non-chronological rows or repeated season blocks.

## Limitations

Phase 8 intentionally excludes:

- player strength and individual statistics;
- injuries and suspensions;
- transfers and replacement quality;
- expected lineups;
- manager and tactical features;
- betting odds.

Those inputs require additional coverage audits and historical identity mapping.
The explicit versioned feature contract lets later phases add them without
silently changing the meaning of this baseline.

## Next phase

Phase 9 can train calibrated tabular result models using this export. Candidate
models should begin with regularized multinomial logistic regression, then test a
tree-based model. They must use chronological validation, fold-local imputation,
and retain a candidate only when it improves probability quality over Phases 6
and 7.
