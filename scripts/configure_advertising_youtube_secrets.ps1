param(
    [ValidateSet("jp","us")]
    [string]$Market = "jp",
    [string]$Repo = "shihuiarenjinba-png/youtube-auto",
    [string]$Branch = "codex/port-proven-uploader",
    [string]$TokenJsonPath = "",
    [switch]$PromptInsteadOfTokenFile
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Read-SecretText([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        $secure.Dispose()
    }
}

function Set-GitHubSecretFromText([string]$Name, [string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "Secret value is empty: $Name"
    }
    $Value | gh secret set $Name --repo $Repo
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to set GitHub secret: $Name"
    }
    Write-Host "[PASS] GitHub secret updated: $Name"
}

function Get-TokenJsonValues([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Token JSON not found: $Path"
    }

    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $obj = $raw | ConvertFrom-Json

    $clientId = [string]$obj.client_id
    $clientSecret = [string]$obj.client_secret
    $refreshToken = [string]$obj.refresh_token

    if ([string]::IsNullOrWhiteSpace($clientId)) { throw "client_id is missing from token JSON" }
    if ([string]::IsNullOrWhiteSpace($clientSecret)) { throw "client_secret is missing from token JSON" }
    if ([string]::IsNullOrWhiteSpace($refreshToken)) { throw "refresh_token is missing from token JSON" }

    return @{
        ClientId = $clientId
        ClientSecret = $clientSecret
        RefreshToken = $refreshToken
    }
}

Require-Command "gh"

gh auth status *> $null
if ($LASTEXITCODE -ne 0) {
    throw "GitHub CLI is not authenticated. Run: gh auth login"
}

$marketUpper = $Market.ToUpperInvariant()
$secretNames = @{
    ClientId = "AD_YOUTUBE_CLIENT_ID_$marketUpper"
    ClientSecret = "AD_YOUTUBE_CLIENT_SECRET_$marketUpper"
    RefreshToken = "AD_YOUTUBE_REFRESH_TOKEN_$marketUpper"
}

if ($Market -eq "jp" -and [string]::IsNullOrWhiteSpace($TokenJsonPath) -and -not $PromptInsteadOfTokenFile) {
    $TokenJsonPath = "C:\Users\aaron\Desktop\auto-blogger\vendor\shorts_factory\token_3.json"
}

if ($Market -eq "us" -and [string]::IsNullOrWhiteSpace($TokenJsonPath) -and -not $PromptInsteadOfTokenFile) {
    throw "US advertising identity is HOLD. Supply a confirmed US token explicitly only after identity review."
}

$values = $null
try {
    if ($PromptInsteadOfTokenFile) {
        $values = @{
            ClientId = Read-SecretText "Advertising $marketUpper client ID"
            ClientSecret = Read-SecretText "Advertising $marketUpper client secret"
            RefreshToken = Read-SecretText "Advertising $marketUpper refresh token"
        }
    }
    else {
        Write-Host "Reading credentials from confirmed advertising token file:"
        Write-Host "  $TokenJsonPath"
        $values = Get-TokenJsonValues $TokenJsonPath
    }

    Write-Host ""
    Write-Host "Target repository: $Repo"
    Write-Host "Target market:     advertising.$Market"
    Write-Host "Target branch:     $Branch"
    Write-Host "No secret values will be printed or committed."
    Write-Host ""

    Set-GitHubSecretFromText $secretNames.ClientId $values.ClientId
    Set-GitHubSecretFromText $secretNames.ClientSecret $values.ClientSecret
    Set-GitHubSecretFromText $secretNames.RefreshToken $values.RefreshToken

    $beforeJson = gh run list --repo $Repo --workflow youtube-ad-pipeline.yml --branch $Branch --event workflow_dispatch --limit 20 --json databaseId
    if ($LASTEXITCODE -ne 0) { throw "Could not list workflow runs before dispatch." }

    $beforeIds = @()
    if ($beforeJson) {
        $beforeIds = @($beforeJson | ConvertFrom-Json | ForEach-Object { [Int64]$_.databaseId })
    }

    Write-Host ""
    Write-Host "Dispatching read-only advertising OAuth identity check..."
    gh workflow run youtube-ad-pipeline.yml --repo $Repo --ref $Branch -f market=$Market -f mode=advertising-oauth-check
    if ($LASTEXITCODE -ne 0) { throw "Failed to dispatch read-only OAuth check." }

    $runId = $null
    for ($i = 0; $i -lt 30 -and -not $runId; $i++) {
        Start-Sleep -Seconds 2
        $runsJson = gh run list --repo $Repo --workflow youtube-ad-pipeline.yml --branch $Branch --event workflow_dispatch --limit 20 --json databaseId,headSha,status,conclusion,createdAt
        if ($LASTEXITCODE -ne 0) { continue }
        $runs = @($runsJson | ConvertFrom-Json)
        $newRun = $runs | Where-Object { $beforeIds -notcontains [Int64]$_.databaseId } | Sort-Object createdAt -Descending | Select-Object -First 1
        if ($newRun) { $runId = [Int64]$newRun.databaseId }
    }

    if (-not $runId) {
        throw "Workflow was dispatched, but the new run ID could not be identified."
    }

    Write-Host "Read-only run ID: $runId"
    gh run watch $runId --repo $Repo --exit-status
    $watchExit = $LASTEXITCODE

    Write-Host ""
    Write-Host "Safe identity evidence:"
    gh run view $runId --repo $Repo --log | Select-String -Pattern "ADVERTISING_YOUTUBE_IDENTITY_PASS|HOLD_|actual_channel|expected_channel|write_performed|fallback_performed"

    if ($watchExit -ne 0) {
        throw "Read-only OAuth identity check did not pass. No upload was authorized."
    }

    Write-Host ""
    Write-Host "[PASS] Advertising OAuth secrets were sent and the read-only identity workflow completed successfully."
    Write-Host "No YouTube upload was requested by this script."
}
finally {
    if ($values) {
        $values.ClientId = $null
        $values.ClientSecret = $null
        $values.RefreshToken = $null
    }
    Remove-Variable values -ErrorAction SilentlyContinue
}
