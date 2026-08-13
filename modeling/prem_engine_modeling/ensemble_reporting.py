"""Human-readable Phase 11 ensemble report."""

from __future__ import annotations

from prem_engine_modeling.ensemble_artifacts import WrittenEnsembleArtifacts
from prem_engine_modeling.ensemble_training import COMPONENT_ORDER, EnsembleTrainingResult
from prem_engine_modeling.evaluation import EvaluationMetrics
from prem_engine_modeling.tabular_data import TabularDataset


def _metrics_row(label: str, metrics: EvaluationMetrics) -> str:
    return (
        f"{label:<25} {metrics.accuracy:>8.2%} {metrics.log_loss:>9.4f} "
        f"{metrics.brier_score:>9.4f} {metrics.ranked_probability_score:>9.4f} "
        f"{metrics.expected_calibration_error:>9.4f}"
    )


def human_ensemble_report(
    result: EnsembleTrainingResult,
    dataset: TabularDataset,
    artifacts: WrittenEnsembleArtifacts,
) -> str:
    weights = dict(zip(COMPONENT_ORDER, result.selected.weights, strict=True))
    lines = [
        "",
        "PREM ENGINE - PHASE 11 ENSEMBLE MODEL",
        "=" * 86,
        "Status                    TRAINING COMPLETED",
        f"Model version             {artifacts.model_version}",
        f"Weight candidates         {len(result.leaderboard)}",
        f"Fixtures                  {len(dataset.targets):,}",
        "",
        "SELECTED WEIGHTS (development folds only)",
    ]
    lines.extend(f"  {name:<10} {weights[name]:>7.1%}" for name in COMPONENT_ORDER)
    lines.append("")
    lines.append("COMPONENT CALIBRATION TEMPERATURES")
    lines.extend(
        f"  {name:<10} {result.component_temperatures[name]:>7.4f}" for name in COMPONENT_ORDER
    )
    lines.extend(
        [
            f"  Mean development log loss   {result.selected.mean_log_loss:.4f}",
            f"  Calibration temperature     {result.calibration_temperature:.4f}",
            "",
            "HOLDOUT COMPARISON",
            "  Model                      Accuracy  Log loss     Brier       RPS       ECE",
            "  " + "-" * 78,
            _metrics_row("  Ensemble", result.holdout_metrics),
        ]
    )
    labels = {
        "elo": "Phase 6 Elo",
        "goals": "Phase 7 goals",
        "tabular": "Phase 9 tabular",
        "player": "Phase 10 player",
    }
    lines.extend(
        _metrics_row(f"  {labels[name]}", result.component_holdout_metrics[name])
        for name in COMPONENT_ORDER
    )
    lines.extend(
        [
            "",
            "PROMOTION VERDICT",
            f"  Status                  {result.promotion.status.upper()}",
            f"  Best benchmark          {result.promotion.best_benchmark}",
            f"  Holdout log-loss gain   {result.promotion.log_loss_improvement:+.4f}",
            f"  Reason                  {result.promotion.reason}",
            "",
            "EVALUATION DISCLOSURE",
            "  Holdout targets were not used to fit weights or calibration. Earlier Phase 9",
            "  and Phase 10 benchmark results for these seasons had already been inspected,",
            "  so 2026/27 remains the next genuinely unseen live validation season.",
            "",
            "ARTIFACTS",
            f"  Model                   {artifacts.model_path}",
            f"  Evaluation              {artifacts.report_path}",
            f"  Model SHA-256           {artifacts.model_checksum}",
            "=" * 86,
        ]
    )
    return "\n".join(lines)
