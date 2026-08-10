"""Time-safe football forecasting and simulation package."""

from prem_engine_modeling.data import load_historical_dataset, standard_six_season_split
from prem_engine_modeling.elo import EloConfig, EloModel, ResultProbabilities
from prem_engine_modeling.feature_export import validate_feature_export
from prem_engine_modeling.features import FeaturePipelineConfig, build_prematch_features
from prem_engine_modeling.goal_training import GoalParameterGrid, train_goal_model
from prem_engine_modeling.goals import DynamicGoalModel, GoalForecast, GoalModelConfig
from prem_engine_modeling.tabular_data import load_tabular_dataset
from prem_engine_modeling.tabular_training import train_tabular_model
from prem_engine_modeling.training import ParameterGrid, train_baseline, walk_forward
from prem_engine_modeling.validation import validate_result_probabilities

__all__ = [
    "DynamicGoalModel",
    "EloConfig",
    "EloModel",
    "FeaturePipelineConfig",
    "GoalForecast",
    "GoalModelConfig",
    "GoalParameterGrid",
    "ParameterGrid",
    "ResultProbabilities",
    "load_historical_dataset",
    "load_tabular_dataset",
    "standard_six_season_split",
    "build_prematch_features",
    "train_baseline",
    "train_goal_model",
    "train_tabular_model",
    "validate_feature_export",
    "validate_result_probabilities",
    "walk_forward",
]
