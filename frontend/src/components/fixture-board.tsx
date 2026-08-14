"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import type { UpcomingMatch } from "@/lib/forecast-types";
import { ClubCrest } from "./club-crest";
import styles from "@/app/product.module.css";

function compactCountdown(totalSeconds: number) {
  if (totalSeconds <= 0) return "Play available";
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  if (days) return `Play in ${days}d ${hours}h`;
  if (hours) return `Play in ${hours}h ${minutes}m`;
  return `Play in ${minutes}m`;
}

function dayLabel(value: string) {
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(new Date(value));
}

function kickoffTime(value: string) {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function FixtureCard({ match, now }: { match: UpcomingMatch; now: number }) {
  const dueAt = new Date(match.prediction_due_at).getTime();
  const countdown = compactCountdown(Math.ceil((dueAt - now) / 1000));
  return (
    <Link className={styles.fixtureCard} href={`/matches/${match.match_uuid}`}>
      <div className={styles.fixtureMeta}>
        <span>{match.fixture_status}</span>
        <time dateTime={match.kickoff_at}>{kickoffTime(match.kickoff_at)}</time>
      </div>
      <div className={styles.fixtureTeam}>
        <ClubCrest club={match.home} size="small" />
        <strong>{match.home.name}</strong>
        <span>Home</span>
      </div>
      <div className={styles.fixtureVersus} aria-label="versus">
        vs
      </div>
      <div className={styles.fixtureTeam}>
        <ClubCrest club={match.away} size="small" />
        <strong>{match.away.name}</strong>
        <span>Away</span>
      </div>
      <div className={styles.fixtureAction}>
        <span>{countdown}</span>
        <strong>Open match <i aria-hidden="true">→</i></strong>
      </div>
    </Link>
  );
}

function LoadingFixtures({ count }: { count: number }) {
  return (
    <div className={styles.fixtureLoading} aria-label="Loading real fixtures" aria-busy="true">
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className={styles.fixtureSkeleton} />
      ))}
    </div>
  );
}

export function FixtureBoard({ mode = "preview" }: { mode?: "preview" | "full" }) {
  const [matches, setMatches] = useState<UpcomingMatch[] | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/matches/upcoming", { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        const payload = (await response.json()) as UpcomingMatch[] | { detail?: string };
        if (!response.ok || !Array.isArray(payload)) {
          throw new Error(
            !Array.isArray(payload) && payload.detail
              ? payload.detail
              : "The fixture service is unavailable.",
          );
        }
        return payload;
      })
      .then(setMatches)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Could not load fixtures.");
        }
      });
    return () => controller.abort();
  }, [attempt]);

  const grouped = useMemo(() => {
    const groups = new Map<string, UpcomingMatch[]>();
    const visible = mode === "preview" ? matches?.slice(0, 4) : matches;
    for (const match of visible ?? []) {
      const label = dayLabel(match.kickoff_at);
      groups.set(label, [...(groups.get(label) ?? []), match]);
    }
    return [...groups.entries()];
  }, [matches, mode]);

  const visibleCount = mode === "preview" ? matches?.slice(0, 4).length : matches?.length;

  if (matches === null && !error) return <LoadingFixtures count={mode === "preview" ? 2 : 4} />;
  if (error) {
    return (
      <div className={styles.fixtureState} role="status">
        <span className={styles.stateCode}>API</span>
        <div>
          <strong>Real fixtures could not be reached</strong>
          <p>{error} No sample clubs will be substituted.</p>
        </div>
        <button
          type="button"
          onClick={() => {
            setError("");
            setMatches(null);
            setAttempt((value) => value + 1);
          }}
        >
          Try again
        </button>
      </div>
    );
  }
  if (!visibleCount) {
    return (
      <div className={styles.fixtureState} role="status">
        <span className={styles.stateCode}>00</span>
        <div>
          <strong>No future fixtures are loaded</strong>
          <p>
            The dashboard only displays canonical Premier League records. The next ingestion run
            will populate this space automatically.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.fixtureGroups}>
      {grouped.map(([label, fixtures]) => (
        <section className={styles.fixtureDay} key={label}>
          <h3>{label}</h3>
          <div>
            {fixtures.map((match) => (
              <FixtureCard match={match} now={now} key={match.match_uuid} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
