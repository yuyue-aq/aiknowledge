param(
    [string]$ApiBase = "http://localhost:8000/api/v1",
    [string]$FixturePath = "",
    [int]$DocumentTimeoutSeconds = 1200
)

$ErrorActionPreference = "Stop"
$space = $null
$auth = $null
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
. (Join-Path $PSScriptRoot "runtime_test_account.ps1")
if ([string]::IsNullOrWhiteSpace($FixturePath)) {
    $FixturePath = Join-Path $repoRoot "aiknowledge\tests\runtime_synthetic_public.txt"
}

function Invoke-JsonPost([string]$Uri, $Body, [object]$Session = $null, [hashtable]$Headers = $null) {
    $params = @{
        Uri = $Uri
        Method = "Post"
        ContentType = "application/json"
        Body = ($Body | ConvertTo-Json -Depth 8)
    }
    if ($null -ne $Session) { $params.WebSession = $Session }
    if ($null -ne $Headers) { $params.Headers = $Headers }
    return Invoke-RestMethod @params
}

try {
    if (-not (Test-Path -LiteralPath $FixturePath -PathType Leaf)) {
        throw "fixture not found: $FixturePath"
    }

    $auth = New-RuntimeTestAccount $ApiBase
    $ownerHeaders = @{ Authorization = "Bearer $($auth.tokens.access_token)" }

    $space = Invoke-JsonPost "$ApiBase/spaces" @{
        name = "runtime-public-e2e-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
        description = "temporary runtime smoke test"
        visibility = "PUBLIC"
        guest_feedback_enabled = $false
    } $null $ownerHeaders
    Write-Output "space_created=true"

    $category = Invoke-JsonPost "$ApiBase/spaces/$($space.id)/categories" @{
        name = "Runtime smoke"
        description = "temporary open category"
        is_open = $true
        sort_order = 0
    } $null $ownerHeaders
    Write-Output "category_created=true"

    $link = Invoke-JsonPost "$ApiBase/spaces/$($space.id)/share-links" @{
        category_ids = @($category.id)
    } $null $ownerHeaders
    Write-Output "share_link_created=true"

    $upload = & curl.exe -sS -X POST `
        -F "file=@$FixturePath;filename=runtime-smoke.txt;type=text/plain" `
        -F "category_id=$($category.id)" `
        -H "Authorization: Bearer $($auth.tokens.access_token)" `
        "$ApiBase/spaces/$($space.id)/documents"
    if ($LASTEXITCODE -ne 0) { throw "document upload command failed" }
    $submission = $upload | ConvertFrom-Json
    $documentId = $submission.document.id
    Write-Output "document_uploaded=true"

    $deadline = (Get-Date).AddSeconds($DocumentTimeoutSeconds)
    do {
        Start-Sleep -Seconds 5
        $document = Invoke-RestMethod "$ApiBase/documents/$documentId" -Headers $ownerHeaders
        Write-Output "document_status=$($document.status)"
        if ($document.status -ne "PROCESSING") { break }
    } while ((Get-Date) -lt $deadline)
    if ($document.status -ne "READY") {
        throw "document processing status: $($document.status)"
    }

    $ownerConversation = Invoke-JsonPost "$ApiBase/owner/conversations" @{
        space_id = $space.id
        title = "Runtime smoke owner"
    } $null $ownerHeaders
    $ownerAnswer = Invoke-JsonPost "$ApiBase/owner/conversations/$($ownerConversation.id)/messages" @{
        question = "BGE 模型产生多少维向量？"
        stream = $false
    } $null $ownerHeaders
    Write-Output "owner_status=$($ownerAnswer.status)"
    Write-Output "owner_citations=$(@($ownerAnswer.citations).Count)"

    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $publicSession = Invoke-JsonPost "$ApiBase/public/session" @{ token = $link.token } $session
    if ($publicSession.categories.Count -lt 1) { throw "public session has no open category" }
    $publicConversation = Invoke-JsonPost "$ApiBase/public/conversations" @{} $session
    $publicAnswer = Invoke-JsonPost "$ApiBase/public/conversations/$($publicConversation.id)/messages" @{
        question = "BGE 模型产生多少维向量？"
        stream = $false
    } $session
    $directQuery = Invoke-JsonPost "$ApiBase/public/query" @{
        token = $link.token
        question = "BGE 模型产生多少维向量？"
    }
    Write-Output "public_status=$($publicAnswer.status)"
    Write-Output "public_has_citations=$($publicAnswer.PSObject.Properties.Name -contains 'citations')"
    Write-Output "public_fields=$([string]::Join(',', @($publicAnswer.PSObject.Properties.Name | Sort-Object)))"
    Write-Output "direct_query_status=$($directQuery.status)"
    Write-Output "direct_query_has_citations=$($directQuery.PSObject.Properties.Name -contains 'citations')"
}
finally {
    try {
        if ($null -ne $space) {
            try {
                Invoke-RestMethod "$ApiBase/spaces/$($space.id)" -Method Delete -Headers $ownerHeaders | Out-Null
                Write-Output "temporary_space_deleted=true"
            }
            catch {
                Write-Output "temporary_space_deleted=false"
                throw "Temporary space cleanup failed."
            }
        }
    }
    finally {
        if ($null -ne $auth) {
            Disable-RuntimeTestAccount $repoRoot $auth
        }
    }
}
