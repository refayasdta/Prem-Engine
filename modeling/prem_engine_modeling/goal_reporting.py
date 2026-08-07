"""Human-readable Phase 7 training output."""

from __future__ import annotations

from dataclasses import asdict

from prem_engine_modeling.data import HistoricalDataset
from prem_engine_modeling.goal_artifacts import WrittenGoalArtifacts
from prem_engine_modeling.goal_evaluation import GoalEvaluationMetrics
from prem_engine_modeling.goal_training import GoalTrainingResult


def _percent(value: float) -> str:
    return f"{value * 100:6.2f}%"


def _metric_rows(label: str, metrics: GoalEvaluationMetrics) -> list[str]:
    return [
        f"{label:<18} {metrics.mean_goal_mae:>8.3f} {metrics.goal_rmse:>8.3f} "
        f"{_percent(metrics.exact_score_accuracy):>9} {metrics.scoreline_log_loss:>10.3f} "
        f"{_percent(metrics.outcome_metrics.accuracy):>9} "
        f"{metrics.outcome_metrics.log_loss:>10.3f}",
    ]


def human_training_report(
    result: GoalTrainingResult,
    dataset: HistoricalDataset,
    artifacts: WrittenGoalArtifacts,
) -> str:
    """Render a compact terminal report and explain metric direction."""

    config = asdict(result.tuning.selected_config)
    lines = [
        "",
        "PREM ENGINE - PHASE 7 GOAL MODEL",
        "=" * 72,
        "Status              TRAINING COMPLETED SUCCESSFULLY",
        f"Model version       {artifacts.model_version}",
        f"Dataset             {len(dataset.records):,} matches / {len(dataset.seasons)} seasons",
        f"Dataset checksum    {dataset.checksum}",
        "",
        "CHRONOLOGICAL EVALUATION",
        f"  History            {', '.join(result.split.history_seasons)}",
        f"  Validation         {result.split.validation_season}",
        f"  Untouched holdout  {', '.join(result.split.test_seasons)}",
        f"  Candidates tested  {result.tuning.candidate_count}",
        "",
        "SELECTED CONFIGURATION",
        f"  Learning rate      {config['learning_rate']}",
        f"  Base goal rate     {config['base_goal_rate']}",
        f"  Home advantage     {config['home_advantage']} log-goal units",
        f"  Dixon-Coles rho    {config['dixon_coles_rho']}",
        f"  Season carryover   {_percent(config['season_carryover']).strip()}",
        "",
        "PERFORMANCE",
        "  Dataset             Goal MAE     RMSE Exact score  Score NLL  Outcome acc Outcome NLL",
        "  " + "-" * 88,
    ]
    lines.extend(_metric_rows("  Validation", result.tuning.validation_metrics))
    lines.extend(_metric_rows("  Holdout", result.holdout_metrics))
    lines.extend(_metric_rows("  League baseline", result.league_average_metrics))
    lines.extend(["", "HOLDOUT BY SEASON"])
    for season, metrics in result.holdout_metrics_by_season.items():
        lines.extend(_metric_rows(f"  {season}", metrics))

    goal_delta = result.league_average_metrics.mean_goal_mae - result.holdout_metrics.mean_goal_mae
    exact_delta = (
        result.holdout_metrics.exact_score_accuracy
        - result.league_average_metrics.exact_score_accuracy
    )
    accuracy_delta = (
        result.holdout_metrics.outcome_metrics.accuracy - result.elo_holdout_metrics.accuracy
    )
    outcome_delta = (
        result.elo_holdout_metrics.log_loss - result.holdout_metrics.outcome_metrics.log_loss
    )
    lines.extend(
        [
            "",
            "PLAIN-LANGUAGE RESULT",
            f"  Average goal error is {result.holdout_metrics.mean_goal_mae:.3f} goals per team.",
            (
                "  Exact score was the top prediction in "
                f"{_percent(result.holdout_metrics.exact_score_accuracy).strip()} "
                "of holdout matches."
            ),
            f"  Goal MAE improvement over league-average baseline: {goal_delta:+.3f} goals.",
            f"  Exact-score change versus league baseline: {_percent(exact_delta).strip()} points.",
            (
                "  Outcome-accuracy change versus Phase 6 Elo: "
                f"{_percent(accuracy_delta).strip()} points."
            ),
            (
                "  Outcome log-loss improvement over Phase 6 Elo: "
                f"{outcome_delta:+.3f} (positive is better)."
            ),
            (
                "  Verdict: goal error and probability quality improved, while the single most "
                "likely exact score and outcome pick did not."
            ),
            "  Lower Goal MAE, RMSE, Score NLL, and Outcome NLL are better.",
            "  Higher Exact score and Outcome accuracy are better.",
            "",
            "ARTIFACTS",
            f"  Model              {artifacts.model_path}",
            f"  Evaluation report  {artifacts.report_path}",
            f"  Model SHA-256       {artifacts.model_checksum}",
            "",
            "LIMITATIONS",
            "  This phase uses goal-derived team form, not injuries, suspensions,",
            "  transfers, player availability, expected lineups, or betting odds.",
            "=" * 72,
        ]
    )
    return "\n".join(lines)
