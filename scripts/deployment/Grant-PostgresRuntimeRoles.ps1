[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z][a-z0-9_]{0,62}$')]
    [string]$ApiRole,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z][a-z0-9_]{0,62}$')]
    [string]$WorkerRole,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z][a-z0-9_]{0,62}$')]
    [string]$BackupRole,

    [Parameter(Mandatory = $true)]
    [switch]$ConfirmRoleGrants
)

$ErrorActionPreference = 'Stop'

function ConvertTo-PostgresUrl {
    param([Parameter(Mandatory = $true)][string]$Url)
    return $Url -replace '^postgresql\+asyncpg://', 'postgresql://'
}

if (-not $ConfirmRoleGrants) {
    throw 'Role grants refused: pass -ConfirmRoleGrants after verifying the target database and role names.'
}
if ([string]::IsNullOrWhiteSpace($env:MIGRATION_DATABASE_URL)) {
    throw 'MIGRATION_DATABASE_URL must contain the migration-owner direct connection string.'
}
if (-not (Get-Command psql -ErrorAction SilentlyContinue)) {
    throw 'psql was not found on PATH.'
}
if ((@($ApiRole, $WorkerRole, $BackupRole) | Sort-Object -Unique).Count -ne 3) {
    throw 'API, worker, and backup role names must be distinct.'
}

$sqlPath = Join-Path $PSScriptRoot 'Grant-PostgresRuntimeRoles.sql'
if (-not (Test-Path -LiteralPath $sqlPath -PathType Leaf)) {
    throw "Role grant SQL does not exist: $sqlPath"
}

$previousPgDatabase = $env:PGDATABASE
try {
    $env:PGDATABASE = ConvertTo-PostgresUrl $env:MIGRATION_DATABASE_URL
    & psql `
        --no-psqlrc `
        --set=ON_ERROR_STOP=1 `
        "--set=api_role=$ApiRole" `
        "--set=worker_role=$WorkerRole" `
        "--set=backup_role=$BackupRole" `
        --file=$sqlPath
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL role grants failed with exit code $LASTEXITCODE."
    }
}
finally {
    $env:PGDATABASE = $previousPgDatabase
}

Write-Output "Verified and granted least-privilege runtime access in the target database."
