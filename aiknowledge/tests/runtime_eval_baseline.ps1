param(
    [string]$ApiBase = "http://localhost:8000/api/v1",
    [string]$ManifestPath = "",
    [int]$DocumentTimeoutSeconds = 1200,
    [switch]$AllowExternalData
)

$ErrorActionPreference = "Stop"
$space = $null
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $ManifestPath = Join-Path $repoRoot "eval\mvp_eval_set.json"
}
$privateCanaryPath = Join-Path $PSScriptRoot "runtime_private_canary.txt"

function Invoke-JsonPost([string]$Uri, $Body) {
    $json = if ($null -eq $Body) {
        "{}"
    } else {
        $Body | ConvertTo-Json -Depth 10 -Compress
    }
    return Invoke-RestMethod -Uri $Uri -Method Post -ContentType "application/json" -Body $json
}

function Upload-Markdown([string]$SpaceId, [string]$CategoryId, [string]$Path, [string]$Filename) {
    $extension = [IO.Path]::GetExtension($Filename).ToLowerInvariant()
    $contentType = if ($extension -eq ".txt") { "text/plain" } else { "text/markdown" }
    $upload = & curl.exe -sS -X POST `
        -F "file=@$Path;filename=$Filename;type=$contentType" `
        -F "category_id=$CategoryId" `
        "$ApiBase/spaces/$SpaceId/documents"
    if ($LASTEXITCODE -ne 0) { throw "document upload command failed: $Filename" }
    $submission = $upload | ConvertFrom-Json
    if ($null -eq $submission.document -or $null -eq $submission.document.id) {
        throw "document upload rejected for $Filename`: $upload"
    }
    return $submission
}

function Wait-DocumentReady([string]$DocumentId, [string]$Label) {
    $deadline = (Get-Date).AddSeconds($DocumentTimeoutSeconds)
    do {
        Start-Sleep -Seconds 5
        $document = Invoke-RestMethod "$ApiBase/documents/$DocumentId"
        Write-Output "document_status[$Label]=$($document.status)"
        if ($document.status -ne "PROCESSING") { break }
    } while ((Get-Date) -lt $deadline)
    if ($document.status -ne "READY") {
        throw "document processing status for $Label`: $($document.status) $($document.failure_message)"
    }
}

try {
    if (-not $AllowExternalData) {
        throw "This evaluation uploads project documents to the configured DeepSeek service. Re-run with -AllowExternalData only after explicit data-sharing authorization."
    }
    if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
        throw "evaluation manifest not found: $ManifestPath"
    }
    if (-not (Test-Path -LiteralPath $privateCanaryPath -PathType Leaf)) {
        throw "private canary fixture not found: $privateCanaryPath"
    }

    $manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
    $space = Invoke-JsonPost "$ApiBase/spaces" @{
        name = "runtime-eval-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
        description = "temporary real-material evaluation baseline"
        visibility = "PUBLIC"
        guest_feedback_enabled = $false
    }
    Write-Output "space_created=true"

    $openCategory = Invoke-JsonPost "$ApiBase/spaces/$($space.id)/categories" @{
        name = "open-primary"
        description = "project requirements and technical overview"
        is_open = $true
        sort_order = 0
    }
    $closedCategory = Invoke-JsonPost "$ApiBase/spaces/$($space.id)/categories" @{
        name = "closed-internal"
        description = "internal planning and security fixture"
        is_open = $false
        sort_order = 1
    }
    Write-Output "categories_created=true"

    $documentSpecs = @(
        @{ key = "requirements"; path = (Join-Path $repoRoot "需求分析文档.md"); filename = "需求分析文档.md"; category = $openCategory.id },
        @{ key = "technical"; path = (Join-Path $repoRoot "技术方案.md"); filename = "技术方案.md"; category = $openCategory.id },
        @{ key = "plan"; path = (Join-Path $repoRoot "MVP开发计划.md"); filename = "MVP开发计划.md"; category = $closedCategory.id },
        @{ key = "canary"; path = $privateCanaryPath; filename = "runtime-private-canary.txt"; category = $closedCategory.id }
    )
    $documentIds = @{}
    foreach ($spec in $documentSpecs) {
        if (-not (Test-Path -LiteralPath $spec.path -PathType Leaf)) {
            throw "evaluation source not found: $($spec.path)"
        }
        $submission = Upload-Markdown $space.id $spec.category $spec.path $spec.filename
        $documentIds[$spec.key] = $submission.document.id
        Write-Output "document_uploaded[$($spec.key)]=true"
    }
    foreach ($spec in $documentSpecs) {
        Wait-DocumentReady $documentIds[$spec.key] $spec.key
    }

    $ownerDocuments = @(
        $documentIds["requirements"],
        $documentIds["technical"],
        $documentIds["plan"],
        $documentIds["canary"]
    )
    $publicDocuments = @($documentIds["requirements"], $documentIds["technical"])
    $caseIds = @{}
    foreach ($case in @($manifest.cases)) {
        $categoryIds = if ($case.scope -eq "OWNER") {
            @()
        } else {
            @($openCategory.id)
        }
        $expectedDocuments = if ($case.scope -eq "OWNER") {
            $ownerDocuments
        } else {
            $publicDocuments
        }
        $createdCase = Invoke-JsonPost "$ApiBase/spaces/$($space.id)/eval-cases" @{
            question = $case.question
            expected_answer = $null
            expected_document_ids = @($expectedDocuments)
            scope = $case.scope
            category_ids = @($categoryIds)
        }
        $caseIds[$createdCase.id] = $case.id
    }
    Write-Output "evaluation_cases_created=$($caseIds.Count)"

    $started = Get-Date
    $detail = Invoke-JsonPost "$ApiBase/spaces/$($space.id)/eval-runs" $null
    $elapsedSeconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 1)
    Write-Output "evaluation_run_status=$($detail.run.status)"
    Write-Output "evaluation_elapsed_seconds=$elapsedSeconds"
    Write-Output "summary_total=$($detail.summary.total)"
    Write-Output "summary_answered=$($detail.summary.answered)"
    Write-Output "summary_insufficient_evidence=$($detail.summary.insufficient_evidence)"
    Write-Output "summary_out_of_scope=$($detail.summary.out_of_scope)"
    Write-Output "summary_failed=$($detail.summary.failed)"
    Write-Output "summary_citation_count=$($detail.summary.citation_count)"
    Write-Output "summary_out_of_scope_violations=$($detail.summary.out_of_scope_violations)"

    foreach ($result in @($detail.results)) {
        $caseId = $caseIds[$result.eval_case_id]
        Write-Output "case=$caseId;status=$($result.answer_status);citations=$($result.citation_count)"
        if ($caseId -eq "public-private-canary-08") {
            # The canary identifier is intentionally present in the test
            # question, so its echo alone is not evidence of retrieval. Check
            # for private-only prose instead and rely on the API's
            # out_of_scope_violations counter for the authorization boundary.
            $privateOnlyMarkers = @(
                "This document belongs only to the closed internal category",
                "must never be exposed to public visitors"
            )
            $markerLeak = $privateOnlyMarkers | Where-Object { $result.answer -like "*$_*" }
            Write-Output "public_canary_private_marker_leak=$([bool]$markerLeak)"
            if ($markerLeak -or $detail.summary.out_of_scope_violations -gt 0) {
                throw "private canary content appeared in public evaluation answer"
            }
        }
    }
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
