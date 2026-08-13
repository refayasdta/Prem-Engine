[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{64}$')]
    [string]$ExpectedSha256,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9_-]+$')]
    [string]$ExpectedDatabaseName,

    [Parameter(Mandatory = $true)]
    [switch]$ConfirmRestore
)

$ErrorActionPreference = 'Stop'

function ConvertTo-PostgresUrl {
    param([Parameter(Mandatory = $true)][string]$Url)
    return $Url -replace '^postgresql\+asyncpg://', 'postgresql://'
}

if (-not $ConfirmRestore) {
    throw 'Restore refused: pass -ConfirmRestore after independently verifying the target and backup.'
}
if ([string]::IsNullOrWhiteSpace($env:RESTORE_DATABASE_URL)) {
    throw 'RESTORE_DATABASE_URL must contain the restore-role connection string.'
}
if (-not (Test-Path -LiteralPath $BackupPath -PathType Leaf)) {
    throw "Backup does not exist: $BackupPath"
}
foreach ($command in @('psql', 'pg_restore')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command was not found on PATH."
    }
}

$actualChecksum = (Get-FileHash -LiteralPath $BackupPath -Algorithm SHA256).Hash
if ($actualChecksum -ine $ExpectedSha256) {
    throw "Backup checksum mismatch. Expected $ExpectedSha256, received $actualChecksum."
}

$previousPgDatabase = $env:PGDATABASE
try {
    $env:PGDATABASE = ConvertTo-PostgresUrl $env:RESTORE_DATABASE_URL
    $actualDatabaseName = (& psql --no-psqlrc --tuples-only --no-align --command='SELECT current_database();').Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Could not verify the restore target; psql exited with $LASTEXITCODE."
    }
    if ($actualDatabaseName -cne $ExpectedDatabaseName) {
        throw "Restore target mismatch. Expected '$ExpectedDatabaseName', connected to '$actualDatabaseName'."
    }

    & pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error --dbname=$env:PGDATABASE $BackupPath
    if ($LASTEXITCODE -ne 0) {
        throw "pg_restore failed with exit code $LASTEXITCODE."
    }
}
finally {
    $env:PGDATABASE = $previousPgDatabase
}

Write-Output "Restore completed for verified database '$ExpectedDatabaseName'."
