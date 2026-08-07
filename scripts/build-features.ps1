param(
    [string]$Dataset = "data/processed/historical_training_matches.csv",
    [string]$Output = "data/processed/prematch_features.csv",
    [string]$Report = "data/processed/prematch_features.report.json",
    [ValidateSet("human", "json")]
    [string]$OutputFormat = "human",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python environment not found. Create .venv and install the project with: python -m pip install -e `".[dev]`""
}
& $pythonPath -c "import prem_engine_modeling" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Prem Engine is not installed in .venv. Activate it and run: python -m pip install -e `".[dev]`""
}

function Resolve-ProjectPath([string]$PathValue) {
    if ([System.IO.Path]::IsPathRooted($PathValue)) { return $PathValue }
    return Join-Path $projectRoot $PathValue
}

$datasetPath = Resolve-ProjectPath $Dataset
if (-not (Test-Path -LiteralPath $datasetPath)) {
    throw "Historical training export not found at $Dataset. Complete the Phase 5 import first."
}
$arguments = @(
    (Join-Path $projectRoot "modeling\scripts\build_prematch_features.py"),
    "--dataset", $datasetPath,
    "--output", (Resolve-ProjectPath $Output),
    "--report", (Resolve-ProjectPath $Report),
    "--output-format", $OutputFormat
)
if ($Force) { $arguments += "--force" }

& $pythonPath @arguments
exit $LASTEXITCODE
