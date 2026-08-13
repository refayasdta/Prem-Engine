import { createHash } from "node:crypto";

const MANIFEST_SCHEMA = "prem-engine-public-snapshot-manifest-v1";
const DEFAULT_STALE_SECONDS = 21_600;
const MAX_STALE_SECONDS = 86_400;
const MAX_PAYLOAD_BYTES = 2_000_000;
const MAX_MANIFEST_BYTES = 8_192;
const MAX_FRESHNESS_SECONDS = 86_400;

type SnapshotManifest = {
  schema_version: string;
  logical_key: string;
  object_key: string;
  published_at: string;
  expires_at: string;
  content_sha256: string;
  content_length: number;
  cache_seconds: number;
};

export type SnapshotCandidate = {
  body: string;
  cacheSeconds: number;
};

export type SnapshotReadResult = {
  fresh: SnapshotCandidate | null;
  stale: SnapshotCandidate | null;
};

export function snapshotLogicalKey(path: string): string | null {
  if (path === "/api/matches/upcoming?limit=10") return "upcoming/default";
  if (path === "/api/standings" || path === "/api/standings?") {
    return "standings/default";
  }
  if (path === "/api/evaluation" || path === "/api/evaluation?") {
    return "evaluation/default";
  }
  const forecast = path.match(
    /^\/api\/matches\/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\/forecast$/i,
  );
  return forecast ? `forecast/${forecast[1].toLowerCase()}` : null;
}

export function resolveSnapshotConfiguration(
  configuredBaseUrl = process.env.PREM_ENGINE_SNAPSHOT_BASE_URL,
  configuredStaleSeconds = process.env.PREM_ENGINE_SNAPSHOT_STALE_IF_ERROR_SECONDS,
  deploymentEnvironment = process.env.VERCEL_ENV,
) {
  if (!configuredBaseUrl) return null;
  const baseUrl = new URL(configuredBaseUrl);
  if (
    baseUrl.username ||
    baseUrl.password ||
    baseUrl.pathname !== "/" ||
    baseUrl.search ||
    baseUrl.hash
  ) {
    throw new Error("PREM_ENGINE_SNAPSHOT_BASE_URL must be an origin without suffixes");
  }
  if (deploymentEnvironment === "production" && baseUrl.protocol !== "https:") {
    throw new Error("PREM_ENGINE_SNAPSHOT_BASE_URL must use HTTPS in production");
  }
  const staleSeconds = Number(configuredStaleSeconds ?? DEFAULT_STALE_SECONDS);
  if (!Number.isInteger(staleSeconds) || staleSeconds < 0 || staleSeconds > MAX_STALE_SECONDS) {
    throw new Error("snapshot stale-if-error duration is invalid");
  }
  return { baseUrl: baseUrl.origin, staleSeconds };
}

function validManifest(value: unknown, logicalKey: string): value is SnapshotManifest {
  if (!value || typeof value !== "object") return false;
  const manifest = value as Partial<SnapshotManifest>;
  if (
    manifest.schema_version !== MANIFEST_SCHEMA ||
    manifest.logical_key !== logicalKey ||
    typeof manifest.object_key !== "string" ||
    !/^public\/v1\/objects\/[a-z0-9][a-z0-9./-]*\.json$/.test(manifest.object_key) ||
    manifest.object_key.includes("..") ||
    typeof manifest.content_sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(manifest.content_sha256) ||
    !Number.isInteger(manifest.content_length) ||
    (manifest.content_length ?? 0) <= 0 ||
    (manifest.content_length ?? 0) > MAX_PAYLOAD_BYTES ||
    !Number.isInteger(manifest.cache_seconds) ||
    (manifest.cache_seconds ?? 0) <= 0 ||
    (manifest.cache_seconds ?? 0) > 300 ||
    typeof manifest.published_at !== "string" ||
    typeof manifest.expires_at !== "string"
  ) {
    return false;
  }
  const publishedAt = Date.parse(manifest.published_at);
  const expiresAt = Date.parse(manifest.expires_at);
  return (
    Number.isFinite(publishedAt) &&
    Number.isFinite(expiresAt) &&
    expiresAt > publishedAt &&
    expiresAt - publishedAt <= MAX_FRESHNESS_SECONDS * 1000
  );
}

function forecastSnapshotIsSafe(logicalKey: string, payload: unknown, nowMs: number): boolean {
  if (!logicalKey.startsWith("forecast/")) return true;
  if (!payload || typeof payload !== "object") return false;
  const forecast = payload as { lifecycle_state?: unknown; prediction_due_at?: unknown };
  if (typeof forecast.lifecycle_state !== "string") return false;
  if (forecast.lifecycle_state === "live" || forecast.lifecycle_state === "generating") {
    return false;
  }
  if (forecast.lifecycle_state === "countdown") {
    if (typeof forecast.prediction_due_at !== "string") return false;
    const dueAt = Date.parse(forecast.prediction_due_at);
    return Number.isFinite(dueAt) && nowMs < dueAt;
  }
  return true;
}

export async function readPublicSnapshot(
  path: string,
  options: {
    fetchImpl?: typeof fetch;
    now?: Date;
    baseUrl?: string;
    staleSeconds?: string;
    deploymentEnvironment?: string;
  } = {},
): Promise<SnapshotReadResult> {
  const empty = { fresh: null, stale: null };
  const logicalKey = snapshotLogicalKey(path);
  if (!logicalKey) return empty;
  try {
    const config = resolveSnapshotConfiguration(
      options.baseUrl,
      options.staleSeconds,
      options.deploymentEnvironment,
    );
    if (!config) return empty;
    const fetchImpl = options.fetchImpl ?? fetch;
    const manifestUrl = new URL(`/public/v1/manifests/${logicalKey}.json`, config.baseUrl);
    const manifestResponse = await fetchImpl(manifestUrl, {
      cache: "no-store",
      headers: { accept: "application/json" },
    });
    if (!manifestResponse.ok) return empty;
    const manifestBody = await manifestResponse.text();
    if (Buffer.byteLength(manifestBody) > MAX_MANIFEST_BYTES) return empty;
    const manifestValue: unknown = JSON.parse(manifestBody);
    if (!validManifest(manifestValue, logicalKey)) return empty;
    const manifest = manifestValue;
    const objectUrl = new URL(`/${manifest.object_key}`, config.baseUrl);
    const objectResponse = await fetchImpl(objectUrl, {
      cache: "no-store",
      headers: { accept: "application/json" },
    });
    if (!objectResponse.ok) return empty;
    const body = await objectResponse.text();
    if (Buffer.byteLength(body) !== manifest.content_length) return empty;
    if (createHash("sha256").update(body).digest("hex") !== manifest.content_sha256) {
      return empty;
    }
    const payload: unknown = JSON.parse(body);
    const nowMs = (options.now ?? new Date()).getTime();
    if (!forecastSnapshotIsSafe(logicalKey, payload, nowMs)) return empty;
    const publishedAt = Date.parse(manifest.published_at);
    const expiresAt = Date.parse(manifest.expires_at);
    if (publishedAt > nowMs + 300_000) return empty;
    if (nowMs <= expiresAt) {
      const cacheSeconds = Math.max(
        0,
        Math.min(manifest.cache_seconds, Math.floor((expiresAt - nowMs) / 1000)),
      );
      return { fresh: { body, cacheSeconds }, stale: null };
    }
    if (nowMs - expiresAt <= config.staleSeconds * 1000) {
      return { fresh: null, stale: { body, cacheSeconds: manifest.cache_seconds } };
    }
    return empty;
  } catch (error) {
    console.warn("public_snapshot_read_failed", {
      error: error instanceof Error ? error.name : "unknown",
    });
    return empty;
  }
}
