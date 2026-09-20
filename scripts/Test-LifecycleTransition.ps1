#Requires -Version 7.2
[CmdletBinding()]
param(
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string] $EnvironmentFile = (Join-Path (Split-Path -Parent $PSScriptRoot) '.azure/environment.env.json'),

    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string] $EvidenceFile = (Join-Path (Split-Path -Parent $PSScriptRoot) '.azure/lifecycle-acceptance.local.json'),

    [ValidateSet('Hot', 'Cool', 'Cold', 'Archive')]
    [string] $ExpectedTier = 'Cool'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$environment = Get-Content -LiteralPath $EnvironmentFile -Raw | ConvertFrom-Json
$evidence = Get-Content -LiteralPath $EvidenceFile -Raw | ConvertFrom-Json
$inspectionUri = $evidence.uri.Replace('.dfs.core.windows.net/', '.blob.core.windows.net/')
$startedClient = $false

$power = az vm get-instance-view `
    --resource-group $environment.resourceGroupName `
    --name $environment.verificationVm `
    --subscription $environment.subscriptionId `
    --query "instanceView.statuses[?starts_with(code, 'PowerState')].displayStatus" `
    -o tsv
if ($LASTEXITCODE -ne 0) {
    throw 'Could not read the verification client power state.'
}

if ($power -notmatch 'running') {
    az vm start `
        --resource-group $environment.resourceGroupName `
        --name $environment.verificationVm `
        --subscription $environment.subscriptionId `
        -o none
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not start the verification client.'
    }
    $startedClient = $true
}

$template = @'
set -eu
token=$(curl -s -m 30 -H Metadata:true "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fstorage.azure.com%2F&client_id=__CLIENT_ID__" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -sS -I -H "Authorization: Bearer $token" -H 'x-ms-version: 2023-11-03' '__URI__'
'@
$script = $template.
    Replace('__CLIENT_ID__', $environment.identities.staging).
    Replace('__URI__', $inspectionUri)
$scriptPath = Join-Path ([IO.Path]::GetTempPath()) "lifecycle-check-$([guid]::NewGuid().ToString('n')).sh"
[IO.File]::WriteAllText($scriptPath, $script.Replace("`r`n", "`n"))

try {
    $result = az vm run-command invoke `
        --resource-group $environment.resourceGroupName `
        --name $environment.verificationVm `
        --subscription $environment.subscriptionId `
        --command-id RunShellScript `
        --scripts "@$scriptPath" `
        -o json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not inspect the lifecycle acceptance artifact.'
    }
}
finally {
    Remove-Item -LiteralPath $scriptPath -Force -ErrorAction SilentlyContinue
    if ($startedClient) {
        az vm deallocate `
            --resource-group $environment.resourceGroupName `
            --name $environment.verificationVm `
            --subscription $environment.subscriptionId `
            -o none
        if ($LASTEXITCODE -ne 0) {
            throw 'Could not deallocate the verification client.'
        }
    }
}

$message = $result.value[0].message
$status = [regex]::Match($message, '(?im)^HTTP/\S+\s+(\d+)').Groups[1].Value
$tier = [regex]::Match($message, '(?im)^x-ms-access-tier:\s*(\S+)').Groups[1].Value
$report = [ordered]@{
    checkedAtUtc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    uri = $evidence.uri
    source = $evidence.lineage.source
    containsGenomicData = [bool]$evidence.lineage.containsGenomicData
    httpStatus = $status
    accessTier = $tier
    expectedTier = $ExpectedTier
    transitioned = $status -eq '200' -and $tier -eq $ExpectedTier
}
$report | ConvertTo-Json

if (-not $report.transitioned) {
    exit 1
}
