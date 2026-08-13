[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')]
    [string]$ReleaseLabel
)

$ErrorActionPreference = 'Stop'

function ConvertTo-PostgresUrl {
    param([Parameter(Mandatory = $true)][string]$Url)
    return $Url -replace '^postgresql\+asyncpg://', 'postgresql://'
}

if ([string]::IsNullOrWhiteSpace($env:DATABASE_URL)) {
    throw 'DATABASE_URL must contain the backup-role connection string.'
}
if (-not (Get-Command pg_dump -ErrorAction SilentlyContinue)) {
    throw 'pg_dump was not found on PATH.'
}

$resolvedOutput = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $resolvedOutput -Force | Out-Null
$timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$backupPath = Join-Path $resolvedOutput "prem-engine-$ReleaseLabel-$timestamp.dump"
$checksumPath = "$backupPath.sha256"
$metadataPath = "$backupPath.metadata.json"

$previousPgDatabase = $env:PGDATABASE
try {
    $env:PGDATABASE = ConvertTo-PostgresUrl $env:DATABASE_URL
    & pg_dump --format=custom --no-owner --no-acl --file=$backupPath
    if ($LASTEXITCODE -ne 0) {
        throw "pg_dump failed with exit code $LASTEXITCODE."
    }
}
finally {
    $env:PGDATABASE = $previousPgDatabase
}

$checksum = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath $checksumPath -Value "$checksum  $([System.IO.Path]::GetFileName($backupPath))"
[ordered]@{
    schemaVersion = 1
    releaseLabel = $ReleaseLabel
    createdAtUtc = (Get-Date).ToUniversalTime().ToString('o')
    backupFile = [System.IO.Path]::GetFileName($backupPath)
    sha256 = $checksum
    format = 'postgres-custom'
} | ConvertTo-Json | Set-Content -LiteralPath $metadataPath

Write-Output "Backup: $backupPath"
Write-Output "SHA256: $checksum"
Write-Output "Metadata: $metadataPath"
