# Phase 4 Data Ingestion

Date: 2026-08-07

## Provider version decision

Prem Engine targets KickoffAPI v2. The official documentation marks v1 as
deprecated with a 01 January 2027 sunset. Authentication remains the server-side
`x-api-key` header. Responses expose the active rate-limit window, its remaining
requests and reset time, plus request identifiers through `X-RateLimit-*` and
`X-Request-Id` headers.

Official sources:

- <https://docs.kickoffapi.com/>
- <https://docs.kickoffapi.com/migration.html>

The two official v2 pages currently disagree about identifier and envelope
examples. One shows prefixed native IDs such as `lg_...`, `tm_...`, and `fx_...`
with `{data, meta}`. The migration guide shows codes such as `en.1` and
`t_arsenal` with `{data, count, page, totalPages}`. Provider DTOs therefore
accept both variants while keeping either form strictly outside canonical domain
identities.

## Request and raw-data lifecycle

1. Atomically reserve a request against the 85-request operational allowance.
2. Commit a `provider_requests` row before performing the network call.
3. Send the key only in the request header; never log or persist it.
4. Compress and store the byte-exact response under a unique object key.
5. Save checksum, status, schema version, quota headers, and request ID.
6. Parse the provider DTO only after raw capture succeeds.
7. Normalize DTOs into canonical records in a separate transaction.

Identical responses still create distinct raw-fetch records and objects. Their
checksums may match, but a later synchronization never overwrites an earlier
observation.

## Identity resolution

External IDs map to internal UUIDs for competitions, clubs, and matches. A new
external ID can attach automatically only when there is one unambiguous
canonical candidate. Match candidates use season, home club, away club, and a
48-hour kickoff window. Multiple candidates create a pending
`identity_review_cases` record rather than silently merging fixtures.

## Fixture normalization

Fixture ingestion is idempotent and maintains:

- canonical fixture status plus the original provider status;
- append-oriented schedule revisions;
- stable `match_uuid` across provider ID changes;
- prediction voiding for postponements and cancellations;
- replacement generation 24 hours before a revised kickoff;
- accepted actual-result revisions when finished or awarded scores change.

Provider standings remain validation input only. They never replace the real or
simulated tables calculated from canonical match records.

## Authenticated validation result

The bounded probe made exactly three requests on 2026-08-07: v2 leagues, teams,
and Premier League 2026 fixtures. All returned HTTP 200 with request IDs and
passed offline validation against the captured byte-exact responses. The account
returned string IDs and the `{data, meta}` envelope with cursor pagination. The
sanitized evidence is committed as `data/contracts/kickoffapi/probe-summary.json`.

All three responses reported `X-RateLimit-Limit: 30`. The account dashboard
confirms that this is the 30-request-per-minute window and that the account also
has a separate 100-request daily allowance. Prem Engine therefore keeps its
explicit 100/day hard limit and 85/day operational ceiling, records the active
provider window independently, and blocks locally whenever that window reports
zero remaining requests before its reset time.
