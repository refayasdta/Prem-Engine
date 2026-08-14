"use client";

import { useEffect, useState } from "react";
import styles from "@/app/product.module.css";

type SetupStatus = {
  state: "setup_required" | "awaiting_sync" | "current" | "stale";
  provider_configured: boolean;
  fixture_count: number;
  last_fixture_sync_at: string | null;
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
    fetch("/api/setup/status", { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("setup status unavailable");
        return (await response.json()) as SetupStatus;
      })
      .then(setStatus)
      .catch(() => undefined);
    return () => controller.abort();
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
      </div>
    </section>
  );
}
