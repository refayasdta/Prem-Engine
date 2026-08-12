param(
    [Parameter(Mandatory = $true)]
    [int]$Season,
    [string]$League = "en.1",
    [ValidateRange(1, 85)]
    [int]$MaxRequests = 16,
    [ValidateRange(0, 20)]
    [int]$MaxSquads = 10,
    [ValidateRange(0, 10)]
    [int]$MaxMatches = 2
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python environment not found. Create .venv and install the project first."
}

Push-Location $projectRoot
try {
    & $pythonPath backend/scripts/sync_player_context.py `
        --league $League `
        --season $Season `
        --max-requests $MaxRequests `
        --max-squads $MaxSquads `
        --max-matches $MaxMatches
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
