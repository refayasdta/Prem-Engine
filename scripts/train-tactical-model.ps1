param(
    [string]$Dataset = "data/processed/tactical_prematch_features.csv",
    [string]$QualityReport = "data/processed/tactical_feature_quality.json",
    [string]$ArtifactRoot = "artifacts/models/tactical",
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
    if ([System.IO.Path]::IsPathRooted($Value)) { return $Value }
    return Join-Path $projectRoot $Value
}

& $pythonPath (Join-Path $projectRoot "modeling\scripts\train_tactical_model.py") `
    --dataset (Resolve-ProjectPath $Dataset) `
    --quality-report (Resolve-ProjectPath $QualityReport) `
    --artifact-root (Resolve-ProjectPath $ArtifactRoot) `
    --output-format $OutputFormat
exit $LASTEXITCODE
