"use client";

import { useEffect, useMemo, useState } from "react";
import { ClubCrest } from "./club-crest";
import { getOrCreateDeviceUuid } from "@/lib/device-identity";
import type { StandingsOverview, StandingsRow, StandingsTable } from "@/lib/insights-types";
import styles from "@/app/insights.module.css";

function goalDifference(value: number) {
  return value > 0 ? `+${value}` : value.toString();
}

function StandingsTableView({
  table,
  comparison,
}: {
  table: StandingsTable;
  comparison?: Map<string, StandingsRow>;
}) {
  const isSimulation = table.kind === "simulated";
  return (
    <article className={styles.tablePanel}>
      <header className={styles.tableHeader}>
        <div>
          <span className={styles.tableMeta}>{isSimulation ? "Prem Engine timeline" : "Official results"}</span>
          <h2>{isSimulation ? "Simulated table" : "Real table"}</h2>
        </div>
        <p>{table.source_fixture_count} matches included</p>
      </header>
      <div className={styles.tableScroll}>
        <table className={styles.standingsTable}>
          <caption className="sr-only">
            {isSimulation ? "Simulated Premier League standings" : "Real Premier League standings"}
          </caption>
          <thead>
            <tr>
              <th scope="col">Pos</th><th scope="col">Club</th><th scope="col">P</th>
              <th scope="col">W</th><th scope="col">D</th><th scope="col">L</th>
              <th scope="col">GF</th><th scope="col">GA</th><th scope="col">GD</th>
              <th scope="col">Pts</th>{isSimulation ? <th scope="col">vs real</th> : null}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row) => {
              const realRow = comparison?.get(row.club.club_uuid);
              const positionDifference = realRow ? realRow.position - row.position : null;
              return (
                <tr key={row.club.club_uuid}>
                  <td className={styles.position}>{row.position}</td>
                  <th scope="row">
                    <span className={styles.clubCell}>
                      <ClubCrest club={row.club} size="small" />
                      <strong>{row.club.name}</strong>
                    </span>
                  </th>
                  <td>{row.played}</td><td>{row.won}</td><td>{row.drawn}</td><td>{row.lost}</td>
                  <td>{row.goals_for}</td><td>{row.goals_against}</td>
                  <td>{goalDifference(row.goal_difference)}</td>
                  <td className={styles.points}>{row.points}</td>
                  {isSimulation ? (
                    <td className={styles.difference}>
                      {positionDifference === null
                        ? "—"
                        : positionDifference > 0
                          ? `↑ ${positionDifference}`
                          : positionDifference < 0
                            ? `↓ ${Math.abs(positionDifference)}`
                            : "—"}
                    </td>
                  ) : null}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function FairComparison({ data }: { data: StandingsOverview }) {
  const simulated = new Map(
    data.fair_comparison.simulated_rows.map((row) => [row.club.club_uuid, row]),
  );
  if (!data.fair_comparison.source_fixture_count) {
    return (
      <div className={styles.state}>
        <span>0–0</span>
        <h2>No paired matches yet</h2>
        <p>
          This comparison starts when a match has both an accepted real result and an active stored
          simulation. It will not compare unequal fixture sets.
        </p>
      </div>
    );
  }
  return (
    <>
      <header className={styles.comparisonIntro}>
        <div>
          <span className={styles.tableMeta}>Like-for-like view</span>
          <h2>Same matches. Different timeline.</h2>
        </div>
        <p>
          Both columns below use exactly the same {data.fair_comparison.source_fixture_count} completed
          fixtures, so differences cannot be caused by one table being further ahead.
        </p>
      </header>
      <div className={styles.tableScroll}>
        <table className={styles.comparisonTable}>
          <caption className="sr-only">Fair comparison of real and simulated standings</caption>
          <thead>
            <tr>
              <th scope="col">Real pos</th><th scope="col">Club</th><th scope="col">P</th>
              <th scope="col">Real pts</th><th scope="col">Sim pos</th>
              <th scope="col">Sim pts</th><th scope="col">Point difference</th>
            </tr>
          </thead>
          <tbody>
            {data.fair_comparison.real_rows.map((realRow) => {
              const simulatedRow = simulated.get(realRow.club.club_uuid);
              const pointDifference = (simulatedRow?.points ?? 0) - realRow.points;
              return (
                <tr key={realRow.club.club_uuid}>
                  <td className={styles.position}>{realRow.position}</td>
                  <th scope="row">
                    <span className={styles.clubCell}>
                      <ClubCrest club={realRow.club} size="small" />
                      <strong>{realRow.club.name}</strong>
                    </span>
                  </th>
                  <td>{realRow.played}</td><td>{realRow.points}</td>
                  <td>{simulatedRow?.position ?? "—"}</td><td>{simulatedRow?.points ?? "—"}</td>
                  <td className={styles.points}>{goalDifference(pointDifference)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function StandingsDashboard() {
  const [data, setData] = useState<StandingsOverview | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [deviceUuid] = useState<string | null>(() =>
    typeof window === "undefined" ? null : getOrCreateDeviceUuid()
  );

  useEffect(() => {
    if (!deviceUuid) return;
    const controller = new AbortController();
    fetch(`/api/standings?device_uuid=${encodeURIComponent(deviceUuid)}`, {
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        const payload = (await response.json()) as StandingsOverview | { detail?: string };
        if (!response.ok || !("real" in payload)) {
          throw new Error("detail" in payload && payload.detail ? payload.detail : "Standings are unavailable.");
        }
        return payload;
      })
      .then((payload) => {
        setData(payload);
        setError("");
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Could not load standings.");
        }
      });
    return () => controller.abort();
  }, [attempt, deviceUuid]);

  const realPositions = useMemo(
    () => new Map(data?.real.rows.map((row) => [row.club.club_uuid, row]) ?? []),
    [data?.real.rows],
  );

  if (!data && !error) {
    return <div className={styles.loading} aria-label="Loading standings" aria-busy="true">
      <span /><span /><span />
    </div>;
  }
  if (!data) {
    return <div className={styles.state} role="alert">
      <span>API</span><h2>Tables could not be calculated</h2>
      <p>{error} No provider table or sample values will be substituted.</p>
      <button type="button" onClick={() => { setError(""); setAttempt((value) => value + 1); }}>
        Try again
      </button>
    </div>;
  }
  if (!data.season) {
    return <div className={styles.state} role="status">
      <span>00</span><h2>No canonical season is loaded</h2>
      <p>The tables will appear after a Premier League season and its clubs are imported.</p>
    </div>;
  }

  return (
    <>
      <div className={styles.summaryStrip}>
        <div><span>Season</span><strong>{data.season.label}</strong></div>
        <div><span>Real matches</span><strong>{data.real.source_fixture_count}</strong></div>
        <div><span>Coverage</span><strong>{data.coverage.played} of {data.coverage.eligible}</strong></div>
        <div><span>Missed</span><strong>{data.coverage.missed}</strong></div>
      </div>
      <div className={styles.tablesGrid}>
        <StandingsTableView table={data.real} />
        <StandingsTableView table={data.simulated} comparison={realPositions} />
      </div>
      <FairComparison data={data} />
      <p className={styles.methodNote}>
        Real standings use accepted official results only. Your simulated standings count each
        completed Play once. Missed and void schedule revisions never add games, goals, or points.
      </p>
    </>
  );
}
