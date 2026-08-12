"use client";

import type { MatchForecast } from "./forecast-types";

export type ForecastPollHandlers = {
  onData: (forecast: MatchForecast) => void;
  onError: (message: string) => void;
};

type ForecastBroadcast =
  | { type: "data"; forecast: MatchForecast }
  | { type: "error"; message: string };

const SECOND = 1_000;

export function forecastPollInterval(
  lifecycleState: MatchForecast["lifecycle_state"] | null,
) {
  if (lifecycleState === "complete" || lifecycleState === "cancelled") {
    return null;
  }
  if (lifecycleState === "live") {
    return 2 * SECOND;
  }
  if (lifecycleState === "generating") {
    return 3 * SECOND;
  }
  return 15 * SECOND;
}

function delay(milliseconds: number) {
  return new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));
}

function errorMessage(payload: unknown) {
  if (
    typeof payload === "object" &&
    payload !== null &&
    "detail" in payload &&
    typeof payload.detail === "string"
  ) {
    return payload.detail;
  }
  return "Match forecast is unavailable.";
}

/**
 * Keep one polling leader per match across same-origin tabs. Other tabs receive
 * the exact leader response through BroadcastChannel and take over if it closes.
 */
export function subscribeOfficialForecast(
  matchUuid: string,
  handlers: ForecastPollHandlers,
) {
  let active = true;
  let pollPending = false;
  let latestState: MatchForecast["lifecycle_state"] | null = null;
  const channelName = `prem-engine:forecast:${matchUuid}`;
  const channel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(channelName);
  const lockAbort = new AbortController();

  const deliver = (message: ForecastBroadcast) => {
    if (!active) return;
    if (message.type === "data") {
      latestState = message.forecast.lifecycle_state;
      handlers.onData(message.forecast);
    } else {
      handlers.onError(message.message);
    }
  };

  channel?.addEventListener("message", (event: MessageEvent<ForecastBroadcast>) => {
    deliver(event.data);
  });

  const publish = (message: ForecastBroadcast) => {
    deliver(message);
    channel?.postMessage(message);
  };

  const poll = async () => {
    while (active && document.visibilityState === "visible") {
      let wait = forecastPollInterval(latestState);
      if (wait === null) return;
      try {
        const response = await fetch(
          `/api/matches/${encodeURIComponent(matchUuid)}/forecast`,
          { cache: "no-store" },
        );
        const payload: unknown = await response.json();
        if (!response.ok) {
          publish({ type: "error", message: errorMessage(payload) });
          const retryAfter = Number(response.headers.get("retry-after"));
          if (Number.isFinite(retryAfter) && retryAfter > 0) {
            wait = Math.max(wait, retryAfter * SECOND);
          }
        } else {
          publish({ type: "data", forecast: payload as MatchForecast });
          wait = forecastPollInterval(latestState);
          if (wait === null) return;
        }
      } catch (reason) {
        publish({
          type: "error",
          message: reason instanceof Error ? reason.message : "Could not load forecast.",
        });
      }
      if (wait !== null) await delay(wait);
    }
  };

  const start = () => {
    if (!active || pollPending || document.visibilityState !== "visible") return;
    pollPending = true;
    if ("locks" in navigator) {
      void navigator.locks
        .request(`prem-engine:forecast:${matchUuid}`, { signal: lockAbort.signal }, poll)
        .catch((reason: unknown) => {
          if (reason instanceof DOMException && reason.name === "AbortError") return;
          handlers.onError("Could not coordinate live updates between browser tabs.");
        })
        .finally(() => {
          pollPending = false;
        });
    } else {
      void poll().finally(() => {
        pollPending = false;
      });
    }
  };

  const handleVisibility = () => {
    if (document.visibilityState === "visible") start();
  };
  document.addEventListener("visibilitychange", handleVisibility);
  start();

  return () => {
    active = false;
    lockAbort.abort();
    channel?.close();
    document.removeEventListener("visibilitychange", handleVisibility);
  };
}
