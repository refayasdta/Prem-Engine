import assert from "node:assert/strict";
import test from "node:test";

import { SlidingWindowRateLimiter, positiveInteger } from "./rate-limit.ts";

test("rejects requests over the sliding-window limit", () => {
  const limiter = new SlidingWindowRateLimiter(2, 10_000);

  assert.deepEqual(limiter.consume("client", 0), {
    allowed: true,
    limit: 2,
    remaining: 1,
    resetAt: 10_000,
    retryAfterSeconds: 10,
  });
  assert.equal(limiter.consume("client", 1_000).allowed, true);

  const rejected = limiter.consume("client", 2_000);
  assert.equal(rejected.allowed, false);
  assert.equal(rejected.remaining, 0);
  assert.equal(rejected.retryAfterSeconds, 8);

  const released = limiter.consume("client", 10_001);
  assert.equal(released.allowed, true);
  assert.equal(released.remaining, 0);
});

test("tracks clients independently", () => {
  const limiter = new SlidingWindowRateLimiter(1, 60_000);

  assert.equal(limiter.consume("first", 0).allowed, true);
  assert.equal(limiter.consume("first", 1).allowed, false);
  assert.equal(limiter.consume("second", 1).allowed, true);
});

test("uses safe defaults for invalid integer configuration", () => {
  assert.equal(positiveInteger("120", 60), 120);
  assert.equal(positiveInteger("0", 60), 60);
  assert.equal(positiveInteger("invalid", 60), 60);
  assert.equal(positiveInteger(undefined, 60), 60);
});
