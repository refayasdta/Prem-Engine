"""Human-readable Phase 9 training results."""

from __future__ import annotations

from prem_engine_modeling.evaluation import EvaluationMetrics
from prem_engine_modeling.tabular_artifacts import WrittenTabularArtifacts
from prem_engine_modeling.tabular_data import TabularDataset
from prem_engine_modeling.tabular_training import TabularTrainingResult


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _metrics_row(label: str, metrics: EvaluationMetrics) -> str:
    return (
        f"{label:<23} {_percent(metrics.accuracy):>9} {metrics.log_loss:>9.4f} "
        f"{metrics.brier_score:>9.4f} {metrics.ranked_probability_score:>9.4f} "
        f"{metrics.expected_calibration_error:>9.4f}"
    )


def human_tabular_report(
    result: TabularTrainingResult,
    dataset: TabularDataset,
    artifacts: WrittenTabularArtifacts,
) -> str:
    lines = [
        "",
        "PREM ENGINE - PHASE 9 CALIBRATED TABULAR MODEL",
        "=" * 84,
        "Status                    TRAINING COMPLETED SUCCESSFULLY",
        f"Model version             {artifacts.model_version}",
        f"Features                  {len(dataset.feature_columns)} approved columns",
        f"Feature checksum          {dataset.checksum}",
        "",
        "CHRONOLOGICAL DESIGN",
        "  Development fold 1      2020/21 -> 2021/22",
        "  Development fold 2      2020/21-2021/22 -> 2022/23",
        f"  Calibration             {dataset.split.calibration_season}",
        f"  Untouched holdout       {', '.join(dataset.split.holdout_seasons)}",
        "",
        "CANDIDATE LEADERBOARD (development folds only; lower is better)",
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
            "SELECTED MODEL",
            f"  Candidate               {result.selected_candidate.candidate_id}",
            f"  Family                  {result.selected_candidate.family}",
            f"  Calibration temperature {result.calibration_temperature:.4f}",
            "",
            "CALIBRATION SEASON",
            "  Model                    Accuracy  Log loss     Brier       RPS       ECE",
            "  " + "-" * 76,
            _metrics_row("  Before calibration", result.calibration_uncalibrated_metrics),
            _metrics_row("  After calibration", result.calibration_calibrated_metrics),
            "",
            "UNTOUCHED HOLDOUT",
            "  Model                    Accuracy  Log loss     Brier       RPS       ECE",
            "  " + "-" * 76,
            _metrics_row("  Tabular calibrated", result.holdout_calibrated_metrics),
            _metrics_row("  Tabular uncalibrated", result.holdout_uncalibrated_metrics),
            _metrics_row("  Phase 6 Elo", result.elo_holdout_metrics),
            _metrics_row("  Phase 7 goals", result.goal_holdout_metrics),
            _metrics_row("  Historical prior", result.historical_prior_holdout_metrics),
            "",
            "HOLDOUT BY SEASON",
        ]
    )
    for season, metrics in result.holdout_metrics_by_season.items():
        lines.append(_metrics_row(f"  {season}", metrics))
    lines.extend(["", "MOST INFLUENTIAL FEATURES (reporting only)"])
    for index, influence in enumerate(result.feature_influences, 1):
        if influence.home_effect is None:
            effect = "nonlinear importance"
        else:
            effect = (
                f"H {influence.home_effect:+.3f} / D {influence.draw_effect:+.3f} / "
                f"A {influence.away_effect:+.3f}"
            )
        lines.append(
            f"  {index:>2}. {influence.feature:<42} {influence.importance:>7.4f}  {effect}"
        )
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
            f"  Evaluation report       {artifacts.report_path}",
            f"  Model SHA-256            {artifacts.model_checksum}",
            "",
            "LIMITATIONS",
            "  This phase excludes players, injuries, suspensions, transfers,",
            "  expected lineups, and tactical features. Influence is not causation.",
            "=" * 84,
        ]
    )
    return "\n".join(lines)
