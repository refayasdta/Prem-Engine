import assert from "node:assert/strict";
import test from "node:test";
import { resolveSiteUrl } from "./site-url.ts";

test("site URL falls back locally outside a production deployment", () => {
  assert.equal(resolveSiteUrl(undefined).href, "http://localhost:3000/");
});

test("site URL accepts an explicit LAN origin", () => {
  assert.equal(resolveSiteUrl("http://192.168.1.10:3000/").href, "http://192.168.1.10:3000/");
});
