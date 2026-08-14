import type { ClubSummary, Numeric } from "./forecast-types";

export interface SeasonSummary {
  season_uuid: string;
  label: string;
  start_date: string;
  end_date: string;
}

export interface StandingsRow {
  position: number;
  club: ClubSummary;
  played: number;
  won: number;
  drawn: number;
  lost: number;
  goals_for: number;
  goals_against: number;
  goal_difference: number;
  points: number;
}

export interface StandingsTable {
  kind: "real" | "simulated";
  calculation_version: string;
  source_fixture_count: number;
  rows: StandingsRow[];
}

export interface StandingsOverview {
  season: SeasonSummary | null;
  calculated_at: string;
  real: StandingsTable;
  simulated: StandingsTable;
  fair_comparison: {
    source_fixture_count: number;
    real_rows: StandingsRow[];
    simulated_rows: StandingsRow[];
  };
  coverage: {
    eligible: number;
    played: number;
    missed: number;
    void: number;
  };
}

export interface EvaluationMetrics {
  calculation_version: string;
  sample_count: number;
  excluded_count: number;
  outcome_accuracy: number | null;
  simulation_outcome_accuracy: number | null;
  exact_simulated_score_accuracy: number | null;
  log_loss: number | null;
  brier_score: number | null;
  ranked_probability_score: number | null;
  expected_goal_mae: number | null;
  expected_calibration_error: number | null;
}

export interface MatchEvaluation {
  match_uuid: string;
  kickoff_at: string;
  home: ClubSummary;
  away: ClubSummary;
  model_version: string;
  home_win_probability: Numeric;
  draw_probability: Numeric;
  away_win_probability: Numeric;
  expected_home_goals: Numeric;
  expected_away_goals: Numeric;
  simulated_home_goals: number;
  simulated_away_goals: number;
  actual_home_goals: number;
  actual_away_goals: number;
  actual_outcome: "home" | "draw" | "away";
  forecast_outcome: "home" | "draw" | "away";
  simulation_outcome: "home" | "draw" | "away";
  forecast_outcome_correct: boolean;
  simulation_outcome_correct: boolean;
  exact_simulated_score_correct: boolean;
  result_kind: string;
  included_in_aggregate: boolean;
}

export interface EvaluationOverview {
  season: SeasonSummary | null;
  calculated_at: string;
  paired_fixture_count: number;
  metrics: EvaluationMetrics;
  matches: MatchEvaluation[];
}
