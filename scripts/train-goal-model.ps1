param(
    [string]$Dataset = "data/processed/historical_training_matches.csv",
    [string]$ArtifactRoot = "artifacts/models/goals",
    [ValidateSet("human", "json")]
    [string]$OutputFormat = "human"
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python environment not found. Create .venv and install the project with: python -m pip install -e `".[dev]`""
}
& $pythonPath -c "import prem_engine_modeling" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Prem Engine is not installed in .venv. Activate it and run: python -m pip install -e `".[dev]`""
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

& $pythonPath (Join-Path $projectRoot "modeling\scripts\train_goal_model.py") `
    --dataset $datasetPath `
    --artifact-root $artifactPath `
    --output-format $OutputFormat
exit $LASTEXITCODE
