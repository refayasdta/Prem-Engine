param(
    [string]$Dataset = "data/processed/historical_training_matches.csv",
    [string]$ArtifactRoot = "artifacts/models/elo"
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python environment not found. Create .venv and install the project with: python -m pip install -e `".[dev]`""
}

$datasetPath = if ([System.IO.Path]::IsPathRooted($Dataset)) {
    $Dataset
}
else {
    Join-Path $projectRoot $Dataset
}
if (-not (Test-Path -LiteralPath $datasetPath)) {
    throw "Historical training export not found at $Dataset. Complete the Phase 5 import first."
}

$artifactPath = if ([System.IO.Path]::IsPathRooted($ArtifactRoot)) {
    $ArtifactRoot
}
else {
    Join-Path $projectRoot $ArtifactRoot
}

& $pythonPath (Join-Path $projectRoot "modeling\scripts\train_elo_baseline.py") `
    --dataset $datasetPath `
    --artifact-root $artifactPath
exit $LASTEXITCODE
