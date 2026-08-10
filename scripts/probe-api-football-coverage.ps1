param(
    [int[]]$Seasons = @(2020, 2021, 2022, 2023, 2024, 2025),
    [string]$Output = "data/contracts/api-football/coverage-summary.json",
    [switch]$ConfirmLiveAudit
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python environment not found. Create .venv and install the project first."
}
$outputPath = if ([System.IO.Path]::IsPathRooted($Output)) {
    $Output
}
else {
    Join-Path $projectRoot $Output
}
$arguments = @(
    (Join-Path $projectRoot "backend\scripts\probe_api_football_coverage.py"),
    "--output",
    $outputPath,
    "--seasons"
) + $Seasons
if ($ConfirmLiveAudit) {
    $arguments += "--confirm-live-audit"
}

& $pythonPath @arguments
exit $LASTEXITCODE
