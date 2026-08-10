"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { UpcomingMatch } from "@/lib/forecast-types";

export function UpcomingMatches() {
  const [matches, setMatches] = useState<UpcomingMatch[] | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/matches/upcoming", { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("The forecast API is not available.");
        return (await response.json()) as UpcomingMatch[];
      })
      .then(setMatches)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setMessage(error instanceof Error ? error.message : "Could not load fixtures.");
        }
      });
    return () => controller.abort();
  }, []);

  if (message) return <p className="mt-4 text-sm text-mist">{message}</p>;
  if (matches === null) return <p className="mt-4 text-sm text-mist">Loading real fixtures…</p>;
  if (matches.length === 0) {
    return (
      <p className="mt-4 max-w-2xl text-sm text-mist">
        No future Premier League fixtures are loaded in the local database yet. Run the approved
        ingestion workflow; this page will never substitute fictional clubs.
      </p>
    );
  }
  return (
    <div className="mt-5 grid gap-2">
      {matches.map((match) => (
        <Link
          key={match.match_uuid}
          href={`/matches/${match.match_uuid}`}
          className="grid gap-2 border border-slate-violet p-4 transition-colors hover:bg-deep-violet sm:grid-cols-[1fr_auto]"
        >
          <span className="font-semibold">
            {match.home.name} <span className="text-mist">vs</span> {match.away.name}
          </span>
          <time className="text-sm text-mist">
            {new Date(match.kickoff_at).toLocaleString("en-GB")}
          </time>
        </Link>
      ))}
    </div>
  );
}
