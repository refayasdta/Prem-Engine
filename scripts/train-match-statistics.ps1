param(
    [string]$Features = "data/processed/prematch_features.csv",
    [string]$Historical = "data/processed/historical_training_matches.csv",
    [string]$ArtifactRoot = "artifacts/models/match-statistics",
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

& $pythonPath (Join-Path $projectRoot "modeling\scripts\train_match_statistics.py") `
    --features (Resolve-ProjectPath $Features) `
    --historical (Resolve-ProjectPath $Historical) `
    --artifact-root (Resolve-ProjectPath $ArtifactRoot) `
    --output-format $OutputFormat
exit $LASTEXITCODE
