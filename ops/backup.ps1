param(
    [string]$OutputDir = "",
    [string]$EnvFile = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $repoRoot "backups"
}
if ([string]::IsNullOrWhiteSpace($EnvFile)) {
    $EnvFile = Join-Path $repoRoot "aiknowledge\.env"
}

function Read-EnvValue([string]$Name, [string]$Fallback) {
    if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) { return $Fallback }
    $line = Get-Content -LiteralPath $EnvFile | Where-Object { $_ -match "^\s*$Name\s*=" } | Select-Object -First 1
    if ($null -eq $line) { return $Fallback }
    $value = ($line -split "=", 2)[1].Trim()
    return $value.Trim('"', "'")
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$pgBackup = Join-Path $OutputDir "postgres-$stamp.dump"
$objectBackup = Join-Path $OutputDir "minio-$stamp"

$composeBaseArgs = @("compose", "--project-directory", $repoRoot)
if (Test-Path -LiteralPath $EnvFile -PathType Leaf) {
    $composeBaseArgs += @("--env-file", $EnvFile)
}
$pgArgs = $composeBaseArgs + @("exec", "-T", "postgres", "pg_dump", "--format=custom", "--no-owner", "--username=$(Read-EnvValue 'POSTGRES_USER' 'aiknowledge')", "--dbname=$(Read-EnvValue 'POSTGRES_DB' 'aiknowledge')")
& docker @pgArgs > $pgBackup
if ($LASTEXITCODE -ne 0 -or (Get-Item -LiteralPath $pgBackup).Length -eq 0) {
    Remove-Item -LiteralPath $pgBackup -Force -ErrorAction SilentlyContinue
    throw "PostgreSQL backup failed."
}

$minioEndpoint = Read-EnvValue 'AIKNOWLEDGE_MINIO_ENDPOINT' 'http://127.0.0.1:9000'
if ($minioEndpoint -notmatch '^https?://') { $minioEndpoint = "http://$minioEndpoint" }
$minioUser = Read-EnvValue 'MINIO_ROOT_USER' 'aiknowledge'
$minioPassword = Read-EnvValue 'MINIO_ROOT_PASSWORD' 'aiknowledge-local-dev-secret'
$minioBucket = Read-EnvValue 'AIKNOWLEDGE_MINIO_BUCKET' 'aiknowledge-private'
if (Get-Command mc -ErrorAction SilentlyContinue) {
    New-Item -ItemType Directory -Force -Path $objectBackup | Out-Null
    & mc alias set aiknowledge-backup $minioEndpoint $minioUser $minioPassword --api S3v4 | Out-Null
    & mc mirror --overwrite "aiknowledge-backup/$minioBucket" $objectBackup
    if ($LASTEXITCODE -ne 0) { throw "MinIO backup failed." }
} else {
    # The API image already contains the MinIO SDK, so a local mc binary is
    # optional. The tar stream keeps object names and bytes in one artifact.
    $objectBackup = Join-Path $OutputDir "minio-$stamp.tar"
    $code = 'import io,os,sys,tarfile; from minio import Minio; c=Minio(os.environ["AIKNOWLEDGE_MINIO_ENDPOINT"],access_key=os.environ["AIKNOWLEDGE_MINIO_ACCESS_KEY"],secret_key=os.environ["AIKNOWLEDGE_MINIO_SECRET_KEY"],secure=os.environ.get("AIKNOWLEDGE_MINIO_SECURE","false").lower()=="true"); b=os.environ["AIKNOWLEDGE_MINIO_BUCKET"]; a=tarfile.open(fileobj=sys.stdout.buffer,mode="w|"); [((lambda d,n:(lambda h:(setattr(h,"size",len(d)),a.addfile(h,io.BytesIO(d))))(tarfile.TarInfo(n)))(c.get_object(b,o.object_name).read(),o.object_name)) for o in c.list_objects(b,recursive=True)]; a.close()'
    $apiArgs = $composeBaseArgs + @("exec", "-T", "api", "python", "-c", $code)
    & docker @apiArgs > $objectBackup
    if ($LASTEXITCODE -ne 0 -or (Get-Item -LiteralPath $objectBackup).Length -eq 0) {
        Remove-Item -LiteralPath $objectBackup -Force -ErrorAction SilentlyContinue
        throw "MinIO backup failed."
    }
}

Write-Output "backup_dir=$OutputDir"
Write-Output "postgres_backup=$pgBackup"
Write-Output "minio_backup=$objectBackup"
