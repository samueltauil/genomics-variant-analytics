#Requires -Version 7.2
<#
.SYNOPSIS
    Provisions the disposable Azure environment for the genomics variant accelerator.
.DESCRIPTION
    Deploys the SMB landing zone, ADLS Gen2 landing account and workload identities, then
    creates the healthcare data solutions folder taxonomy over the data plane using Entra
    authentication. Every resource is tagged for teardown by Remove-Accelerator.ps1.

    This script provisions billable resources. Run with -WhatIf first.
#>
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [ValidatePattern('^[a-z0-9]{2,10}$')]
    [string] $EnvironmentName = 'demo',

    [ValidateNotNullOrEmpty()]
    [string] $Location = 'eastus2',

    [ValidateRange(1, 30)]
    [int] $ExpiresInDays = 1,

    [ValidateRange(32, 262144)]
    [int] $ShareQuotaGiB = 128,

    [ValidateRange(3000, 102400)]
    [int] $ShareIops = 3000,

    [ValidateRange(125, 10340)]
    [int] $ShareBandwidthMibps = 200,

    [ValidateNotNullOrEmpty()]
    [string] $SubscriptionId
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$templatePath = Join-Path $repositoryRoot 'infra/main.bicep'
$environmentFile = Join-Path $repositoryRoot '.azure/environment.env.json'
$keyPath = Join-Path $repositoryRoot '.azure/client.local.key'

# Top-level taxonomy from healthcare data solutions, with the genomics modality beneath it.
$taxonomy = @(
    'Ingest/Genomics/BCL'
    'Ingest/Genomics/FASTQ'
    'Ingest/Genomics/BAM'
    'Ingest/Genomics/VCF'
    'Process/Genomics/FASTQ'
    'Process/Genomics/BAM'
    'Process/Genomics/VCF'
    'Failed/Genomics'
    'External/Genomics'
    'Inventory/Genomics'
    'ReferenceData/Genomics'
    'SampleData/Genomics'
)

function Invoke-Az {
    param([Parameter(Mandatory)][string[]] $Arguments, [string] $ErrorMessage = 'Azure CLI call failed')

    $output = & az @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$ErrorMessage`n$output"
    }
    return $output
}

if (-not $SubscriptionId) {
    $SubscriptionId = Invoke-Az @('account', 'show', '--query', 'id', '-o', 'tsv') 'No subscription selected. Run az login or pass -SubscriptionId.'
}

$account = Invoke-Az @('account', 'show', '--subscription', $SubscriptionId, '-o', 'json') 'Could not read the requested subscription' | ConvertFrom-Json
$deployerObjectId = Invoke-Az @('ad', 'signed-in-user', 'show', '--query', 'id', '-o', 'tsv') 'Could not resolve the signed-in principal'
$expiresOn = (Get-Date).AddDays($ExpiresInDays).ToString('yyyy-MM-dd')
$deploymentName = "genomics-$EnvironmentName-$(Get-Date -Format 'yyyyMMddHHmmss')"

New-Item -ItemType Directory -Force -Path (Join-Path $repositoryRoot '.azure') | Out-Null
if (-not (Test-Path -LiteralPath $keyPath)) {
    # Linux provisioning requires a key even though verification runs through run-command.
    & ssh-keygen -t ed25519 -N '""' -C "genomics-$EnvironmentName" -f $keyPath -q
    if ($LASTEXITCODE -ne 0) { throw 'Could not generate the client provisioning key.' }
}
$adminPublicKey = (Get-Content -LiteralPath "$keyPath.pub" -Raw).Trim()

Write-Host "Subscription : $($account.name)"
Write-Host "Region       : $Location"
Write-Host "Environment  : $EnvironmentName (expires $expiresOn)"

$parameters = @(
    "environmentName=$EnvironmentName"
    "location=$Location"
    "deployerPrincipalId=$deployerObjectId"
    "expiresOn=$expiresOn"
    "adminPublicKey=$adminPublicKey"
    "landingShareQuotaGiB=$ShareQuotaGiB"
    "landingProvisionedIops=$ShareIops"
    "landingProvisionedBandwidthMibps=$ShareBandwidthMibps"
)

$common = @(
    '--subscription', $SubscriptionId
    '--location', $Location
    '--template-file', $templatePath
    '--parameters'
) + $parameters

if (-not $PSCmdlet.ShouldProcess("subscription $($account.name)", "deploy $deploymentName")) {
    Invoke-Az (@('deployment', 'sub', 'what-if') + $common) 'What-if analysis failed'
    return
}

$result = Invoke-Az (
    @('deployment', 'sub', 'create', '--name', $deploymentName, '-o', 'json') + $common
) 'Deployment failed' | ConvertFrom-Json
$outputs = $result.properties.outputs

Write-Host 'Creating the folder taxonomy from inside the network.'
$lakeAccount = $outputs.lakeStorageAccount.value
$filesystem = $outputs.lakeFilesystem.value
$clientName = $outputs.verificationClientName.value
$stagingClientId = $outputs.stagingIdentityClientId.value
$resourceGroupName = $outputs.resourceGroupName.value

$directoryList = ($taxonomy | ForEach-Object { "'$_'" }) -join ' '
$taxonomyTemplate = @'
set -eu
token=$(curl -s -m 30 -H Metadata:true "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fstorage.azure.com%2F&client_id=__CLIENT_ID__" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
failed=0
for directory in __DIRECTORIES__; do
  status=$(curl -s -o /dev/null -w '%{http_code}' -X PUT -H "Authorization: Bearer $token" -H 'x-ms-version: 2021-06-08' -H 'Content-Length: 0' "https://__ACCOUNT__.dfs.core.windows.net/__FILESYSTEM__/$directory?resource=directory")
  echo "$directory -> $status"
  case "$status" in 201|409) ;; *) failed=1 ;; esac
done
exit $failed
'@

$taxonomyScript = $taxonomyTemplate.
    Replace('__CLIENT_ID__', $stagingClientId).
    Replace('__DIRECTORIES__', $directoryList).
    Replace('__ACCOUNT__', $lakeAccount).
    Replace('__FILESYSTEM__', $filesystem)

# run-command splits --scripts on whitespace, so the script is delivered as a file with LF endings.
$scriptPath = Join-Path ([IO.Path]::GetTempPath()) "genomics-taxonomy-$([guid]::NewGuid().ToString('n')).sh"
[IO.File]::WriteAllText($scriptPath, $taxonomyScript.Replace("`r`n", "`n"))
try {
    $runResult = Invoke-Az @(
        'vm', 'run-command', 'invoke'
        '--name', $clientName
        '--resource-group', $resourceGroupName
        '--subscription', $SubscriptionId
        '--command-id', 'RunShellScript'
        '--scripts', "@$scriptPath"
        '-o', 'json'
    ) 'Could not create the folder taxonomy' | ConvertFrom-Json
}
finally {
    Remove-Item -LiteralPath $scriptPath -Force -ErrorAction SilentlyContinue
}

$runMessage = $runResult.value[0].message
$created = ([regex]::Matches($runMessage, '-> (201|409)')).Count
if ($created -ne $taxonomy.Count) {
    throw "Folder taxonomy incomplete: $created of $($taxonomy.Count) directories.`n$runMessage"
}
Write-Host "Folder taxonomy created by the staging identity ($created directories)."

$environment = [ordered]@{
    subscriptionId    = $SubscriptionId
    subscriptionName  = $account.name
    tenantId          = $account.tenantId
    location          = $Location
    environmentName   = $EnvironmentName
    expiresOn         = $expiresOn
    resourceGroupName = $resourceGroupName
    landingAccount    = $outputs.landingStorageAccount.value
    landingShare      = $outputs.landingShareName.value
    landingUncPath    = $outputs.landingUncPath.value
    lakeAccount       = $lakeAccount
    lakeFilesystem    = $filesystem
    verificationVm    = $clientName
    taxonomy          = $taxonomy
    identities        = [ordered]@{
        ingestion = $outputs.ingestionIdentityClientId.value
        staging   = $outputs.stagingIdentityClientId.value
        pipeline  = $outputs.pipelineIdentityClientId.value
    }
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $environmentFile) | Out-Null
$environment | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $environmentFile -Encoding utf8

Write-Host "Deployed. Environment recorded in $environmentFile (untracked)."
Write-Host "Tear down with: ./scripts/Remove-Accelerator.ps1 -EnvironmentName $EnvironmentName"
