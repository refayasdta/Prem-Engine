"""Human-readable Phase 12 detailed-statistics report."""

from __future__ import annotations

from prem_engine_modeling.match_statistics_artifacts import WrittenStatisticsArtifacts
from prem_engine_modeling.match_statistics_data import (
    UNSUPPORTED_TARGETS,
    DetailedStatisticsDataset,
)
from prem_engine_modeling.match_statistics_training import DetailedStatisticsTrainingResult


def human_statistics_report(
    result: DetailedStatisticsTrainingResult,
    dataset: DetailedStatisticsDataset,
    artifacts: WrittenStatisticsArtifacts,
) -> str:
    lines = [
        "",
        "PREM ENGINE - PHASE 12 DETAILED MATCH STATISTICS",
        "=" * 104,
        "Status                    TRAINING COMPLETED",
        f"Model version             {artifacts.model_version}",
        f"Fixtures                  {len(dataset.tabular.targets):,}",
        f"Features                  {len(dataset.tabular.feature_columns)}",
        f"Count targets             {len(result.targets)}",
        f"Model targets promoted    {result.promoted_target_count}",
        "",
        "HOLDOUT TARGET DECISIONS (760 fixtures; lower MAE/deviance is better)",
        "  Target                    Alpha  Model MAE  Base MAE  Model Dev  Base Dev  Official",
        "  " + "-" * 92,
    ]
    for item in result.targets:
        source = "MODEL" if item.use_model else "BASELINE"
        lines.append(
            f"  {item.target.name:<25} {item.selected_alpha:>6.2f} "
            f"{item.holdout_metrics.mean_absolute_error:>10.3f} "
            f"{item.baseline_metrics.mean_absolute_error:>9.3f} "
            f"{item.holdout_metrics.mean_poisson_deviance:>10.3f} "
            f"{item.baseline_metrics.mean_poisson_deviance:>9.3f}  {source}"
        )
    lines.extend(
        [
            "",
            f"Aggregate model MAE        {result.aggregate_model_mae:.4f}",
            f"Aggregate baseline MAE     {result.aggregate_baseline_mae:.4f}",
            "",
            "UNSUPPORTED HISTORICAL TARGETS",
        ]
    )
    lines.extend(f"  {name:<28} {reason}" for name, reason in UNSUPPORTED_TARGETS.items())
    lines.extend(
        [
            "",
            "CONSISTENCY CONTRACT",
            "  Shots on target are capped at total shots for the same team.",
            "  Means and 90% plausible interval bounds are non-negative.",
            "  Phase 13 will create the joint event sequence and enforce event-level totals.",
            "",
            "ARTIFACTS",
            f"  Model                   {artifacts.model_path}",
            f"  Evaluation              {artifacts.report_path}",
            f"  Model SHA-256           {artifacts.model_checksum}",
            "=" * 104,
        ]
    )
    return "\n".join(lines)
