param(
    [string]$PlayerFeatures = "data/processed/player_prematch_features.csv",
    [string]$HistoricalMatches = "data/processed/historical_training_matches.csv",
    [string]$Dataset = "data/processed/tactical_prematch_features.csv",
    [string]$Report = "data/processed/tactical_feature_quality.json",
    [switch]$Force,
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

$arguments = @(
    (Join-Path $projectRoot "modeling\scripts\build_tactical_features.py"),
    "--player-features", (Resolve-ProjectPath $PlayerFeatures),
    "--historical-matches", (Resolve-ProjectPath $HistoricalMatches),
    "--dataset", (Resolve-ProjectPath $Dataset),
    "--report", (Resolve-ProjectPath $Report),
    "--output-format", $OutputFormat
)
if ($Force) { $arguments += "--force" }
& $pythonPath @arguments
exit $LASTEXITCODE
