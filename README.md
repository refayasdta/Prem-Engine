# Prem Engine

## Short description

Prem Engine is a self-contained Premier League forecasting and match-simulation application that
runs on your own computer. It synchronizes fixtures and results, forecasts scores and match
outcomes with the approved Phase 7 model, creates a saved simulation when a user presses Play, and
compares those predictions with real results. Each installation owns its database, models, and
simulation history; no Prem Engine cloud account or hosted server is required.

## Requirements

Only the following host software is required:

- **Git**, to download and update the repository.
- **Docker Desktop** on Windows or macOS, or **Docker Engine with Docker Compose v2** on Linux.
- A modern desktop browser such as Chrome, Edge, Firefox, or Safari.
- An internet connection for the first image build and for current football-data synchronization.
- A **KickoffAPI key** for current fixture synchronization. The application can start without one,
  but it remains in setup-required mode and Play stays disabled until current data is synchronized.

A phone is optional. It can open Prem Engine while it is connected to the same trusted local
network as the host computer after LAN access is enabled.

Python, Node.js, pnpm, PostgreSQL, and machine-learning libraries do **not** need to be installed on
the host. Docker provides them inside the application containers.

## Installation

1. Install Git and Docker, then start Docker.

2. Open PowerShell or another terminal and clone the repository:

   ```powershell
   git clone https://github.com/refayasdta/Prem-Engine.git
   cd Prem-Engine
   ```

3. Create your private local configuration file:

   ```powershell
   Copy-Item .env.example .env
   ```

   On macOS or Linux, use `cp .env.example .env` instead.

4. Open `.env` in a text editor and set your provider key:

   ```text
   KICKOFF_API_KEY=your_key_here
   ```

   Do not commit or share `.env`. Prem Engine keeps this key on the server side and does not return
   it to the browser.

5. Build and start the complete application:

   ```powershell
   docker compose up --build -d
   ```

   The first build can take several minutes. Compose starts PostgreSQL, applies database
   migrations, initializes the installation, and then starts the API, frontend, and synchronization
   and model-training worker.

6. Confirm that the services are healthy:

   ```powershell
   docker compose ps
   docker compose --profile operations run --rm operations diagnostics
   ```

7. Open [http://localhost:3000](http://localhost:3000) in your browser. The first synchronization
   may take a short time. Prem Engine will show its real setup or synchronization state while it is
   working instead of presenting old data as current.

For normal shutdown and restart, use:

```powershell
# Stop while preserving all local data
docker compose down

# Start again with the existing database, models, and simulations
docker compose up -d
```

> **Warning:** `docker compose down -v` permanently deletes the local database, raw captures,
> simulations, and locally trained model artifacts. It is a destructive reset, not a normal stop
> command.

Backup, restore, troubleshooting, logs, upgrades, offline recovery, and trusted-LAN phone setup are
documented in the [local operations runbook](docs/deployment/LOCAL_OPERATIONS.md).

## FAQ

### Is Prem Engine free?

Prem Engine does not require paid application hosting. You run it on your own computer. You may
still have normal hardware, electricity, internet, or external data-provider costs, and the terms
and pricing of a provider can change independently of this project.

### Can it run without a KickoffAPI key?

The application will start, preserve bundled reference data, and display a setup-required state.
It cannot claim that current fixtures are fresh, so Play remains disabled until a successful
current-data synchronization. FPL endpoints are used as a bounded fallback for incomplete current
squad data; they do not replace KickoffAPI as the primary fixture source.

### Why does it say that local fixture data may be stale?

Fixture data becomes stale four hours after the last successful reconciliation. The warning can
appear when the computer or Docker was off, the provider is unavailable, the API key is missing or
invalid, the request quota has been reached, or the worker has not completed startup
reconciliation. Saved data remains visible, but Play is disabled until synchronization succeeds.

### How does Prem Engine stay within provider usage limits?

It records requests in the local database before sending them, synchronizes fixtures in bounded
batches, refreshes the active fixture window every four hours, and refreshes player context daily.
KickoffAPI has a configured hard ceiling of 100 requests per day; Prem Engine stops earlier at its
85-request operational ceiling and also enforces a minute limit. Retries cannot bypass this ledger.
The FPL squad fallback has a separate, smaller request budget.

### When can I simulate a match?

Play unlocks exactly 24 hours before the current official kickoff and remains available through 45
minutes after kickoff. The backend checks the time window, current schedule revision, and fixture
freshness. A postponed or rescheduled fixture receives a new valid Play window.

### Why is a simulation on my phone different from—or missing on—my laptop?

This is intentional. Each browser receives a random local device identity, and simulations,
simulated standings, and coverage are saved separately for that identity. There are no accounts or
automatic cross-device synchronization. Replaying the same fixture in the same browser returns the
same stored simulation rather than generating a new result.

### Is the one-minute match replay running in real time?

No. It is a presentation of an already generated, immutable match payload. The clock advances
steadily through a compressed match, including its halftime transition. Backgrounding a browser can
temporarily delay screen updates, but reopening it restores the correct presentation position.

### What does “live connection interrupted” mean?

The browser temporarily lost its update connection to the local API. Prem Engine continues showing
the most recent verified state while retrying. On a phone, confirm that the host computer and Docker
are running, both devices remain on the same trusted Wi-Fi network, and the firewall still permits
the configured LAN port.

### Where is my data stored, and will restarting delete it?

Fixtures, results, model versions, forecasts, simulations, standings, and evaluations are stored in
local Docker volumes. Normal stop, restart, rebuild, and computer reboot operations preserve those
volumes. Clearing browser storage creates a new device identity, while deleting Docker volumes
removes the installation's stored application data.

### Can I use Prem Engine away from my home network?

Not by default. The frontend initially binds only to `127.0.0.1`, and the project does not expose a
public hosted service. Trusted-LAN access is optional and documented in the
[local operations runbook](docs/deployment/LOCAL_OPERATIONS.md). Do not expose port 3000 to public
Wi-Fi or forward it directly through a router; the local edition does not provide user accounts.

### Where can I find the detailed technical documentation?

Start with the [cloneable local architecture](docs/deployment/CLONEABLE_LOCAL_ARCHITECTURE.md), the
[Phase 7 goal model](docs/phase-7/GOAL_MODEL.md), and the
[stored match simulation design](docs/phase-13/QUICK_MATCH_SIMULATION.md). The `docs` directory also
contains the complete historical phase and architecture record.

## How the model works

### Official forecast model

Prem Engine's approved outcome and scoreline model is the Phase 7 dynamic Poisson goal model. It
learns a separate attacking strength and defensive strength for every club and combines them with
the league scoring rate and home advantage. Before a fixture, it calculates the two teams'
expected goals approximately as:

```text
home expected goals = league rate × home advantage × home attack × away defence
away expected goals = league rate × away attack × home defence
```

The implementation uses an equivalent log-scale equation for numerical stability. It converts the
two expected-goal values into probabilities for every score from 0–0 through 10–10. Adding the
appropriate score probabilities produces the home-win, draw, and away-win probabilities. A
Dixon–Coles low-score correction was evaluated during model selection; the selected Phase 7
configuration uses a zero correction because a non-zero value did not improve validation results.

### Training without future-data leakage

Matches are processed in chronological order. A completed result may update team strength only if
that result was available before the fixture being predicted. Therefore, a match cannot train on
itself, a later result cannot influence an earlier prediction, and simultaneous fixtures cannot
leak results into one another. Strengths partially carry into a new season instead of either being
forgotten completely or treated as permanently unchanged.

Every fresh installation begins with the approved bundled model. After all non-postponed matches
in an eligible matchweek have accepted final results, the local worker fully retrains Phase 7 using
all eligible historical data plus current-season results known at that cutoff. Postponed matches do
not block later matchweeks. If the computer was offline for several matchweeks, the worker catches
up one cutoff at a time in chronological order.

Each trained artifact records its exact data cutoff, included fixtures, feature schema, model and
runtime versions, and checksums. A new version becomes active only after training and provenance
validation finish successfully. If training fails, the last verified model remains active.

### From a forecast to a simulated match

The Phase 7 model supplies expected goals, outcome probabilities, and the scoreline distribution.
The approved Phase 12 models or documented safe fallbacks supply supported detailed-statistic
expectations such as shots, corners, fouls, and cards. Prem Engine then uses one saved random seed
to build a consistent match payload: the final score, events, lineups, commentary, and statistics
agree with one another and are protected by a checksum.

Pressing Play does not continually rerun the model. It creates one immutable simulation for that
device, fixture, and schedule revision, then presents the stored match as a compressed one-minute
replay. When the real result becomes available, Prem Engine evaluates the forecast and keeps real
and simulated league tables separate.

Several later candidate models—including standalone tabular, player-impact, ensemble, and tactical
models—were evaluated against untouched holdout data. They were not promoted because they did not
beat the approved Phase 7 benchmark, so they are not silently used for official forecasts.

## Thank you

Thank you for trying Prem Engine. The project was built to make football forecasting transparent,
reproducible, and personal: your installation owns its data, preserves its simulations, and shows
both what the model predicts and how those predictions perform. Feedback, careful testing, and
responsible contributions are always appreciated.
