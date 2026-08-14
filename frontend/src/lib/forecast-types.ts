export type LifecycleState =
  | "countdown"
  | "generating"
  | "live"
  | "complete"
  | "postponed"
  | "cancelled"
  | "unavailable"
  | "locked"
  | "available"
  | "missed"
  | "void"
  | "stale";

export type TeamSide = "home" | "away";
export type Numeric = number | string;

export interface ClubSummary {
  club_uuid: string;
  name: string;
  short_name: string;
  crest_url: string | null;
}

export interface UpcomingMatch {
  match_uuid: string;
  fixture_status: string;
  kickoff_at: string;
  prediction_due_at: string;
  home: ClubSummary;
  away: ClubSummary;
}

export interface ForecastPlayer {
  player_uuid: string;
  name: string;
  position: "GK" | "DEF" | "MID" | "FWD";
  shirt_number: number;
  shirt_number_source: "observed" | "presentation_slot";
  starting_probability: number;
  availability_probability: number;
}

export interface ForecastLineup {
  club_uuid: string;
  club_name: string;
  short_name: string;
  formation: string;
  confidence: number;
  starters: ForecastPlayer[];
  substitutes: ForecastPlayer[];
}

export interface ForecastEvent {
  event_id: string;
  minute: number;
  second: number;
  event_type: string;
  team: TeamSide | null;
  player_uuid: string | null;
  player_name: string | null;
  secondary_player_uuid: string | null;
  secondary_player_name: string | null;
  commentary: string;
  home_score: number;
  away_score: number;
}

export interface MatchForecast {
  match_uuid: string;
  fixture_status: string;
  lifecycle_state: LifecycleState;
  kickoff_at: string;
  prediction_due_at: string;
  seconds_until_generation: number;
  seconds_until_play: number;
  schedule_revision_uuid: string | null;
  schedule_revision_number: number | null;
  window_opens_at: string | null;
  window_closes_at: string | null;
  data_current: boolean;
  play_classification: string | null;
  generated_at: string | null;
  home: ClubSummary;
  away: ClubSummary;
  prediction: null | {
    prediction_version_uuid: string | null;
    version_number: number | null;
    locked_at: string;
    feature_cutoff_at: string;
    feature_snapshot_checksum: string;
    model_version: string;
    expected_home_goals: Numeric;
    expected_away_goals: Numeric;
    home_win_probability: Numeric;
    draw_probability: Numeric;
    away_win_probability: Numeric;
    statistics_distribution: {
      statistics_model_version?: string;
      means?: Record<string, Numeric>;
      intervals_90?: Record<string, [Numeric, Numeric]>;
    };
    expected_lineups: {
      schema_version: string;
      home: ForecastLineup;
      away: ForecastLineup;
    };
  };
  presentation: {
    started_at: string | null;
    duration_seconds: number;
    phase: string;
    elapsed_seconds: number;
    remaining_seconds: number;
    football_second: number;
    complete: boolean;
  };
  simulation: null | {
    simulation_uuid: string;
    checksum: string;
    scoreboard_home: number;
    scoreboard_away: number;
    events: ForecastEvent[];
    visible_statistics: Record<string, number>;
    final_score: { home: number; away: number } | null;
    final_statistics: Record<string, Numeric> | null;
  };
}
