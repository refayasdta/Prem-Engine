param(
    [string[]]$Seasons = @("2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"),
    [switch]$ConfirmPublicDownload
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python environment not found. Create .venv and install the project first."
}
$arguments = @(
    (Join-Path $projectRoot "backend\scripts\audit_historical_fpl.py"),
    "--seasons"
) + $Seasons
if ($ConfirmPublicDownload) {
    $arguments += "--confirm-public-download"
}

& $pythonPath @arguments
exit $LASTEXITCODE
