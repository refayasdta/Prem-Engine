param(
    [string]$BaseFeatures = "data/processed/prematch_features.csv",
    [string]$Performances = "data/processed/player_context/player_performances.csv",
    [string]$Availability = "data/processed/player_context/availability_observations.csv",
    [string]$Transfers = "data/processed/player_context/transfer_observations.csv",
    [string]$Dataset = "data/processed/player_prematch_features.csv",
    [string]$Report = "data/processed/player_feature_quality.json",
    [ValidateSet("human", "json")]
    [string]$OutputFormat = "human",
    [switch]$Force
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

$arguments = @(
    (Join-Path $projectRoot "modeling\scripts\build_player_features.py"),
    "--base-features", (Resolve-ProjectPath $BaseFeatures),
    "--performances", (Resolve-ProjectPath $Performances),
    "--availability", (Resolve-ProjectPath $Availability),
    "--transfers", (Resolve-ProjectPath $Transfers),
    "--dataset", (Resolve-ProjectPath $Dataset),
    "--report", (Resolve-ProjectPath $Report),
    "--output-format", $OutputFormat
)
if ($Force) {
    $arguments += "--force"
}

& $pythonPath @arguments
exit $LASTEXITCODE
