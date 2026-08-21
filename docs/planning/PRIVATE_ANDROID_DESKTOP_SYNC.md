# Private Android–Desktop Synchronization Plan

## Status and priority

This document records a possible **private, post-project extension** for synchronizing one owner's
Prem Engine data between their laptop and Android phone.

This synchronization feature is **not part of the current cloneable GitHub product**. The immediate
priority is to finish, test, and stabilize the public cloneable repository before the first match of
the upcoming Premier League season. Work on the private synchronization service and Android app
must wait until that project is complete.

The intended order is:

1. Finish every remaining cloneable-repository stage.
2. Complete the public project's testing, cleanup, documentation, and release checks.
3. Confirm the public project is ready before the Premier League season begins.
4. Freeze the interfaces and data contracts needed by a companion client.
5. Only then begin the private laptop–phone synchronization work.
6. Develop the Android mobile version after the private synchronization design is finalized.

## Private-use requirement

Laptop–phone database synchronization is intended **only for the project owner and the owner's two
devices**. It must not be presented as a feature available to people who clone the public GitHub
repository.

The public cloneable edition should continue to work entirely on one local host without Supabase,
a cloud account, a mobile app, or any private synchronization credentials.

Prefer keeping all private implementation outside the public repository, including:

- the Android application source;
- the laptop synchronization agent;
- Supabase schema migrations and server-side functions;
- pairing and authentication code;
- private Docker Compose override files;
- deployment scripts;
- Supabase project identifiers and URLs; and
- every private key, token, password, signing key, and service-role credential.

A suitable later structure would be a separate private repository or an unshared local directory,
for example:

```text
Prem-Engine/                       Public cloneable GitHub repository
Prem-Engine-Private-Sync/          Private laptop sync agent and cloud definitions
Prem-Engine-Android/               Private Android application
```

The private laptop agent could be attached using an external Compose override or a separately run
service. This keeps private functionality out of the public checkout. If the public project later
needs a small generic interface to support the private companion, that interface should contain no
owner-specific behavior, cloud dependency, or secret and must not make Supabase necessary for normal
clones.

## Current product behavior

The current cloneable edition has one PostgreSQL database on the desktop host. Browsers do not each
own a complete database. Instead, each browser has a device UUID, and the desktop database stores a
separate simulation history for each device.

The proposed private extension changes the owner experience: the laptop and phone remain different
devices, but both belong to one shared private profile and ultimately display the same accepted
simulation for a fixture revision.

## Proposed private architecture

The future system would contain three data stores:

```text
Laptop PostgreSQL
        ↕
Supabase synchronization database
        ↕
Android SQLite
```

### Laptop PostgreSQL

The desktop remains the complete Prem Engine installation and retains:

- raw provider captures;
- historical and current football data;
- Phase 7 training state and model artifacts;
- fixtures and official results;
- operational and evaluation records; and
- synchronized simulations saved for the shared private profile.

### Android SQLite

The Android app uses a local SQLite database for:

- synchronized upcoming fixtures;
- forecast outputs available to the phone;
- saved simulation timelines and results;
- cached standings and evaluation data;
- the paired profile and device identifiers; and
- pending synchronization operations.

This allows previously synchronized information and completed simulations to remain viewable when
the phone is offline.

### Supabase

Supabase acts only as a small synchronization authority. It does not replace the desktop database
and does not train or run the Phase 7 model.

It stores only the records needed to coordinate the owner's two devices, such as:

- shared profile and registered-device identifiers;
- fixture UUID, kickoff time, and schedule revision;
- prediction/model and simulation-algorithm versions;
- the forecast inputs or outputs required to reproduce a simulation;
- Play reservations and their expiry times;
- a server-issued shared random seed;
- the one accepted simulation result and timeline; and
- synchronization revisions and timestamps.

Raw provider data, complete training datasets, model artifacts, operational backups, and the rest of
the laptop database should remain local.

## Shared identity and pairing

The laptop and phone have separate device identifiers but are authorized for the same private
profile. Initial development may use the same private Supabase account on both devices. A later
version may use a one-time QR pairing flow.

Pairing must not expose an administrative or Supabase service-role credential. Mobile and laptop
clients use ordinary authenticated sessions. Row-level security must restrict every synchronized
record to the owner's profile.

## Play and synchronization flow

Starting a new shared Play requires a brief internet connection. Offline access is supported for
viewing already synchronized data, but not for claiming a new fixture.

When Play is pressed on either device:

1. The device asks Supabase for the shared profile's record for the fixture and schedule revision.
2. Supabase uses server time to verify the inclusive T−24-hour through T+45-minute Play window.
3. If a completed result exists, the device downloads and presents that result.
4. If another device is generating it, the requesting device waits for the accepted result.
5. If no record exists, Supabase atomically reserves the fixture for the requesting device.
6. Supabase creates and returns a shared random seed.
7. The claiming phone or laptop generates the prediction and simulation locally, subject to the
   capabilities available on that device.
8. The device uploads the completed result with its model, algorithm, fixture, and schedule
   revision information.
9. Supabase marks it as the one accepted result.
10. The other device downloads that exact record the next time it synchronizes.

The authoritative uniqueness key is:

```text
(profile_id, match_uuid, schedule_revision)
```

An atomic database constraint prevents two accepted results for that identity. If both devices press
Play at nearly the same time, only one reservation succeeds.

If the generating device closes or loses connectivity, the reservation may expire. The cloud keeps
the original seed so the other device can safely finish the same simulation rather than create a
different one.

## Prediction and simulation responsibilities

Prediction and simulation are separate operations:

- prediction produces outcome probabilities and predicted match statistics; and
- simulation uses those forecasts and the shared seed to create the saved entertainment timeline.

The initial Android version should preferably avoid porting the full Phase 7 Python training and
inference environment. A simpler first implementation is:

1. The laptop generates forecasts for upcoming fixtures.
2. Only the required forecast outputs synchronize to Supabase and Android.
3. Either device can claim Play.
4. The claiming device runs the lightweight simulation using the synchronized forecast and
   server-issued seed.

A later Android version may run compatible inference locally if that is still desirable and can be
implemented without changing model behavior.

## Offline rules

While offline, either device may:

- view cached fixtures and forecasts;
- replay completed simulations;
- view cached tables and evaluation information; and
- queue non-conflicting synchronization work.

While offline, a device may not start an unclaimed shared Play because it cannot know whether the
other device has already claimed or completed that fixture.

The intended message is:

```text
Internet connection is required to start a shared simulation.
Previously saved simulations remain available offline.
```

The laptop does not need to be powered on. Only the generating device and Supabase must be reachable
when a new Play begins.

## Supabase free-tier expectation

For one owner, one laptop, and one phone, the synchronization workload should be very small and is
expected to fit comfortably within Supabase's current free tier. The service would store compact
coordination and result records rather than the full Prem Engine dataset.

This is a current expectation, not a permanent guarantee. Supabase may change its limits or pricing,
and inactive free projects may pause. Before private implementation begins, the current free-tier
terms must be checked again and the design must fail safely if the service is paused or unavailable.

Potential Android distribution fees are separate from Supabase. A private development build, PWA,
or permitted sideloading path may remain free; publishing through an app store may require a
developer account.

## Security requirements

The private extension must include:

- authenticated users and paired devices;
- row-level security scoped to the single private profile;
- no administrative key in either client;
- server-side validation of the Play window using trusted time;
- atomic reservation and completion operations;
- idempotent uploads and downloads;
- encrypted transport;
- revocable device access;
- safe handling of lost or replaced phones;
- audit timestamps for claims and completions; and
- database backups or export for the small cloud dataset.

The Supabase service-role key, signing secrets, private environment files, and production project
configuration must never be committed to the public Prem Engine repository.

## Later implementation stages

After the cloneable repository is complete, the private extension can be developed in these stages:

1. Define and version the minimal synchronization contract.
2. Create the private Supabase project, authentication, tables, constraints, and row-level policies.
3. Implement and test atomic Play reservation, seed assignment, expiry, completion, and recovery.
4. Build the private laptop synchronization agent outside the public repository.
5. Build the Android application with SQLite and offline read support.
6. Add secure laptop–phone pairing.
7. Test simultaneous Play, interrupted generation, fixture rescheduling, stale data, logout, device
   revocation, Supabase pause, and recovery.
8. Verify that the public cloneable repository still operates with no cloud account or private code.

## Acceptance criteria

The private extension is acceptable only when:

1. Either the phone or laptop can be the first device to claim an eligible match.
2. Only one result is accepted for a profile, fixture, and schedule revision.
3. Both devices eventually display the exact same simulation.
4. Supabase never runs the Phase 7 model or match simulation.
5. The laptop may be powered off while the phone claims and simulates using synchronized forecast
   data.
6. Previously synchronized information remains viewable offline.
7. Starting a new shared Play fails clearly when the cloud cannot be reached.
8. No private credential or owner-only synchronization implementation is present in the public
   GitHub repository.
9. Normal clones continue to work without Supabase or the Android app.
10. Development of this extension begins only after the public cloneable project is finished and
    ready for the Premier League season.

## Decision summary

- The public cloneable Prem Engine project remains the current and deadline-critical priority.
- Private laptop–phone synchronization is deferred until the public project is complete.
- The future Android app is a private companion, not a public clone feature.
- Supabase coordinates and stores shared results but does not predict or simulate matches.
- Exactly one online device generates each previously unplayed fixture.
- New Play requires cloud connectivity; saved data remains available offline.
- The laptop does not need to remain running.
- Private synchronization and Android code should live outside the public GitHub repository.
