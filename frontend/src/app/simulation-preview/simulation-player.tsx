"use client";

import { useEffect, useMemo, useState } from "react";
import type {
  SimulationEvent,
  SimulationEventType,
  SimulationLineup,
  SimulationPreviewData,
  TeamSide,
} from "./simulation-types";
import styles from "./simulation.module.css";

const MATCH_SECONDS = 90 * 60;

const EVENT_LABELS: Record<SimulationEventType, string> = {
  kickoff: "KO",
  shot: "SH",
  shot_on_target: "SOT",
  goal: "GOAL",
  corner: "COR",
  foul: "FK",
  yellow_card: "YC",
  red_card: "RC",
  substitution: "SUB",
  half_time: "HT",
  second_half: "2H",
  full_time: "FT",
};

const STAT_ROWS = [
  ["Shots", "shots"],
  ["On target", "shots_on_target"],
  ["Corners", "corners"],
  ["Fouls", "fouls"],
  ["Yellow cards", "yellow_cards"],
  ["Red cards", "red_cards"],
] as const;

function eventSecond(event: SimulationEvent) {
  return event.minute * 60 + event.second;
}

function displayedTime(totalSeconds: number) {
  const minute = Math.floor(totalSeconds / 60)
    .toString()
    .padStart(2, "0");
  const second = Math.floor(totalSeconds % 60)
    .toString()
    .padStart(2, "0");
  return `${minute}:${second}`;
}

function simulationSecondForPresentation(
  elapsedSeconds: number,
  firstHalfSeconds: number,
  halfTimeSeconds: number,
  secondHalfSeconds: number,
) {
  if (elapsedSeconds <= firstHalfSeconds) {
    return (elapsedSeconds / firstHalfSeconds) * (MATCH_SECONDS / 2);
  }
  if (elapsedSeconds < firstHalfSeconds + halfTimeSeconds) {
    return MATCH_SECONDS / 2;
  }
  const secondHalfElapsed = elapsedSeconds - firstHalfSeconds - halfTimeSeconds;
  return Math.min(
    MATCH_SECONDS,
    MATCH_SECONDS / 2 + (secondHalfElapsed / secondHalfSeconds) * (MATCH_SECONDS / 2),
  );
}

function eventMinute(event: SimulationEvent) {
  if (event.event_type === "full_time") return "FT";
  if (event.event_type === "half_time") return "HT";
  return `${event.minute}’`;
}

function currentStatistic(events: SimulationEvent[], side: TeamSide, statistic: string) {
  return events.filter((event) => {
    if (event.team !== side) return false;
    if (statistic === "shots") {
      return ["shot", "shot_on_target", "goal"].includes(event.event_type);
    }
    if (statistic === "shots_on_target") {
      return ["shot_on_target", "goal"].includes(event.event_type);
    }
    return event.event_type === statistic.replace(/s$/, "").replace("card", "card");
  }).length;
}

function statisticValue(events: SimulationEvent[], side: TeamSide, statistic: string) {
  const eventType: Partial<Record<string, SimulationEventType>> = {
    corners: "corner",
    fouls: "foul",
    yellow_cards: "yellow_card",
    red_cards: "red_card",
  };
  if (statistic === "shots" || statistic === "shots_on_target") {
    return currentStatistic(events, side, statistic);
  }
  return events.filter(
    (event) => event.team === side && event.event_type === eventType[statistic],
  ).length;
}

function TeamMark({ lineup }: { lineup: SimulationLineup }) {
  return (
    <span className={styles.teamMark} aria-hidden="true">
      {lineup.short_name}
    </span>
  );
}

function LineupCard({ lineup, side }: { lineup: SimulationLineup; side: TeamSide }) {
  return (
    <article className={styles.lineupCard}>
      <header className={styles.lineupHeader}>
        <div>
          <p className={styles.eyebrow}>{side} expected XI</p>
          <h3>{lineup.club_name}</h3>
        </div>
        <span className={styles.formation}>{lineup.formation}</span>
      </header>
      <ol className={styles.playerList}>
        {lineup.starters.map((player) => (
          <li key={player.player_uuid}>
            <span className={styles.shirt}>{player.shirt_number}</span>
            <span>{player.name}</span>
            <span className={styles.position}>{player.position}</span>
          </li>
        ))}
      </ol>
      <details className={styles.bench}>
        <summary>Bench · {lineup.substitutes.length}</summary>
        <ul>
          {lineup.substitutes.map((player) => (
            <li key={player.player_uuid}>
              {player.shirt_number} · {player.name} · {player.position}
            </li>
          ))}
        </ul>
      </details>
    </article>
  );
}

export function SimulationPlayerView({ data }: { data: SimulationPreviewData }) {
  const { preview, simulation } = data;
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (!playing) return;
    let previousTick = performance.now();
    const timer = window.setInterval(() => {
      const currentTick = performance.now();
      const elapsedSinceTick = (currentTick - previousTick) / 1000;
      previousTick = currentTick;
      setElapsedSeconds((current) => {
        const next = Math.min(
          preview.presentation_duration_seconds,
          current + elapsedSinceTick,
        );
        if (next >= preview.presentation_duration_seconds) setPlaying(false);
        return next;
      });
    }, 100);
    return () => window.clearInterval(timer);
  }, [playing, preview.presentation_duration_seconds]);

  const simulationSecond = simulationSecondForPresentation(
    elapsedSeconds,
    preview.first_half_seconds,
    preview.half_time_seconds,
    preview.second_half_seconds,
  );
  const atHalfTime =
    elapsedSeconds >= preview.first_half_seconds &&
    elapsedSeconds < preview.first_half_seconds + preview.half_time_seconds;

  const visibleEvents = useMemo(
    () => simulation.events.filter((event) => eventSecond(event) <= simulationSecond),
    [simulation.events, simulationSecond],
  );
  const latestEvent = visibleEvents.at(-1);
  const visibleFeed = visibleEvents.filter((event) => event.event_type !== "kickoff").toReversed();
  const homeScore = latestEvent?.home_score ?? 0;
  const awayScore = latestEvent?.away_score ?? 0;
  const finished = elapsedSeconds >= preview.presentation_duration_seconds;

  const restart = () => {
    setElapsedSeconds(0);
    setPlaying(true);
  };

  const togglePlayback = () => {
    if (finished) {
      restart();
      return;
    }
    setPlaying((current) => !current);
  };

  return (
    <div className={styles.shell}>
      <header className={styles.topbar}>
        <div>
          <p className={styles.eyebrow}>{preview.competition}</p>
          <p className={styles.matchMeta}>
            Matchweek {preview.matchweek} · {preview.venue}
          </p>
        </div>
        <div className={styles.lockBadge}>
          <span aria-hidden="true">◆</span>
          Locked simulation
        </div>
      </header>

      <p className={styles.notice}>{preview.notice}</p>

      <section className={styles.scoreboard} aria-label="Simulation scoreboard">
        <div className={styles.teamHome}>
          <TeamMark lineup={simulation.home_team} />
          <div>
            <p className={styles.teamRole}>Home</p>
            <h1>{simulation.home_team.club_name}</h1>
          </div>
        </div>
        <div className={styles.scoreCenter}>
          <p className={styles.clock}>
            {finished ? "FULL TIME" : atHalfTime ? "HALF TIME" : displayedTime(simulationSecond)}
          </p>
          <p className={styles.score} aria-live="polite">
            {homeScore}<span>:</span>{awayScore}
          </p>
          <p className={styles.seed}>Seed {simulation.random_seed}</p>
        </div>
        <div className={styles.teamAway}>
          <div>
            <p className={styles.teamRole}>Away</p>
            <h1>{simulation.away_team.club_name}</h1>
          </div>
          <TeamMark lineup={simulation.away_team} />
        </div>
      </section>

      <section className={styles.controls} aria-label="Playback controls">
        <button type="button" onClick={togglePlayback}>
          {playing ? "Pause" : finished ? "Replay" : "Play"}
        </button>
        <button type="button" className={styles.secondaryButton} onClick={restart}>
          Restart
        </button>
        <label className={styles.timelineLabel}>
          <span className="sr-only">Match position</span>
          <input
            aria-label="Match position"
            type="range"
            min="0"
            max={preview.presentation_duration_seconds}
            step="0.1"
            value={elapsedSeconds}
            onChange={(event) => {
              setElapsedSeconds(Number(event.target.value));
              setPlaying(false);
            }}
          />
        </label>
        <p className={styles.durationBadge}>01:00 fixed</p>
      </section>

      <section className={styles.forecastStrip} aria-label="Pre-match forecast">
        <div>
          <span>Home win</span>
          <strong>{(simulation.home_win_probability * 100).toFixed(1)}%</strong>
        </div>
        <div>
          <span>Draw</span>
          <strong>{(simulation.draw_probability * 100).toFixed(1)}%</strong>
        </div>
        <div>
          <span>Away win</span>
          <strong>{(simulation.away_win_probability * 100).toFixed(1)}%</strong>
        </div>
        <div>
          <span>Expected goals</span>
          <strong>
            {simulation.expected_home_goals.toFixed(2)} – {simulation.expected_away_goals.toFixed(2)}
          </strong>
        </div>
      </section>

      <main className={styles.matchGrid}>
        <section className={styles.liveColumn}>
          <article className={styles.liveMoment}>
            <div>
              <p className={styles.eyebrow}>Live match pulse</p>
              <p className={styles.momentMinute}>{latestEvent ? eventMinute(latestEvent) : "PRE"}</p>
            </div>
            <div className={styles.momentCopy} aria-live="polite">
              <span className={styles.eventTag}>
                {latestEvent ? EVENT_LABELS[latestEvent.event_type] : "READY"}
              </span>
              <p>{latestEvent?.commentary ?? "Press play to begin the stored match replay."}</p>
            </div>
          </article>

          <article className={styles.panel}>
            <header className={styles.panelHeader}>
              <div>
                <p className={styles.eyebrow}>Match statistics</p>
                <h2>As it happened</h2>
              </div>
              <span>{finished ? "Final" : "Live"}</span>
            </header>
            <div className={styles.statistics}>
              {STAT_ROWS.map(([label, key]) => {
                const homeValue = statisticValue(visibleEvents, "home", key);
                const awayValue = statisticValue(visibleEvents, "away", key);
                const total = Math.max(1, homeValue + awayValue);
                return (
                  <div className={styles.statRow} key={key}>
                    <strong>{homeValue}</strong>
                    <div>
                      <span>{label}</span>
                      <div className={styles.statBar}>
                        <i style={{ width: `${(homeValue / total) * 100}%` }} />
                        <b style={{ width: `${(awayValue / total) * 100}%` }} />
                      </div>
                    </div>
                    <strong>{awayValue}</strong>
                  </div>
                );
              })}
            </div>
          </article>

          <article className={styles.panel}>
            <header className={styles.panelHeader}>
              <div>
                <p className={styles.eyebrow}>Stored event stream</p>
                <h2>Match commentary</h2>
              </div>
              <span>{visibleEvents.length}/{simulation.events.length} events</span>
            </header>
            <div className={styles.eventFeed} aria-live="polite">
              {visibleFeed.length === 0 ? (
                <p className={styles.emptyFeed}>No events yet. The simulation is waiting at kick-off.</p>
              ) : (
                visibleFeed.slice(0, 12).map((event) => (
                  <div className={styles.eventRow} key={event.event_id}>
                    <time>{eventMinute(event)}</time>
                    <span className={styles.eventTag}>{EVENT_LABELS[event.event_type]}</span>
                    <div>
                      <strong>
                        {event.team === "home"
                          ? simulation.home_team.short_name
                          : event.team === "away"
                            ? simulation.away_team.short_name
                            : "MATCH"}
                      </strong>
                      <p>{event.commentary}</p>
                    </div>
                    <b>{event.home_score}:{event.away_score}</b>
                  </div>
                ))
              )}
            </div>
          </article>
        </section>

        <aside className={styles.lineupColumn}>
          <LineupCard lineup={simulation.home_team} side="home" />
          <LineupCard lineup={simulation.away_team} side="away" />
        </aside>
      </main>

      <footer className={styles.integrity}>
        <div>
          <p className={styles.eyebrow}>Locked forecast provenance</p>
          <p>Outcome · {simulation.outcome_model_version}</p>
          <p>Statistics · {simulation.statistics_model_version}</p>
        </div>
        <div>
          <p>Locked {new Date(simulation.locked_at).toLocaleString("en-GB", { timeZone: "UTC" })} UTC</p>
          <p className={styles.checksum}>SHA-256 · {simulation.checksum}</p>
        </div>
      </footer>
    </div>
  );
}
