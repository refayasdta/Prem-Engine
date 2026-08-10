param(
    [string]$Output = "frontend/src/data/simulation-preview.json"
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

& $pythonPath (Join-Path $projectRoot "modeling\scripts\generate_simulation_preview.py") `
    --output $outputPath
exit $LASTEXITCODE
