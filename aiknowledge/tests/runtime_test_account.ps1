# Shared by the Compose runtime smoke tests. Credentials remain in memory.
function New-RuntimeTestAccount([string]$ApiBase) {
    $runtimeEmail = "aiknowledge-runtime-$([guid]::NewGuid().ToString('N'))@example.invalid"
    $passwordBytes = New-Object byte[] 32
    $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $random.GetBytes($passwordBytes)
        $runtimePassword = [Convert]::ToBase64String($passwordBytes)
        return Invoke-RestMethod "$ApiBase/auth/register" -Method Post -ContentType "application/json" -Body (@{
            email = $runtimeEmail
            password = $runtimePassword
            display_name = "Runtime E2E"
        } | ConvertTo-Json)
    }
    catch {
        throw "Unable to register the isolated runtime test account."
    }
    finally {
        $random.Dispose()
        [Array]::Clear($passwordBytes, 0, $passwordBytes.Length)
        $runtimePassword = $null
    }
}

function Disable-RuntimeTestAccount([string]$RepoRoot, [object]$AuthResponse) {
    $cleanupScript = Join-Path $RepoRoot "ops\disable_runtime_accounts.py"
    $composeFile = Join-Path $RepoRoot "compose.yaml"
    $envFile = Join-Path $RepoRoot "aiknowledge\.env"
    $cleanupCode = Get-Content -LiteralPath $cleanupScript -Raw
    $output = $cleanupCode | & docker compose --project-directory $RepoRoot --file $composeFile --env-file $envFile exec -T api python - `
        --user-id $AuthResponse.user.id --email $AuthResponse.user.email
    if ($LASTEXITCODE -ne 0 -or $output -notcontains "runtime_account_disabled=true") {
        throw "Unable to disable the runtime test account. Retry ops/disable_runtime_accounts.py --user-id $($AuthResponse.user.id) --email $($AuthResponse.user.email)."
    }
    Write-Output "temporary_account_disabled=true"
}
