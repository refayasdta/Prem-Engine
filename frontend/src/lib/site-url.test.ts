import assert from "node:assert/strict";
import test from "node:test";
import { resolveSiteUrl } from "./site-url.ts";

test("site URL falls back locally outside a production deployment", () => {
  assert.equal(resolveSiteUrl(undefined, undefined).href, "http://localhost:3000/");
});

test("site URL requires HTTPS in production", () => {
  assert.throws(
    () => resolveSiteUrl("http://prem-engine.example", "production"),
    /must use HTTPS/,
  );
  assert.equal(
    resolveSiteUrl("https://prem-engine.example/", "production").href,
    "https://prem-engine.example/",
  );
});

test("site URL is mandatory in production", () => {
  assert.throws(() => resolveSiteUrl(undefined, "production"), /is required/);
});
