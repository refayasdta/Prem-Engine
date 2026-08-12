import assert from "node:assert/strict";
import test from "node:test";

import { forecastPollInterval } from "./official-forecast-poller.ts";

test("polls quickly only while a stored simulation is being revealed", () => {
  assert.equal(forecastPollInterval("live"), 2_000);
  assert.equal(forecastPollInterval("generating"), 3_000);
  assert.equal(forecastPollInterval("countdown"), 15_000);
  assert.equal(forecastPollInterval("unavailable"), 15_000);
});

test("stops polling terminal presentations", () => {
  assert.equal(forecastPollInterval("complete"), null);
  assert.equal(forecastPollInterval("cancelled"), null);
});
