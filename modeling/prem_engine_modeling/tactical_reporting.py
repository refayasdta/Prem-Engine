"""Human-readable Phase 15 tactical training reports."""

from __future__ import annotations

from prem_engine_modeling.evaluation import EvaluationMetrics
from prem_engine_modeling.tabular_training import TabularTrainingResult
from prem_engine_modeling.tactical_artifacts import WrittenTacticalArtifacts
from prem_engine_modeling.tactical_features import TACTICAL_FEATURE_COLUMNS
from prem_engine_modeling.tactical_training import TacticalTrainingDataset


def _metrics(label: str, metrics: EvaluationMetrics) -> str:
    return (
        f"{label:<25} {metrics.accuracy * 100:>8.2f}% {metrics.log_loss:>9.4f} "
        f"{metrics.brier_score:>9.4f} {metrics.ranked_probability_score:>9.4f} "
        f"{metrics.expected_calibration_error:>9.4f}"
    )


def human_tactical_blocked_report(dataset: TacticalTrainingDataset) -> str:
    coverage = dataset.coverage
    return "\n".join(
        [
            "",
            "PREM ENGINE - PHASE 15 TACTICAL MODEL",
            "=" * 86,
            "Status                    TRAINING SAFELY BLOCKED",
            f"Style coverage            {coverage.style_covered_fixture_rate:.1%}",
            f"Shape coverage            {coverage.shape_covered_fixture_rate:.1%}",
            f"Observed starting XIs     {coverage.shape_observation_count:,}",
            "",
            "WHY NO MODEL WAS FIT",
            f"  {coverage.reason}",
            "  Sparse formations would make the apparent tactical influence misleading.",
            "=" * 86,
        ]
    )


def human_tactical_training_report(
    result: TabularTrainingResult,
    dataset: TacticalTrainingDataset,
    artifacts: WrittenTacticalArtifacts,
) -> str:
    lines = [
        "",
        "PREM ENGINE - PHASE 15 TACTICAL MODEL",
        "=" * 86,
        "Status                    TRAINING COMPLETED",
        f"Model version             {artifacts.model_version}",
        f"Features                  {len(dataset.tabular.feature_columns)}",
        f"Style coverage            {dataset.coverage.style_covered_fixture_rate:.1%}",
        f"Shape coverage            {dataset.coverage.shape_covered_fixture_rate:.1%}",
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
            _metrics("  Tactical model", result.holdout_calibrated_metrics),
            _metrics("  Phase 6 Elo", result.elo_holdout_metrics),
            _metrics("  Phase 7 goals", result.goal_holdout_metrics),
            "",
            "TACTICAL FEATURE INFLUENCES (association, not causation)",
        ]
    )
    influences = [
        item for item in result.feature_influences if item.feature in TACTICAL_FEATURE_COLUMNS
    ]
    if not influences:
        lines.append("  No tactical feature entered the leading influence set.")
    for index, influence in enumerate(influences, 1):
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
            "HOW TO READ THIS",
            "  PROMOTED means the candidate beat the established benchmark on the",
            "  untouched holdout under the configured margin. REJECTED means Phase 7",
            "  remains the official outcome and scoreline model.",
            "",
            "ARTIFACTS",
            f"  Model                   {artifacts.model_path}",
            f"  Evaluation              {artifacts.report_path}",
            f"  Model SHA-256           {artifacts.model_checksum}",
            "=" * 86,
        ]
    )
    return "\n".join(lines)
