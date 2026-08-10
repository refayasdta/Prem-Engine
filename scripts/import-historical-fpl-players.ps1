param(
    [string]$Manifest = "data/contracts/fpl-historical/coverage-summary.json",
    [string]$ClubAliases = "data/mappings/fpl-clubs.csv"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python environment not found. Create .venv and install the project first."
}

& $pythonPath (Join-Path $projectRoot "backend\scripts\import_historical_fpl_players.py") `
    --manifest (Join-Path $projectRoot $Manifest) `
    --club-aliases (Join-Path $projectRoot $ClubAliases)
exit $LASTEXITCODE
