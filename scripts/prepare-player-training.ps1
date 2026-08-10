param(
    [string]$PythonPath = ".venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$resolvedPython = if ([System.IO.Path]::IsPathRooted($PythonPath)) {
    $PythonPath
}
else {
    Join-Path $projectRoot $PythonPath
}

if (-not (Test-Path -LiteralPath $resolvedPython)) {
    throw "Python environment not found at $resolvedPython. Recreate .venv before preparing training."
}
& $resolvedPython --version
if ($LASTEXITCODE -ne 0) {
    throw "The .venv Python launcher is broken. Recreate .venv with Python 3.12 before continuing."
}

$env:PYTHONPATH = @(
    (Join-Path $projectRoot "backend"),
    (Join-Path $projectRoot "modeling"),
    $env:PYTHONPATH
) -join [System.IO.Path]::PathSeparator
$processed = Join-Path $projectRoot "data\processed"
$playerContext = Join-Path $processed "player_context"

Write-Host "`nSTEP 1/4 - Export canonical match data" -ForegroundColor Cyan
& $resolvedPython (Join-Path $projectRoot "backend\scripts\export_historical_modeling_data.py") `
    --output-root $processed
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`nSTEP 2/4 - Rebuild 24-hour pre-match features" -ForegroundColor Cyan
& $resolvedPython (Join-Path $projectRoot "modeling\scripts\build_prematch_features.py") `
    --dataset (Join-Path $processed "historical_training_matches.csv") `
    --output (Join-Path $processed "prematch_features.csv") `
    --report (Join-Path $processed "prematch_features.report.json") `
    --output-format human `
    --force
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`nSTEP 3/4 - Export normalized player context" -ForegroundColor Cyan
& $resolvedPython (Join-Path $projectRoot "backend\scripts\export_player_context.py") `
    --output-root $playerContext
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`nSTEP 4/4 - Build and audit player-enhanced features" -ForegroundColor Cyan
& $resolvedPython (Join-Path $projectRoot "modeling\scripts\build_player_features.py") `
    --base-features (Join-Path $processed "prematch_features.csv") `
    --performances (Join-Path $playerContext "player_performances.csv") `
    --availability (Join-Path $playerContext "availability_observations.csv") `
    --transfers (Join-Path $playerContext "transfer_observations.csv") `
    --dataset (Join-Path $processed "player_prematch_features.csv") `
    --report (Join-Path $processed "player_feature_quality.json") `
    --output-format human `
    --force
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "`nPreparation complete. No model was trained." -ForegroundColor Green
