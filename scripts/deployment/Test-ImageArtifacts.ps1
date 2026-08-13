[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('@sha256:[0-9a-f]{64}$')]
    [string]$JobImage,

    [string]$ExpectedGoalSha256 = 'fe8a19c262b6a0d8aa02e01564f6c109eec2d16e237fa276e6a414967ecf0adc',
    [string]$ExpectedStatisticsSha256 = '6859e2b0a6cd23382b795e68034b29548a6ac0a26fa9f08623cda5306cac4e12'
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'docker was not found on PATH.'
}

$goalPath = '/app/artifacts/models/goals/goals-v1-156511483a94/model.joblib'
$statisticsPath = '/app/artifacts/models/match-statistics/detailed-statistics-v1-42e73adec486/model.joblib'
$output = & docker run --rm --entrypoint sha256sum $JobImage $goalPath $statisticsPath
if ($LASTEXITCODE -ne 0) {
    throw "Artifact verification container failed with exit code $LASTEXITCODE."
}

$actual = @{}
foreach ($line in $output) {
    if ($line -match '^([0-9a-f]{64})\s+(.+)$') {
        $actual[$Matches[2]] = $Matches[1]
    }
}
if ($actual[$goalPath] -cne $ExpectedGoalSha256) {
    throw 'Goal model checksum does not match the approved release artifact.'
}
if ($actual[$statisticsPath] -cne $ExpectedStatisticsSha256) {
    throw 'Statistics model checksum does not match the approved release artifact.'
}

Write-Output 'Both production model artifacts match their approved SHA256 checksums.'
