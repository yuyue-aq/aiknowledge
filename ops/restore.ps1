param(
    [Parameter(Mandatory = $true)]
    [string]$PostgresBackup,
    [Parameter(Mandatory = $true)]
    [string]$MinioBackup,
    [switch]$ConfirmRestore,
    [string]$EnvFile = ""
)

$ErrorActionPreference = "Stop"
if (-not $ConfirmRestore) {
    throw "Restore is destructive. Re-run with -ConfirmRestore after stopping application writers and verifying the backup."
}
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($EnvFile)) {
    $EnvFile = Join-Path $repoRoot "aiknowledge\.env"
}
if (-not (Test-Path -LiteralPath $PostgresBackup -PathType Leaf)) {
    throw "PostgreSQL backup not found: $PostgresBackup"
}
if (-not (Test-Path -LiteralPath $MinioBackup -PathType Container) -and -not (Test-Path -LiteralPath $MinioBackup -PathType Leaf)) {
    throw "MinIO backup artifact not found: $MinioBackup"
}

function Read-EnvValue([string]$Name, [string]$Fallback) {
    if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) { return $Fallback }
    $line = Get-Content -LiteralPath $EnvFile | Where-Object { $_ -match "^\s*$Name\s*=" } | Select-Object -First 1
    if ($null -eq $line) { return $Fallback }
    return (($line -split "=", 2)[1].Trim()).Trim('"', "'")
}

$composeBaseArgs = @("compose", "--project-directory", $repoRoot)
if (Test-Path -LiteralPath $EnvFile -PathType Leaf) {
    $composeBaseArgs += @("--env-file", $EnvFile)
}
$pgArgs = $composeBaseArgs + @("exec", "-T", "postgres", "pg_restore", "--clean", "--if-exists", "--no-owner", "--username=$(Read-EnvValue 'POSTGRES_USER' 'aiknowledge')", "--dbname=$(Read-EnvValue 'POSTGRES_DB' 'aiknowledge')")
Get-Content -LiteralPath $PostgresBackup -AsByteStream -Raw | & docker @pgArgs
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL restore failed." }

$minioEndpoint = Read-EnvValue 'AIKNOWLEDGE_MINIO_ENDPOINT' 'http://127.0.0.1:9000'
if ($minioEndpoint -notmatch '^https?://') { $minioEndpoint = "http://$minioEndpoint" }
$minioUser = Read-EnvValue 'MINIO_ROOT_USER' 'aiknowledge'
$minioPassword = Read-EnvValue 'MINIO_ROOT_PASSWORD' 'aiknowledge-local-dev-secret'
$minioBucket = Read-EnvValue 'AIKNOWLEDGE_MINIO_BUCKET' 'aiknowledge-private'
if ((Test-Path -LiteralPath $MinioBackup -PathType Container) -and (Get-Command mc -ErrorAction SilentlyContinue)) {
    & mc alias set aiknowledge-restore $minioEndpoint $minioUser $minioPassword --api S3v4 | Out-Null
    & mc mirror --overwrite --remove $MinioBackup "aiknowledge-restore/$minioBucket"
    if ($LASTEXITCODE -ne 0) { throw "MinIO restore failed." }
} else {
    if (-not (Test-Path -LiteralPath $MinioBackup -PathType Leaf)) {
        throw "A directory backup requires the MinIO client 'mc' on PATH."
    }
    $code = 'import io,os,sys,tarfile; from minio import Minio; c=Minio(os.environ["AIKNOWLEDGE_MINIO_ENDPOINT"],access_key=os.environ["AIKNOWLEDGE_MINIO_ACCESS_KEY"],secret_key=os.environ["AIKNOWLEDGE_MINIO_SECRET_KEY"],secure=os.environ.get("AIKNOWLEDGE_MINIO_SECURE","false").lower()=="true"); b=os.environ["AIKNOWLEDGE_MINIO_BUCKET"]; a=tarfile.open(fileobj=sys.stdin.buffer,mode="r|"); [c.put_object(b,m.name,io.BytesIO(m.read()),length=m.size) for m in a if m.isfile()]; a.close()'
    $apiArgs = $composeBaseArgs + @("exec", "-T", "api", "python", "-c", $code)
    Get-Content -LiteralPath $MinioBackup -AsByteStream -Raw | & docker @apiArgs
    if ($LASTEXITCODE -ne 0) { throw "MinIO restore failed." }
}

Write-Output "restore_completed=true"
