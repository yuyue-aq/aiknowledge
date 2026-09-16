param(
    # 127.0.0.2 avoids colliding with a locally running uvicorn bound to
    # 127.0.0.1 while still reaching the Docker port published on 0.0.0.0.
    [string]$ApiBase = "http://127.0.0.2:8000/api/v1",
    [string]$FixturePath = "D:\develop\aiknowledge\aiknowledge\.env.example"
)

$ErrorActionPreference = "Stop"
$space = $null

function Invoke-JsonPost([string]$Uri, $Body) {
    return Invoke-RestMethod -Uri $Uri -Method Post -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 8)
}

function Get-ObjectExists([string]$ObjectKey) {
    $escapedKey = $ObjectKey.Replace("'", "''")
    $code = "import os; from minio import Minio; c=Minio(os.environ['AIKNOWLEDGE_MINIO_ENDPOINT'], access_key=os.environ['AIKNOWLEDGE_MINIO_ACCESS_KEY'], secret_key=os.environ['AIKNOWLEDGE_MINIO_SECRET_KEY'], secure=False); key='$escapedKey'; exists=any(item.object_name == key for item in c.list_objects(os.environ['AIKNOWLEDGE_MINIO_BUCKET'], prefix=key)); print('exists=' + str(exists).lower())"
    $output = & docker compose --env-file aiknowledge/.env exec -T api python -c $code
    if ($LASTEXITCODE -ne 0) { throw "unable to inspect MinIO object" }
    return ($output -match "exists=true")
}

try {
    if (-not (Test-Path -LiteralPath $FixturePath -PathType Leaf)) {
        throw "fixture not found: $FixturePath"
    }

    $space = Invoke-JsonPost "$ApiBase/spaces" @{
        name = "runtime-delete-e2e-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
        description = "temporary delete cleanup test"
        visibility = "PRIVATE"
        guest_feedback_enabled = $false
    }
    $upload = & curl.exe -sS -X POST `
        -F "file=@$FixturePath;filename=runtime-cleanup.txt;type=text/plain" `
        "$ApiBase/spaces/$($space.id)/documents"
    if ($LASTEXITCODE -ne 0) { throw "document upload command failed" }
    $submission = $upload | ConvertFrom-Json
    $documentId = $submission.document.id
    $objectKey = "documents/$($space.id)/$documentId/source.txt"
    Write-Output "document_uploaded=true"
    Write-Output "object_exists_before_delete=$(Get-ObjectExists $objectKey)"

    Invoke-RestMethod "$ApiBase/documents/$documentId" -Method Delete | Out-Null
    Write-Output "document_deleted=true"

    $existsAfterDelete = $true
    for ($attempt = 0; $attempt -lt 15; $attempt++) {
        Start-Sleep -Seconds 2
        $existsAfterDelete = Get-ObjectExists $objectKey
        if (-not $existsAfterDelete) { break }
    }
    Write-Output "object_exists_after_delete=$existsAfterDelete"
    if ($existsAfterDelete) { throw "object still exists after cleanup task window" }

    try {
        Invoke-RestMethod "$ApiBase/documents/$documentId" -Method Get | Out-Null
        throw "deleted document remained visible"
    }
    catch {
        if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw }
    }
    Write-Output "deleted_document_hidden=true"
}
finally {
    if ($null -ne $space) {
        try {
            Invoke-RestMethod "$ApiBase/spaces/$($space.id)" -Method Delete | Out-Null
            Write-Output "temporary_space_deleted=true"
        }
        catch {
            Write-Output "temporary_space_deleted=false"
            Write-Error $_
        }
    }
}
