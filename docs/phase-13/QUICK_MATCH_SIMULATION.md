# Phase 13: Stored quick-match simulation

Phase 13 converts one locked pre-match forecast into one complete, deterministic
match simulation. The backend generates the result, expected lineups, statistics,
and event sequence once. The browser only reveals that stored sequence over time;
it never decides what happens next.

## Inputs and authority

- The Phase 7 goal model remains authoritative for expected goals, outcome
  probabilities, and the sampled final score.
- The Phase 12 detailed-statistics model supplies count means for half-time goals,
  shots, shots on target, corners, fouls, yellow cards, and red cards.
- The expected-lineup contract supplies 11 starters and a bench for each team.
- A stored integer seed makes generation reproducible.

The Phase 10 player candidate and Phase 11 ensemble remain unpromoted. Phase 13
does not silently substitute either rejected model into the official outcome.

## Consistency rules

The generator reconciles every sampled match before it can be stored:

- Goals are shots on target, and shots on target are shots.
- Half-time goals equal goal events before the break and cannot exceed final goals.
- Each corner, foul, card, substitution, shot, and goal has a chronological event.
- Every event carries the score at that moment.
- The last event is full-time and its score equals the sampled result.
- A canonical SHA-256 checksum covers the complete locked payload.
- The same forecast and seed produce the same payload and checksum.

`validate_simulation_consistency` rejects altered, out-of-order, or internally
contradictory payloads. Phase 14 will call this generator from the scheduled
forecast lifecycle and persist the validated payload under the existing canonical
`match_uuid` and `prediction_version_uuid` relationships.

## Preview fixture

The tracked preview is explicitly fictional. It uses fixed model means, fixed
lineups, and seed `13082026` so every developer sees the same match. Its current
locked result is 0–2 across 74 stored events, with checksum:

```text
040c5348d2b9ef4e56ae8913c12f56cbe1e3411fcc2222929fed0d79e5bb8bc3
```

Regenerate it with:

```powershell
.\scripts\generate-simulation-preview.ps1
```

Then start the local site and open the player:

```powershell
cd frontend
pnpm dev
```

```text
http://localhost:3000/simulation-preview
```

Every presentation has a fixed one-minute duration: 25 seconds for the first
half, a 10-second half-time interval, and 25 seconds for the second half. The
preview provides play, pause, restart, and timeline seeking for testing, but no
speed control. The score, commentary, and statistics are calculated only from
events already revealed at the selected match time. The final payload exists
beforehand, but the interface does not expose future events during ordinary
playback.

## Postponements

The agreed lifecycle remains unchanged: if a fixture is postponed after its match
has been simulated, the active prediction, predicted lineup, and simulation are
voided. The stable internal `match_uuid` remains. A new official forecast and
simulation are generated 24 hours before the revised kickoff. Audit metadata is
handled by the lifecycle layer rather than by changing the deterministic generator.

## Verification

Phase 13 adds tests for deterministic output, seed variation, lineup constraints,
zero-count behavior, checksum tampering, chronological order, rolling score, final
score, and event/statistic reconciliation. Frontend linting, TypeScript checking,
production building, and browser inspection cover the replay page.
