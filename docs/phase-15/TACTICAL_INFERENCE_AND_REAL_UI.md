# Phase 15: tactical inference and real-data match UI

Phase 15 adds auditable tactical proxies and connects the public match page to
the canonical Phase 14 forecast API. It does not invent teams or players when
the database has no fixture coverage.

## What is inferred

The tactical candidate uses 34 new prior-only features (17 per club):

- recent shots for and against, shots-on-target allowed, shot share, and shot
  accuracy;
- recent corners, corner share, and foul counts;
- position-group shape inferred from observed starting XIs;
- formation stability and starter continuity;
- explicit sample counts and coverage values.

“Formation” means the observed goalkeeper/defender/midfielder/attacker position
groups. Historical FPL classifications can describe a winger as a midfielder,
so a label such as `4-5-1` is a measurable position-group shape, not a claim
about the team’s in-possession structure. Shots and corners are style proxies.
Fouls are not relabelled as pressing.

All source observations must satisfy `available_after < feature_cutoff_at`.
The cutoff remains exactly 24 hours before kickoff. Missing early lineup history
is represented by sample and coverage fields rather than imputed tactical
labels. The source audit found one impossible shots-on-target value; the derived
rate caps that value at total shots while preserving and checksumming the raw
source row.

## Measured readiness

The reference feature build produced:

- 2,280 fixtures across six seasons;
- 134 total model features (74 base, 26 player, 34 tactical);
- 2,768 observed team starting XIs;
- 97.5% two-team style-history coverage;
- 58.7% two-team observed-shape coverage;
- zero feature-cutoff violations.

That passes the Phase 15 coverage gate. It permits training; it does not prove
the candidate will improve forecasting.

## Training outcome

The user completed the approved manual run on 2026-08-10. The selected
`logistic-c-0.03` candidate achieved 46.32% accuracy, 1.0794 log loss, 0.6481
Brier score, 0.2243 RPS, and 0.0768 ECE on the 760-match untouched holdout.
Phase 7 goals achieved 49.87% accuracy and 1.0089 log loss on the same matches.

The tactical candidate's log loss was 0.0705 worse, so the promotion gate
**rejected** it. Phase 7 remains the official outcome and scoreline model. The
real-data UI, expected-formation inference, coverage reporting, and future
retraining path remain part of the product; only the rejected tactical outcome
artifact is excluded from official forecasts. See
`data/contracts/models/TACTICAL_MODEL_TRAINING_RESULT.md` for the complete
decision record.

## Manual training

The user remains the model trainer. To reproduce the completed reference run,
build the ignored feature dataset first:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
.\scripts\build-tactical-features.ps1 -Force
```

Then start the chronological candidate evaluation yourself:

```powershell
.\scripts\train-tactical-model.ps1
```

The terminal report is deliberately human-readable. It shows the candidate
leaderboard, untouched-holdout accuracy/log loss/Brier/RPS/calibration, tactical
feature associations, the Phase 6 and Phase 7 benchmarks, and a plain promotion
verdict. A tactical candidate is official only if the stored report says
`PROMOTED`. If it says `REJECTED`, Phase 7 remains the outcome and scoreline
model. Artifacts and processed feature files remain ignored by Git.

## Real-data website path

The frontend now requests real canonical fixtures through its own server-side
proxy:

- `GET /api/matches/upcoming` lists upcoming database fixtures;
- `/matches/{match_uuid}` polls the Phase 14 synchronized forecast endpoint;
- club names, crests, expected lineups, players, probabilities, statistics, and
  revealed events come from the stored forecast;
- there is no simulate, replay, restart, seek, or speed button on official
  matches;
- the backend starts and locks the simulation automatically at T-24, and every
  viewer sees the same fixed 60-second presentation clock;
- postponed and cancelled states do not display a stale simulation.

Set `PREM_ENGINE_API_BASE_URL` in `frontend/.env.local` if the FastAPI service is
not running at `http://127.0.0.1:8000`.

The `/simulation-preview` route remains a clearly labelled fictional developer
lab. It is intentionally separate from all official fixture navigation. Phase
16 will complete the broader dashboard, both standings tables, responsive
polish, accessibility checks, deployment, and monitoring.
