param(
    [string]$OutputRoot = "data/processed/player_context"
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python environment not found. Create .venv and install the project first."
}
$outputPath = if ([System.IO.Path]::IsPathRooted($OutputRoot)) {
    $OutputRoot
}
else {
    Join-Path $projectRoot $OutputRoot
}

& $pythonPath (Join-Path $projectRoot "backend\scripts\export_player_context.py") `
    --output-root $outputPath
exit $LASTEXITCODE
