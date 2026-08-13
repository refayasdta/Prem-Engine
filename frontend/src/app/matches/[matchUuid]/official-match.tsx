"use client";

import { useEffect, useMemo, useState } from "react";
import { ClubCrest } from "@/components/club-crest";
import { secondsUntil } from "@/lib/countdown";
import type {
  ForecastEvent,
  ForecastLineup,
  MatchForecast,
  Numeric,
  TeamSide,
} from "@/lib/forecast-types";
import { subscribeOfficialForecast } from "@/lib/official-forecast-poller";
import styles from "./match.module.css";

const STATISTICS = [
  ["Shots", "shots"],
  ["On target", "shots_on_target"],
  ["Corners", "corners"],
  ["Fouls", "fouls"],
  ["Yellow cards", "yellow_cards"],
  ["Red cards", "red_cards"],
] as const;

function number(value: Numeric) {
  return Number(value);
}

function percent(value: Numeric) {
  return `${(number(value) * 100).toFixed(1)}%`;
}

function countdown(totalSeconds: number) {
  const remaining = Math.max(0, totalSeconds);
  const days = Math.floor(remaining / 86400);
  const hours = Math.floor((remaining % 86400) / 3600);
  const minutes = Math.floor((remaining % 3600) / 60);
  const seconds = remaining % 60;
  return `${days ? `${days}d ` : ""}${hours.toString().padStart(2, "0")}:${minutes
    .toString()
    .padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
}

function eventMinute(event: ForecastEvent) {
  if (event.event_type === "full_time") return "FT";
  if (event.event_type === "half_time") return "HT";
  return `${event.minute}′`;
}

function Lineup({ lineup, side }: { lineup: ForecastLineup; side: TeamSide }) {
  return (
    <article className={styles.panel}>
      <header className={styles.panelHeader}>
        <div>
          <p className={styles.eyebrow}>{side} expected XI</p>
          <h2>{lineup.club_name}</h2>
        </div>
        <span>{lineup.formation}</span>
      </header>
      <ol className={styles.players}>
        {lineup.starters.map((player) => (
          <li key={player.player_uuid}>
            <b>{player.shirt_number}</b>
            <span>{player.name}</span>
            <small>{player.position}</small>
          </li>
        ))}
      </ol>
      <details className={styles.bench}>
        <summary>Expected bench · {lineup.substitutes.length}</summary>
        <ul>
          {lineup.substitutes.map((player) => (
            <li key={player.player_uuid}>
              {player.shirt_number} · {player.name} · {player.position}
            </li>
          ))}
        </ul>
      </details>
      <p className={styles.confidence}>Lineup confidence {(lineup.confidence * 100).toFixed(0)}%</p>
    </article>
  );
}

function WaitingState({ data }: { data: MatchForecast }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (data.lifecycle_state !== "countdown") return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [data.lifecycle_state, data.prediction_due_at]);

  const messages = {
    countdown: "The backend will generate and lock this match automatically at T-24.",
    generating: "The T-24 job is generating and locking the forecast now.",
    postponed: "This fixture is postponed. Its old forecast is void and no replay is active.",
    cancelled: "This fixture was cancelled. No forecast will be presented.",
    unavailable: "The forecast could not be generated from the currently available evidence.",
    live: "The stored simulation is being revealed.",
    complete: "The stored presentation is complete.",
  } as const;
  const title = data.lifecycle_state === "countdown"
    ? countdown(secondsUntil(data.prediction_due_at, now))
    : data.lifecycle_state === "generating"
      ? "Locking forecast…"
      : "No active simulation";

  return (
    <section
      className={styles.waiting}
      role="status"
      aria-live={data.lifecycle_state === "countdown" ? "off" : "polite"}
    >
      <p className={styles.eyebrow}>{data.lifecycle_state}</p>
      <h2 role={data.lifecycle_state === "countdown" ? "timer" : undefined}>{title}</h2>
      <p>{messages[data.lifecycle_state]}</p>
      <small>Scheduled generation: {new Date(data.prediction_due_at).toLocaleString("en-GB")}</small>
    </section>
  );
}

export function OfficialMatch({ matchUuid }: { matchUuid: string }) {
  const [data, setData] = useState<MatchForecast | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    return subscribeOfficialForecast(matchUuid, {
      onData: (forecast) => {
        setData(forecast);
        setError("");
      },
      onError: setError,
    });
  }, [matchUuid]);

  const events = useMemo(() => data?.simulation?.events ?? [], [data?.simulation?.events]);
  const feed = useMemo(
    () => events.filter((event) => event.event_type !== "kickoff").toReversed(),
    [events],
  );

  if (!data) {
    return (
      <main className={styles.shell} id="main-content">
        <section className={styles.state} role="status" aria-busy={!error}>
          <span>{error ? "API" : "T-24"}</span>
          <h1>{error ? "Official match unavailable" : "Loading official match"}</h1>
          <p>
            {error || "Connecting to the canonical match record. No sample teams will be shown."}
          </p>
          {error ? <small>The page will retry automatically.</small> : null}
        </section>
      </main>
    );
  }

  const simulation = data.simulation;
  const prediction = data.prediction;
  const footballMinute = Math.min(90, Math.floor(data.presentation.football_second / 60));
  const phaseLabel = data.presentation.complete
    ? "FULL TIME"
    : data.presentation.phase === "half_time"
      ? "HALF TIME"
      : `${footballMinute.toString().padStart(2, "0")}:00`;

  return (
    <main className={styles.shell} id="main-content">
      {error ? (
        <div className={styles.connectionNotice} role="status">
          Live connection interrupted. Showing the most recent verified state while retrying.
        </div>
      ) : null}
      <header className={styles.meta}>
        <div>
          <p className={styles.eyebrow}>Premier League · stored T-24 forecast</p>
          <p>Kickoff {new Date(data.kickoff_at).toLocaleString("en-GB")}</p>
        </div>
        <span className={styles.status}>{data.lifecycle_state}</span>
      </header>

      <section className={styles.scoreboard} aria-label={`${data.home.name} versus ${data.away.name}`}>
        <div className={styles.team}>
          <ClubCrest club={data.home} size="large" />
          <div><small>Home</small><h1>{data.home.name}</h1></div>
        </div>
        <div className={styles.scoreCenter}>
          <time>{simulation ? phaseLabel : "T-24"}</time>
          <p>
            {simulation ? simulation.final_score?.home ?? simulation.scoreboard_home : "—"}
            <span>:</span>
            {simulation ? simulation.final_score?.away ?? simulation.scoreboard_away : "—"}
          </p>
          <small>{simulation ? "Automatic 01:00 presentation" : "Awaiting stored simulation"}</small>
        </div>
        <div className={`${styles.team} ${styles.away}`}>
          <div><small>Away</small><h1>{data.away.name}</h1></div>
          <ClubCrest club={data.away} size="large" />
        </div>
      </section>

      {!prediction || !simulation ? (
        <WaitingState data={data} />
      ) : (
        <>
          <section className={styles.forecast} aria-label="Outcome forecast">
            <div><span>Home win</span><strong>{percent(prediction.home_win_probability)}</strong></div>
            <div><span>Draw</span><strong>{percent(prediction.draw_probability)}</strong></div>
            <div><span>Away win</span><strong>{percent(prediction.away_win_probability)}</strong></div>
            <div>
              <span>Expected goals</span>
              <strong>{number(prediction.expected_home_goals).toFixed(2)} – {number(prediction.expected_away_goals).toFixed(2)}</strong>
            </div>
          </section>

          <div className={styles.grid}>
            <section className={styles.mainColumn}>
              <article className={styles.panel}>
                <header className={styles.panelHeader}>
                  <div>
                    <p className={styles.eyebrow}>Synchronized event stream</p>
                    <h2>Match commentary</h2>
                  </div>
                  <span>{events.length} revealed</span>
                </header>
                <div className={styles.feed} aria-live="polite">
                  {feed.length ? feed.slice(0, 14).map((event) => (
                    <div className={styles.event} key={event.event_id}>
                      <time>{eventMinute(event)}</time>
                      <b>{event.event_type.replaceAll("_", " ")}</b>
                      <p>{event.commentary}</p>
                      <strong>{event.home_score}:{event.away_score}</strong>
                    </div>
                  )) : <p className={styles.empty}>Kick-off is about to be revealed automatically.</p>}
                </div>
              </article>

              <article className={styles.panel}>
                <header className={styles.panelHeader}>
                  <div>
                    <p className={styles.eyebrow}>Match statistics</p>
                    <h2>{data.presentation.complete ? "Final simulation" : "As revealed"}</h2>
                  </div>
                </header>
                <div className={styles.statistics}>
                  {STATISTICS.map(([label, key]) => {
                    const home = simulation.visible_statistics[`home_${key}`] ?? 0;
                    const away = simulation.visible_statistics[`away_${key}`] ?? 0;
                    const total = Math.max(1, home + away);
                    return (
                      <div className={styles.stat} key={key}>
                        <strong>{home}</strong>
                        <div>
                          <span>{label}</span>
                          <i aria-hidden="true">
                            <b style={{ width: `${home / total * 100}%` }} />
                            <em style={{ width: `${away / total * 100}%` }} />
                          </i>
                        </div>
                        <strong>{away}</strong>
                      </div>
                    );
                  })}
                </div>
              </article>
            </section>
            <aside className={styles.lineups} aria-label="Expected lineups">
              <Lineup lineup={prediction.expected_lineups.home} side="home" />
              <Lineup lineup={prediction.expected_lineups.away} side="away" />
            </aside>
          </div>
          <footer className={styles.integrity}>
            <div><span>Outcome model</span><b>{prediction.model_version}</b></div>
            <div><span>Locked</span><b>{new Date(prediction.locked_at).toLocaleString("en-GB")}</b></div>
            <div><span>Simulation SHA-256</span><b>{simulation.checksum}</b></div>
          </footer>
        </>
      )}
    </main>
  );
}
