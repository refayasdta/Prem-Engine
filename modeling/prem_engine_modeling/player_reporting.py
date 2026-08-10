"""Human-readable Phase 10 readiness and training reports."""

from __future__ import annotations

from prem_engine_modeling.evaluation import EvaluationMetrics
from prem_engine_modeling.player_artifacts import WrittenPlayerArtifacts
from prem_engine_modeling.player_features import PLAYER_FEATURE_COLUMNS
from prem_engine_modeling.player_training import PlayerImpactDataset
from prem_engine_modeling.tabular_training import TabularTrainingResult


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _metrics_row(label: str, metrics: EvaluationMetrics) -> str:
    return (
        f"{label:<25} {_percent(metrics.accuracy):>9} {metrics.log_loss:>9.4f} "
        f"{metrics.brier_score:>9.4f} {metrics.ranked_probability_score:>9.4f} "
        f"{metrics.expected_calibration_error:>9.4f}"
    )


def human_player_blocked_report(dataset: PlayerImpactDataset) -> str:
    coverage = dataset.coverage
    return "\n".join(
        [
            "",
            "PREM ENGINE - PHASE 10 PLAYER-IMPACT TRAINING",
            "=" * 86,
            "Status                    TRAINING SAFELY BLOCKED",
            f"Player performances       {coverage.performance_record_count:,}",
            (
                "Covered fixtures          "
                f"{coverage.covered_fixture_count:,} ({coverage.covered_fixture_rate:.1%})"
            ),
            "",
            "WHY NO MODEL WAS FIT",
            f"  {coverage.reason}",
            "  Training on sparse player history would produce misleading importance values",
            "  and an unreliable expected-lineup adjustment.",
            "",
            "WHAT IS READY",
            "  Internal player identities and append-only source provenance",
            "  Lineup, performance, availability, suspension, and transfer contracts",
            "  Prior-only player strength and starting-probability calculations",
            "  Expected XI, replacement quality, bench depth, and uncertainty features",
            "  Chronological training, calibration, benchmark, and promotion pipeline",
            "",
            "NEXT DATA ACTION",
            "  Continue quota-aware historical lineup and player-stat ingestion, rebuild",
            "  the player features, then rerun this command. The gate opens automatically",
            "  only when historical coverage becomes adequate.",
            "=" * 86,
        ]
    )


def human_player_training_report(
    result: TabularTrainingResult,
    dataset: PlayerImpactDataset,
    artifacts: WrittenPlayerArtifacts,
) -> str:
    lines = [
        "",
        "PREM ENGINE - PHASE 10 PLAYER-IMPACT MODEL",
        "=" * 86,
        "Status                    TRAINING COMPLETED",
        f"Model version             {artifacts.model_version}",
        f"Features                  {len(dataset.tabular.feature_columns)}",
        f"Covered fixtures          {dataset.coverage.covered_fixture_rate:.1%}",
        "",
        "CANDIDATE LEADERBOARD (development folds; lower is better)",
        "  Rank Candidate                                      Log loss    Brier",
        "  " + "-" * 72,
    ]
    for rank, score in enumerate(result.leaderboard, 1):
        lines.append(
            f"  {rank:>4} {score.spec.candidate_id:<42} "
            f"{score.mean_log_loss:>9.4f} {score.mean_brier_score:>9.4f}"
        )
    lines.extend(
        [
            "",
            "UNTOUCHED HOLDOUT",
            "  Model                      Accuracy  Log loss     Brier       RPS       ECE",
            "  " + "-" * 78,
            _metrics_row("  Player model", result.holdout_calibrated_metrics),
            _metrics_row("  Phase 6 Elo", result.elo_holdout_metrics),
            _metrics_row("  Phase 7 goals", result.goal_holdout_metrics),
            "",
            "PLAYER FEATURE INFLUENCES (association, not causation)",
        ]
    )
    player_influences = [
        item for item in result.feature_influences if item.feature in PLAYER_FEATURE_COLUMNS
    ]
    for index, influence in enumerate(player_influences, 1):
        lines.append(f"  {index:>2}. {influence.feature:<46} {influence.importance:>7.4f}")
    lines.extend(
        [
            "",
            "PROMOTION VERDICT",
            f"  Status                  {result.promotion.status.upper()}",
            f"  Best benchmark          {result.promotion.best_benchmark}",
            (
                "  Holdout log-loss gain   "
                f"{result.promotion.log_loss_improvement:+.4f} (positive is better)"
            ),
            f"  Reason                  {result.promotion.reason}",
            "",
            "ARTIFACTS",
            f"  Model                   {artifacts.model_path}",
            f"  Evaluation              {artifacts.report_path}",
            f"  Model SHA-256           {artifacts.model_checksum}",
            "=" * 86,
        ]
    )
    return "\n".join(lines)
