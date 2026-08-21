import assert from "node:assert/strict";
import test from "node:test";
import { proxyBackend, resolveBackendConfiguration } from "./backend-proxy.ts";

test("backend configuration uses local development defaults", () => {
  assert.deepEqual(resolveBackendConfiguration(undefined), {
    baseUrl: "http://127.0.0.1:8000",
  });
});
test("backend configuration accepts the private Compose service origin", () => {
  assert.deepEqual(resolveBackendConfiguration("http://api:8000"), {
    baseUrl: "http://api:8000",
  });
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
