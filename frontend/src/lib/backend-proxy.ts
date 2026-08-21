const DEFAULT_BACKEND = "http://127.0.0.1:8000";
const DEFAULT_CACHE_SECONDS = 300;
const FORECAST_CACHE_SECONDS = 30;

export function resolveBackendConfiguration(
  configuredBaseUrl = process.env.PREM_ENGINE_API_BASE_URL,
) {
  const baseUrl = new URL(configuredBaseUrl ?? DEFAULT_BACKEND);
  if (
    baseUrl.username ||
    baseUrl.password ||
    baseUrl.pathname !== "/" ||
    baseUrl.search ||
    baseUrl.hash
  ) {
    throw new Error("PREM_ENGINE_API_BASE_URL must be an origin without credentials or suffixes");
  }
  return { baseUrl: baseUrl.origin };
}

export async function proxyBackend(path: string, init: RequestInit = {}) {
  const method = (init.method ?? "GET").toUpperCase();
  try {
    const { baseUrl } = resolveBackendConfiguration();
    const requestHeaders = new Headers(init.headers);
    requestHeaders.set("accept", "application/json");
    const response = await fetch(`${baseUrl}${path}`, {
      ...init,
      cache: "no-store",
      headers: requestHeaders,
    });
    const body = await response.text();
    const headers = new Headers({
      "content-type": response.headers.get("content-type") ?? "application/json",
      "x-prem-engine-source": "origin",
    });
    for (const name of [
      "retry-after",
      "x-ratelimit-limit",
      "x-ratelimit-remaining",
      "x-ratelimit-reset",
    ]) {
      const value = response.headers.get(name);
      if (value !== null) {
        headers.set(name, value);
      }
    }
    if (response.ok && method === "GET") {
      const cacheSeconds = originCacheSeconds(path, body);
      headers.set(
        "cache-control",
        cacheSeconds === null
          ? "private, no-store"
          : `public, s-maxage=${cacheSeconds}, stale-while-revalidate=${cacheSeconds}`,
      );
    } else {
      headers.set("cache-control", "private, no-store");
    }
    return new Response(body, {
      status: response.status,
      headers,
    });
  } catch {
    return Response.json(
      { detail: "Prem Engine API is unavailable. Start the backend and try again." },
      { status: 503, headers: { "cache-control": "private, no-store" } },
    );
  }
}

function originCacheSeconds(path: string, body: string): number | null {
  if (path === "/api/setup/status") return null;
  if (!path.endsWith("/forecast")) return DEFAULT_CACHE_SECONDS;
  try {
    const payload = JSON.parse(body) as {
      lifecycle_state?: unknown;
      prediction_due_at?: unknown;
    };
    if (payload.lifecycle_state === "live" || payload.lifecycle_state === "generating") {
      return null;
    }
    if (payload.lifecycle_state === "countdown") {
      if (typeof payload.prediction_due_at !== "string") return null;
      const secondsUntilDue = Math.floor(
        (Date.parse(payload.prediction_due_at) - Date.now()) / 1000,
      );
      return secondsUntilDue > 0
        ? Math.max(1, Math.min(FORECAST_CACHE_SECONDS, secondsUntilDue))
        : null;
    }
    return FORECAST_CACHE_SECONDS;
  } catch {
    return null;
  }
}
