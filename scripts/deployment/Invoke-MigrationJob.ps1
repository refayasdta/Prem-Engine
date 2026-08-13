[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [Parameter(Mandatory = $true)]
    [string]$Region,

    [Parameter(Mandatory = $true)]
    [string]$JobName,

    [Parameter(Mandatory = $true)]
    [string]$BackupMetadataPath,

    [Parameter(Mandatory = $true)]
    [switch]$ConfirmMigration
)

$ErrorActionPreference = 'Stop'

if (-not $ConfirmMigration) {
    throw 'Migration refused: pass -ConfirmMigration after backup and restore rehearsal approval.'
}
if (-not (Test-Path -LiteralPath $BackupMetadataPath -PathType Leaf)) {
    throw "Backup metadata does not exist: $BackupMetadataPath"
}
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    throw 'gcloud was not found on PATH.'
}

$metadata = Get-Content -LiteralPath $BackupMetadataPath -Raw | ConvertFrom-Json
if ($metadata.schemaVersion -ne 1 -or $metadata.format -ne 'postgres-custom') {
    throw 'Backup metadata is not a supported Prem Engine PostgreSQL backup record.'
}
if ($metadata.sha256 -notmatch '^[0-9a-f]{64}$') {
    throw 'Backup metadata does not contain a valid SHA256 digest.'
}
$backupPath = Join-Path (Split-Path -Parent ([System.IO.Path]::GetFullPath($BackupMetadataPath))) $metadata.backupFile
if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
    throw "The backup referenced by metadata does not exist: $backupPath"
}
$actualChecksum = (Get-FileHash -LiteralPath $backupPath -Algorithm SHA256).Hash
if ($actualChecksum -ine $metadata.sha256) {
    throw 'The pre-migration backup checksum no longer matches its metadata.'
}

& gcloud run jobs execute $JobName --project=$ProjectId --region=$Region --wait
if ($LASTEXITCODE -ne 0) {
    throw "Migration job failed with exit code $LASTEXITCODE."
}

Write-Output "Migration job '$JobName' completed. Verify alembic current before changing traffic."
