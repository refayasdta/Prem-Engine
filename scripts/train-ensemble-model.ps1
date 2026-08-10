param(
    [string]$Dataset = "data/processed/player_prematch_features.csv",
    [string]$QualityReport = "data/processed/player_feature_quality.json",
    [string]$ArtifactRoot = "artifacts/models/ensemble",
    [double]$WeightStep = 0.1,
    [ValidateSet("human", "json")]
    [string]$OutputFormat = "human"
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python environment not found. Create .venv and install the project first."
}

function Resolve-ProjectPath([string]$Value) {
    if ([System.IO.Path]::IsPathRooted($Value)) {
        return $Value
    }
    return Join-Path $projectRoot $Value
}

& $pythonPath (Join-Path $projectRoot "modeling\scripts\train_ensemble_model.py") `
    --dataset (Resolve-ProjectPath $Dataset) `
    --quality-report (Resolve-ProjectPath $QualityReport) `
    --artifact-root (Resolve-ProjectPath $ArtifactRoot) `
    --weight-step $WeightStep `
    --output-format $OutputFormat
exit $LASTEXITCODE
