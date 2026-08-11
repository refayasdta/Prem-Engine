# Phase 16A: Core product UI

Phase 16A turns the forecasting pipeline into a coherent public product without
changing any model, prediction, or simulation rules. Phase 7 remains the only
approved outcome and scoreline model.

## Delivered routes

- `/` is the product dashboard and explains the T-24 lifecycle.
- `/fixtures` lists all canonical upcoming fixtures grouped by local date.
- `/matches/{match_uuid}` shows the real club identities, official prediction,
  expected lineups, stored events, and revealed statistics for one match.
- `/simulation-preview` remains an isolated fictional developer lab and is not
  linked from the public product navigation.

## Data integrity rules

The dashboard and fixture index read only `GET /api/matches/upcoming`. Official
match pages read only `GET /api/matches/{match_uuid}/forecast`. If either source
is empty or unavailable, the interface shows an explicit state; it never fills
the gap with sample clubs, players, scores, or events.

Before T-24, the match page shows a countdown and score placeholders rather than
a misleading `0:0`. At T-24, the backend automatically creates and locks the
prediction and complete simulation. The browser has no simulate, replay-speed,
or restart control. It reveals the stored sequence over the same fixed 60-second
presentation for every viewer.

Postponed matches state that the former forecast is void. The replacement
forecast is generated 24 hours before the revised kickoff under the established
lifecycle policy.

## Visual system

All interface surfaces, text, borders, charts, and interaction states use only:

- midnight `#000505`
- deep violet `#3b3355`
- slate violet `#5d5d81`
- mist `#bfcde0`
- paper `#fefcfd`

Official club crests retain their natural colors. The supplied commercial site
reference informed hierarchy and card placement only; no external components or
assets were copied.

The UI has a shared header and footer, skip navigation, visible keyboard focus,
reduced-motion behavior, responsive layouts, loading skeletons, empty and API
failure states, a route-level error boundary, and a not-found page. Share
metadata uses a project-owned 1200-by-630 social preview at `frontend/public/og.png`.

## Boundaries

Phase 16A does not add or alter standings, post-match evaluation, model training,
deployment, scheduled production infrastructure, or monitoring.

- Phase 16B will add the simulated and real-world tables plus evaluation views.
- Phase 16C will add hosting, production scheduling, monitoring, backups, and
  operational documentation.

## Local verification

With PostgreSQL and the backend available:

```powershell
cd frontend
pnpm dev
```

Open `http://localhost:3000`. If the database has no upcoming fixtures, the
honest empty state is the expected behavior.
