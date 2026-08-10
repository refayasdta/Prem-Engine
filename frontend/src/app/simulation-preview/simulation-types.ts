export type TeamSide = "home" | "away";

export type SimulationEventType =
  | "kickoff"
  | "shot"
  | "shot_on_target"
  | "goal"
  | "corner"
  | "foul"
  | "yellow_card"
  | "red_card"
  | "substitution"
  | "half_time"
  | "second_half"
  | "full_time";

export interface SimulationPlayer {
  player_uuid: string;
  name: string;
  position: "GK" | "DEF" | "MID" | "FWD";
  shirt_number: number;
}

export interface SimulationLineup {
  club_uuid: string;
  club_name: string;
  short_name: string;
  formation: string;
  starters: SimulationPlayer[];
  substitutes: SimulationPlayer[];
}

export interface SimulationEvent {
  event_id: string;
  minute: number;
  second: number;
  event_type: SimulationEventType;
  team: TeamSide | null;
  player_uuid: string | null;
  player_name: string | null;
  secondary_player_uuid: string | null;
  secondary_player_name: string | null;
  commentary: string;
  home_score: number;
  away_score: number;
}

export interface StoredSimulation {
  schema_version: string;
  simulation_uuid: string;
  match_uuid: string;
  prediction_version_uuid: string;
  random_seed: number;
  feature_cutoff_at: string;
  locked_at: string;
  outcome_model_version: string;
  statistics_model_version: string;
  expected_home_goals: number;
  expected_away_goals: number;
  home_win_probability: number;
  draw_probability: number;
  away_win_probability: number;
  home_team: SimulationLineup;
  away_team: SimulationLineup;
  home_goals: number;
  away_goals: number;
  statistics: Record<string, number>;
  events: SimulationEvent[];
  checksum: string;
}

export interface SimulationPreviewData {
  preview: {
    is_sample_data: boolean;
    notice: string;
    competition: string;
    matchweek: number;
    kickoff_at: string;
    venue: string;
    presentation_duration_seconds: number;
    first_half_seconds: number;
    half_time_seconds: number;
    second_half_seconds: number;
  };
  simulation: StoredSimulation;
}
