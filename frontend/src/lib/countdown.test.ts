import assert from "node:assert/strict";
import test from "node:test";
import { secondsUntil } from "./countdown.ts";

test("countdown advances from the local clock and stops at zero", () => {
  const dueAt = "2026-08-13T12:00:00.000Z";
  const start = Date.parse("2026-08-13T11:59:55.000Z");

  assert.equal(secondsUntil(dueAt, start), 5);
  assert.equal(secondsUntil(dueAt, start + 1_000), 4);
  assert.equal(secondsUntil(dueAt, start + 5_000), 0);
  assert.equal(secondsUntil(dueAt, start + 10_000), 0);
});

test("invalid timestamps fail closed at zero", () => {
  assert.equal(secondsUntil("not-a-timestamp", 0), 0);
});
