"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ClubCrest } from "./club-crest";
import type { EvaluationOverview, MatchEvaluation } from "@/lib/insights-types";
import styles from "@/app/insights.module.css";

const METRICS = [
  ["Outcome accuracy", "outcome_accuracy", "How often the highest forecast probability matched the real outcome.", "percent"],
  ["Probability log loss", "log_loss", "Lower is better. Confident wrong forecasts receive the largest penalty.", "decimal"],
  ["Brier score", "brier_score", "Lower is better. Measures error across home, draw, and away probabilities.", "decimal"],
  ["Ranked probability", "ranked_probability_score", "Lower is better. Respects the ordered distance between outcomes.", "decimal"],
  ["Calibration error", "expected_calibration_error", "Lower is better. Compares stated confidence with observed frequency.", "decimal"],
  ["Expected-goal MAE", "expected_goal_mae", "Lower is better. Average absolute goal error per team.", "goals"],
  ["Simulation outcome", "simulation_outcome_accuracy", "How often the one stored simulated result got the outcome right.", "percent"],
  ["Exact sim score", "exact_simulated_score_accuracy", "How often the stored simulation matched the full real scoreline.", "percent"],
] as const;

function formatMetric(value: number | null, kind: "percent" | "decimal" | "goals") {
  if (value === null) return "—";
  if (kind === "percent") return `${(value * 100).toFixed(1)}%`;
  if (kind === "goals") return value.toFixed(2);
  return value.toFixed(3);
}

function probabilityForPick(match: MatchEvaluation) {
  const value = match.forecast_outcome === "home"
    ? match.home_win_probability
    : match.forecast_outcome === "draw"
      ? match.draw_probability
      : match.away_win_probability;
  return `${(Number(value) * 100).toFixed(0)}%`;
}

function outcomeName(value: "home" | "draw" | "away", match: MatchEvaluation) {
  if (value === "home") return match.home.short_name;
  if (value === "away") return match.away.short_name;
  return "Draw";
}

export function EvaluationDashboard() {
  const [data, setData] = useState<EvaluationOverview | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/evaluation", { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        const payload = (await response.json()) as EvaluationOverview | { detail?: string };
        if (!response.ok || !("metrics" in payload)) {
          throw new Error("detail" in payload && payload.detail ? payload.detail : "Evaluation is unavailable.");
        }
        return payload;
      })
      .then((payload) => {
        setData(payload);
        setError("");
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Could not load evaluation.");
        }
      });
    return () => controller.abort();
  }, [attempt]);

  if (!data && !error) {
    return <div className={styles.loading} aria-label="Loading evaluation" aria-busy="true">
      <span /><span /><span />
    </div>;
  }
  if (!data) {
    return <div className={styles.state} role="alert">
      <span>API</span><h2>Evaluation could not be calculated</h2>
      <p>{error} No placeholder accuracy will be shown.</p>
      <button type="button" onClick={() => { setError(""); setAttempt((value) => value + 1); }}>
        Try again
      </button>
    </div>;
  }
  if (!data.season) {
    return <div className={styles.state} role="status">
      <span>00</span><h2>No canonical season is loaded</h2>
      <p>Evaluation begins after the season, locked predictions, and real results are available.</p>
    </div>;
  }

  return (
    <>
      <section className={styles.evaluationLead}>
        <div>
          <span className={styles.tableMeta}>Live accountability report</span>
          <h2>OptiMatch Performance</h2>
          <p>
            These figures are recalculated from immutable OptiMatch Model forecasts paired with
            accepted real results. They are not the historical training score and they never
            rewrite a pick.
          </p>
        </div>
        <div>
          <dl>
            <div><dt>Season</dt><dd>{data.season.label}</dd></div>
            <div><dt>Paired matches</dt><dd>{data.paired_fixture_count}</dd></div>
            <div><dt>Metric sample</dt><dd>{data.metrics.sample_count}</dd></div>
            <div><dt>Exceptional exclusions</dt><dd>{data.metrics.excluded_count}</dd></div>
            <div><dt>Official model</dt><dd>OptiMatch Model</dd></div>
          </dl>
        </div>
      </section>

      {data.metrics.sample_count ? (
        <section className={styles.metricsGrid} aria-label="Forecast accuracy metrics">
          {METRICS.map(([label, key, explanation, kind]) => (
            <article className={styles.metricCard} key={key}>
              <span>{label}</span>
              <strong>{formatMetric(data.metrics[key], kind)}</strong>
              <p>{explanation}</p>
            </article>
          ))}
        </section>
      ) : (
        <div className={styles.state} role="status">
          <span>0%</span><h2>No ordinary results to score yet</h2>
          <p>
            Metrics appear only after a locked forecast is paired with an accepted result. Awarded
            fixtures remain visible below but are excluded from ordinary accuracy.
          </p>
        </div>
      )}

      <section>
        <header className={styles.historyHeader}>
          <div><span className={styles.tableMeta}>Match-by-match evidence</span><h2>Forecast ledger</h2></div>
          <p>Every row keeps the stored simulation and real result separate. Open the match for its full provenance.</p>
        </header>
        {data.matches.length ? (
          <div className={styles.tableScroll}>
            <table className={styles.historyTable}>
              <caption className="sr-only">Evaluated official forecasts</caption>
              <thead>
                <tr><th scope="col">Match</th><th scope="col">Most likely</th><th scope="col">Expected goals</th><th scope="col">Simulation</th><th scope="col">Actual</th><th scope="col">Outcome pick</th><th scope="col">Status</th></tr>
              </thead>
              <tbody>
                {data.matches.map((match) => (
                  <tr key={match.match_uuid}>
                    <th scope="row">
                      <Link className={styles.historyClubs} href={`/matches/${match.match_uuid}`}>
                        <ClubCrest club={match.home} size="small" />
                        <strong>{match.home.short_name} vs {match.away.short_name}</strong>
                        <ClubCrest club={match.away} size="small" />
                      </Link>
                    </th>
                    <td>{outcomeName(match.forecast_outcome, match)} · {probabilityForPick(match)}</td>
                    <td className={styles.score}>{Number(match.expected_home_goals).toFixed(2)}–{Number(match.expected_away_goals).toFixed(2)}</td>
                    <td className={styles.score}>{match.simulated_home_goals}–{match.simulated_away_goals}</td>
                    <td className={styles.score}>{match.actual_home_goals}–{match.actual_away_goals}</td>
                    <td><span className={styles.verdict} data-correct={match.forecast_outcome_correct}>{match.forecast_outcome_correct ? "Correct" : "Wrong"}</span></td>
                    <td>{match.included_in_aggregate ? "Included" : `${match.result_kind} · excluded`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className={styles.state} role="status">
            <span>00</span><h2>No forecasts have real results yet</h2>
            <p>The ledger will populate automatically as accepted results arrive.</p>
          </div>
        )}
      </section>
      <p className={styles.methodNote}>
        Lower is better for log loss, Brier score, ranked probability score, calibration error, and
        expected-goal MAE. Awarded results are excluded from ordinary metrics because they were not
        produced by normal match play.
      </p>
    </>
  );
}
