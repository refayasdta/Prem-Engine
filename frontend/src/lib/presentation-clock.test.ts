import assert from "node:assert/strict";
import test from "node:test";
import { presentationClockAt, type PresentationClockSource } from "./presentation-clock.ts";

const startedAt = "2026-08-14T11:00:00.000Z";
const start = Date.parse(startedAt);
const source: PresentationClockSource = {
  started_at: startedAt,
  duration_seconds: 60,
  phase: "first_half",
  football_second: 0,
  complete: false,
};

test("smoothly maps the first and second halves around the halftime pause", () => {
  assert.deepEqual(presentationClockAt(source, start + 12_500), {
    phase: "first_half",
    footballSecond: 1_350,
    complete: false,
  });
  assert.deepEqual(presentationClockAt(source, start + 30_000), {
    phase: "half_time",
    footballSecond: 2_700,
    complete: false,
  });
  assert.deepEqual(presentationClockAt(source, start + 47_500), {
    phase: "second_half",
    footballSecond: 4_050,
    complete: false,
  });
});

test("finishes exactly at the configured presentation duration", () => {
  assert.deepEqual(presentationClockAt(source, start + 60_000), {
    phase: "complete",
    footballSecond: 5_400,
    complete: true,
  });
});
