import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";
import { proxyBackend, resolveBackendConfiguration } from "./backend-proxy.ts";

test("backend configuration uses local development defaults", () => {
  assert.deepEqual(resolveBackendConfiguration(undefined, undefined, undefined), {
    baseUrl: "http://127.0.0.1:8000",
    originToken: undefined,
  });
});

test("backend configuration requires an authenticated HTTPS origin in production", () => {
  assert.throws(
    () => resolveBackendConfiguration(undefined, undefined, "production"),
    /API_BASE_URL is required/,
  );
  assert.throws(
    () => resolveBackendConfiguration("http://api.example", "a".repeat(32), "production"),
    /must use HTTPS/,
  );
  assert.throws(
    () => resolveBackendConfiguration("https://api.example", "short", "production"),
    /at least 32 bytes/,
  );
  assert.deepEqual(
    resolveBackendConfiguration("https://api.example", "a".repeat(32), "production"),
    { baseUrl: "https://api.example", originToken: "a".repeat(32) },
  );
});

test("setup status is never cached", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response('{"state":"setup_required"}', { status: 200 })) as typeof fetch;
  try {
    const response = await proxyBackend("/api/setup/status");
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("cache-control"), "private, no-store");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

function manifestFor(body: string, expiresAt: Date) {
  return JSON.stringify({
    schema_version: "prem-engine-public-snapshot-manifest-v1",
    logical_key: "standings/default",
    object_key: "public/v1/objects/standings/default/version.json",
    published_at: new Date(Date.now() - 600_000).toISOString(),
    expires_at: expiresAt.toISOString(),
    content_sha256: createHash("sha256").update(body).digest("hex"),
    content_length: Buffer.byteLength(body),
    cache_seconds: 300,
  });
}

test("proxy serves a verified fresh snapshot without calling the API origin", async () => {
  const originalFetch = globalThis.fetch;
  const originalSnapshotUrl = process.env.PREM_ENGINE_SNAPSHOT_BASE_URL;
  const body = '{"rows":[]}';
  const calls: string[] = [];
  process.env.PREM_ENGINE_SNAPSHOT_BASE_URL = "https://snap.example";
  globalThis.fetch = (async (input: string | URL | Request) => {
    const url = input.toString();
    calls.push(url);
    return new Response(
      url.includes("/manifests/")
        ? manifestFor(body, new Date(Date.now() + 300_000))
        : body,
      { status: 200 },
    );
  }) as typeof fetch;
  try {
    const response = await proxyBackend("/api/standings");
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("x-prem-engine-source"), "snapshot");
    assert.equal(await response.text(), body);
    assert.equal(calls.length, 2);
    assert.ok(calls.every((url) => url.startsWith("https://snap.example/")));
  } finally {
    globalThis.fetch = originalFetch;
    if (originalSnapshotUrl === undefined) {
      delete process.env.PREM_ENGINE_SNAPSHOT_BASE_URL;
    } else {
      process.env.PREM_ENGINE_SNAPSHOT_BASE_URL = originalSnapshotUrl;
    }
  }
});

test("proxy uses a verified stale snapshot only after an origin failure", async () => {
  const originalFetch = globalThis.fetch;
  const originalSnapshotUrl = process.env.PREM_ENGINE_SNAPSHOT_BASE_URL;
  const originalApiUrl = process.env.PREM_ENGINE_API_BASE_URL;
  const body = '{"rows":[{"position":1}]}';
  process.env.PREM_ENGINE_SNAPSHOT_BASE_URL = "https://snap.example";
  process.env.PREM_ENGINE_API_BASE_URL = "https://api.example";
  globalThis.fetch = (async (input: string | URL | Request) => {
    const url = input.toString();
    if (url.startsWith("https://api.example/")) {
      return new Response('{"detail":"unavailable"}', { status: 503 });
    }
    return new Response(
      url.includes("/manifests/")
        ? manifestFor(body, new Date(Date.now() - 60_000))
        : body,
      { status: 200 },
    );
  }) as typeof fetch;
  try {
    const response = await proxyBackend("/api/standings");
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("x-prem-engine-source"), "snapshot-stale");
    assert.match(response.headers.get("warning") ?? "", /stale/);
    assert.equal(await response.text(), body);
  } finally {
    globalThis.fetch = originalFetch;
    for (const [name, value] of [
      ["PREM_ENGINE_SNAPSHOT_BASE_URL", originalSnapshotUrl],
      ["PREM_ENGINE_API_BASE_URL", originalApiUrl],
    ] as const) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
});
