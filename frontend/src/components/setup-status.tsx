"use client";

import { useEffect, useState } from "react";
import styles from "@/app/product.module.css";

type SetupStatus = {
  state: "setup_required" | "awaiting_sync" | "syncing" | "current" | "stale";
  provider_configured: boolean;
  fixture_count: number;
  last_fixture_sync_at: string | null;
  sync_operation: string | null;
  sync_pages_processed: number;
  sync_records_received: number;
  last_sync_error_code: string | null;
  next_fixture_sync_at: string | null;
};

const copy = {
  setup_required: {
    title: "Live fixture data needs setup",
    body: "Add your KickoffAPI key to the local .env file, then restart Prem Engine. Play stays disabled until the first fixture synchronization succeeds.",
  },
  awaiting_sync: {
    title: "Waiting for the first fixture sync",
    body: "Your provider key is configured. Prem Engine will show current fixtures after the local worker completes synchronization.",
  },
  syncing: {
    title: "Local fixture synchronization is running",
    body: "Prem Engine is reconciling the saved schedule with KickoffAPI. The page updates automatically when the worker finishes.",
  },
  stale: {
    title: "Local fixture data may be stale",
    body: "Saved data is still available, but Prem Engine cannot claim the current schedule is fresh. Play remains disabled until synchronization succeeds.",
  },
  current: {
    title: "Local fixture data is current",
    body: "This installation owns its synchronized fixtures and saved application data.",
  },
} as const;

export function SetupStatusNotice() {
  const [status, setStatus] = useState<SetupStatus | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const refresh = () => {
      fetch("/api/setup/status", { cache: "no-store", signal: controller.signal })
        .then(async (response) => {
          if (!response.ok) throw new Error("setup status unavailable");
          return (await response.json()) as SetupStatus;
        })
        .then(setStatus)
        .catch(() => undefined);
    };
    refresh();
    const interval = window.setInterval(refresh, 5_000);
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, []);

  if (!status || status.state === "current") return null;
  const message = copy[status.state];
  return (
    <section className={styles.setupNotice} role="status" aria-live="polite">
      <span>{status.state.replaceAll("_", " ")}</span>
      <div>
        <strong>{message.title}</strong>
        <p>{message.body}</p>
        {status.last_fixture_sync_at ? (
          <small>
            Last successful fixture sync: {new Date(status.last_fixture_sync_at).toLocaleString("en-GB")}
          </small>
        ) : null}
        {status.state === "syncing" ? (
          <small>
            {status.sync_operation?.replaceAll("_", " ") ?? "synchronization"}: {status.sync_pages_processed} page(s), {status.sync_records_received} fixture(s)
          </small>
        ) : null}
        {status.last_sync_error_code ? (
          <small>Last synchronization issue: {status.last_sync_error_code.replaceAll("_", " ")}</small>
        ) : null}
      </div>
    </section>
  );
}
