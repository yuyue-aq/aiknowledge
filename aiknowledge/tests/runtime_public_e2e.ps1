param(
    [string]$ApiBase = "http://127.0.0.1:8000/api/v1",
    [string]$FixturePath = "D:\develop\aiknowledge\aiknowledge\.env.example",
    [int]$DocumentTimeoutSeconds = 1200
)

$ErrorActionPreference = "Stop"
$space = $null

function Invoke-JsonPost([string]$Uri, $Body, [object]$Session = $null) {
    $params = @{
        Uri = $Uri
        Method = "Post"
        ContentType = "application/json"
        Body = ($Body | ConvertTo-Json -Depth 8)
    }
    if ($null -ne $Session) { $params.WebSession = $Session }
    return Invoke-RestMethod @params
}

try {
    if (-not (Test-Path -LiteralPath $FixturePath -PathType Leaf)) {
        throw "fixture not found: $FixturePath"
    }

    $space = Invoke-JsonPost "$ApiBase/spaces" @{
        name = "runtime-public-e2e-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
        description = "temporary runtime smoke test"
        visibility = "PUBLIC"
        guest_feedback_enabled = $false
    }
    Write-Output "space_created=true"

    $category = Invoke-JsonPost "$ApiBase/spaces/$($space.id)/categories" @{
        name = "Runtime smoke"
        description = "temporary open category"
        is_open = $true
        sort_order = 0
    }
    Write-Output "category_created=true"

    $link = Invoke-JsonPost "$ApiBase/spaces/$($space.id)/share-links" @{
        category_ids = @($category.id)
    }
    Write-Output "share_link_created=true"

    $upload = & curl.exe -sS -X POST `
        -F "file=@$FixturePath;filename=runtime-smoke.txt;type=text/plain" `
        -F "category_id=$($category.id)" `
        "$ApiBase/spaces/$($space.id)/documents"
    if ($LASTEXITCODE -ne 0) { throw "document upload command failed" }
    $submission = $upload | ConvertFrom-Json
    $documentId = $submission.document.id
    Write-Output "document_uploaded=true"

    $deadline = (Get-Date).AddSeconds($DocumentTimeoutSeconds)
    do {
        Start-Sleep -Seconds 5
        $document = Invoke-RestMethod "$ApiBase/documents/$documentId"
        Write-Output "document_status=$($document.status)"
        if ($document.status -ne "PROCESSING") { break }
    } while ((Get-Date) -lt $deadline)
    if ($document.status -ne "READY") {
        throw "document processing status: $($document.status)"
    }

    $ownerConversation = Invoke-JsonPost "$ApiBase/owner/conversations" @{
        space_id = $space.id
        title = "Runtime smoke owner"
    }
    $ownerAnswer = Invoke-JsonPost "$ApiBase/owner/conversations/$($ownerConversation.id)/messages" @{
        question = "BGE 模型产生多少维向量？"
        stream = $false
    }
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
    Write-Output "public_status=$($publicAnswer.status)"
    Write-Output "public_has_citations=$($publicAnswer.PSObject.Properties.Name -contains 'citations')"
    Write-Output "public_fields=$([string]::Join(',', @($publicAnswer.PSObject.Properties.Name | Sort-Object)))"
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
