$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python environment not found. Create .venv and install the project first."
}

Push-Location $projectRoot
try {
    & $pythonPath -m prem_engine_api.jobs.dispatcher
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
