import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import {
  readPublicSnapshot,
  resolveSnapshotConfiguration,
  snapshotLogicalKey,
} from "./public-snapshot.ts";

const now = new Date("2026-08-13T12:00:00Z");

function snapshotFetch(
  payload: unknown,
  options: { expiresAt?: string; checksum?: string } = {},
): typeof fetch {
  const body = JSON.stringify(payload);
  const manifest = JSON.stringify({
    schema_version: "prem-engine-public-snapshot-manifest-v1",
    logical_key: "standings/default",
    object_key: "public/v1/objects/standings/default/version.json",
    published_at: "2026-08-13T11:55:00Z",
    expires_at: options.expiresAt ?? "2026-08-13T12:05:00Z",
    content_sha256: options.checksum ?? createHash("sha256").update(body).digest("hex"),
    content_length: Buffer.byteLength(body),
    cache_seconds: 300,
  });
  return (async (input: string | URL | Request) => {
    const url = input.toString();
    return new Response(url.includes("/manifests/") ? manifest : body, {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;
}

test("snapshot configuration enforces a safe HTTPS origin", () => {
  assert.equal(resolveSnapshotConfiguration(undefined), null);
  assert.throws(
    () => resolveSnapshotConfiguration("http://snap.example", undefined, "production"),
    /HTTPS/,
  );
  assert.deepEqual(
    resolveSnapshotConfiguration("https://snap.example", "3600", "production"),
    { baseUrl: "https://snap.example", staleSeconds: 3600 },
  );
});

test("only exact public API routes map to snapshot keys", () => {
  assert.equal(snapshotLogicalKey("/api/standings"), "standings/default");
  assert.equal(snapshotLogicalKey("/api/standings?season_uuid=private"), null);
  assert.equal(snapshotLogicalKey("/api/matches/upcoming?limit=10"), "upcoming/default");
});

test("a fresh checksum-verified snapshot is accepted", async () => {
  const result = await readPublicSnapshot("/api/standings", {
    baseUrl: "https://snap.example",
    fetchImpl: snapshotFetch({ rows: [] }),
    now,
  });
  assert.equal(result.fresh?.body, '{"rows":[]}');
  assert.equal(result.stale, null);
});

test("a corrupt or over-age snapshot is rejected", async () => {
  const corrupt = await readPublicSnapshot("/api/standings", {
    baseUrl: "https://snap.example",
    fetchImpl: snapshotFetch({ rows: [] }, { checksum: "0".repeat(64) }),
    now,
  });
  assert.deepEqual(corrupt, { fresh: null, stale: null });

  const expired = await readPublicSnapshot("/api/standings", {
    baseUrl: "https://snap.example",
    fetchImpl: snapshotFetch({ rows: [] }, { expiresAt: "2026-08-13T00:00:00Z" }),
    staleSeconds: "60",
    now,
  });
  assert.deepEqual(expired, { fresh: null, stale: null });
});

test("a recently expired verified snapshot is retained only for fallback", async () => {
  const result = await readPublicSnapshot("/api/standings", {
    baseUrl: "https://snap.example",
    fetchImpl: snapshotFetch({ rows: [] }, { expiresAt: "2026-08-13T11:59:30Z" }),
    now,
  });
  assert.equal(result.fresh, null);
  assert.equal(result.stale?.body, '{"rows":[]}');
});
