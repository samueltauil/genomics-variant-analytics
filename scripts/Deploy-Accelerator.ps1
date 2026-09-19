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
    [string] $SubscriptionId,

    [Parameter(HelpMessage = 'Object id of the deploying principal. Supply this when Microsoft Graph is unavailable, as it often is for CI identities.')]
    [ValidatePattern('^[0-9a-fA-F-]{36}$')]
    [string] $DeployerObjectId,

    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string] $PreflightSnapshotPath,

    [Parameter(HelpMessage = 'Deploy the Storage Actions lifecycle task (task 3.5). Disable to skip it entirely.')]
    [bool] $DeployStorageActions = $true,

    [ValidateRange(0, 365)]
    [int] $StorageActionsTierAfterDays = 1
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$templatePath = Join-Path $repositoryRoot 'infra/main.bicep'
$environmentFile = Join-Path $repositoryRoot '.azure/environment.env.json'
$keyPath = Join-Path $repositoryRoot '.azure/client.local.key'
$preflightPath = Join-Path $repositoryRoot 'scripts/Test-DemoPreflight.ps1'

Write-Host 'Running Azure preflight before any resource lookup or deployment.'
$preflightArgs = @(
    '-NoLogo', '-NoProfile', '-NonInteractive', '-File', $preflightPath,
    '-EnvironmentName', $EnvironmentName,
    '-Location', $Location,
    '-ShareQuotaGiB', $ShareQuotaGiB,
    '-ShareIops', $ShareIops,
    '-ShareBandwidthMibps', $ShareBandwidthMibps,
    '-RequireAzureChecks'
)
if ($SubscriptionId) {
    $preflightArgs += @('-SubscriptionId', $SubscriptionId)
}
if ($DeployerObjectId) {
    $preflightArgs += @('-DeployerObjectId', $DeployerObjectId)
}
if ($PreflightSnapshotPath) {
    $preflightArgs += @('-SnapshotPath', $PreflightSnapshotPath)
}
$preflight = & pwsh @preflightArgs
if ($LASTEXITCODE -ne 0) {
    throw "Preflight failed; provisioning was not started.`n$($preflight -join [Environment]::NewLine)"
}
$preflight | Write-Host

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
    # The CLI default can change between runs, so a recorded environment wins over it.
    if (Test-Path -LiteralPath $environmentFile) {
        $SubscriptionId = (Get-Content -LiteralPath $environmentFile -Raw | ConvertFrom-Json).subscriptionId
    }
    else {
        $SubscriptionId = Invoke-Az @('account', 'show', '--query', 'id', '-o', 'tsv') 'No subscription selected. Run az login or pass -SubscriptionId.'
    }
}

$account = Invoke-Az @('account', 'show', '--subscription', $SubscriptionId, '-o', 'json') 'Could not read the requested subscription' | ConvertFrom-Json
$deployerObjectId = $DeployerObjectId
if (-not $deployerObjectId) {
    $deployerObjectId = Invoke-Az @('ad', 'signed-in-user', 'show', '--query', 'id', '-o', 'tsv') 'Could not resolve the signed-in principal. Pass -DeployerObjectId when Microsoft Graph is unavailable.'
}
$expiresOn = (Get-Date).AddDays($ExpiresInDays).ToString('yyyy-MM-dd')
$deploymentName = "genomics-$EnvironmentName-$(Get-Date -Format 'yyyyMMddHHmmss')"

New-Item -ItemType Directory -Force -Path (Join-Path $repositoryRoot '.azure') | Out-Null

# Azure rejects a public-key change on an existing VM, so a re-run must present the key the VM
# already carries. Generating one here would otherwise break idempotency whenever the untracked
# local key is absent.
$existingGroupName = "rg-genomics-$EnvironmentName"
$adminPublicKey = & az vm show --resource-group $existingGroupName --name "vm-genomics-$EnvironmentName" `
    --subscription $SubscriptionId `
    --query 'osProfile.linuxConfiguration.ssh.publicKeys[0].keyData' -o tsv 2>$null
if ($LASTEXITCODE -ne 0) { $adminPublicKey = $null }
if ($adminPublicKey) {
    Write-Host 'Reusing the provisioning key already recorded on the verification client.'
}
else {
    if (-not (Test-Path -LiteralPath $keyPath)) {
        # Linux provisioning requires a key even though verification runs through run-command.
        & ssh-keygen -t ed25519 -N '""' -C "genomics-$EnvironmentName" -f $keyPath -q
        if ($LASTEXITCODE -ne 0) { throw 'Could not generate the client provisioning key.' }
    }
    $adminPublicKey = (Get-Content -LiteralPath "$keyPath.pub" -Raw).Trim()
}

$storageActionsStateFile = Join-Path $repositoryRoot '.azure/storage-actions.local.json'
$storageActionsTierBeforeDateUtc = ''
$storageActionsVerificationRunStartUtc = ''
if ($DeployStorageActions) {
    # Storage Actions conditions compare against a fixed instant, not a relative "N days ago"
    # expression. Recomputing that instant on every deploy would make an unchanged environment
    # report a change on every re-run, breaking the idempotency guarantee task 11.4 verifies. The
    # first run computes and freezes both instants; later runs reuse them from local state.
    if (Test-Path -LiteralPath $storageActionsStateFile) {
        $existingState = Get-Content -LiteralPath $storageActionsStateFile -Raw | ConvertFrom-Json
        $storageActionsTierBeforeDateUtc = $existingState.tierBeforeDateUtc
        $storageActionsVerificationRunStartUtc = $existingState.verificationRunStartUtc
        Write-Host "Reusing frozen Storage Actions thresholds from $storageActionsStateFile."
    }
    else {
        $nowUtc = (Get-Date).ToUniversalTime()
        $storageActionsTierBeforeDateUtc = $nowUtc.AddDays(-$StorageActionsTierAfterDays).ToString('yyyy-MM-ddTHH:mm:ssZ')
        $storageActionsVerificationRunStartUtc = $nowUtc.AddMinutes(15).ToString('yyyy-MM-ddTHH:mm:ssZ')
        [ordered]@{
            tierBeforeDateUtc       = $storageActionsTierBeforeDateUtc
            verificationRunStartUtc = $storageActionsVerificationRunStartUtc
            computedAtUtc           = $nowUtc.ToString('yyyy-MM-ddTHH:mm:ssZ')
            tierAfterDays           = $StorageActionsTierAfterDays
        } | ConvertTo-Json | Set-Content -LiteralPath $storageActionsStateFile -Encoding utf8
        Write-Host "Computed and froze Storage Actions thresholds in $storageActionsStateFile."
    }
}

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
    "deployStorageActions=$($DeployStorageActions.ToString().ToLowerInvariant())"
    "storageActionsTierBeforeDateUtc=$storageActionsTierBeforeDateUtc"
    "storageActionsVerificationRunStartUtc=$storageActionsVerificationRunStartUtc"
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

# Report the pending change set before deploying, so a re-run against a complete environment can
# state that nothing changes rather than leaving the operator to infer it from a silent success.
$pending = Invoke-Az (
    @('deployment', 'sub', 'what-if', '--no-pretty-print', '-o', 'json') + $common
) 'What-if analysis failed' | ConvertFrom-Json
$changeCounts = @{}
foreach ($change in $pending.changes) {
    $changeCounts[$change.changeType] = 1 + ($changeCounts[$change.changeType] ?? 0)
}
$changed = @($pending.changes | Where-Object changeType -notin @('NoChange', 'Ignore'))
$changeSummary = (
    $changeCounts.GetEnumerator() | Sort-Object Key | ForEach-Object { "$($_.Key)=$($_.Value)" }
) -join ', '
if ($changed.Count -eq 0) {
    Write-Host "Pending changes: none ($changeSummary). The environment is already complete."
}
else {
    Write-Host "Pending changes: $($changed.Count) ($changeSummary)."
    $changed | ForEach-Object { Write-Host "  $($_.changeType) $($_.resourceId)" }
}

$deploymentStarted = Get-Date
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
$startedVerificationClient = $false

# The client is deallocated between runs to avoid idle compute charges.
$power = Invoke-Az @(
    'vm', 'get-instance-view', '-g', $resourceGroupName, '-n', $clientName,
    '--subscription', $SubscriptionId, '--query',
    'instanceView.statuses[?starts_with(code, ''PowerState'')].displayStatus', '-o', 'tsv'
) 'Could not read the client power state'
if ($power -notmatch 'running') {
    Write-Host "  starting $clientName"
    Invoke-Az @('vm', 'start', '-g', $resourceGroupName, '-n', $clientName,
        '--subscription', $SubscriptionId, '-o', 'none') 'Could not start the client'
    $startedVerificationClient = $true
}

try {
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

    # Data Factory raises its managed private endpoints as pending connections on each account.
    Write-Host 'Approving managed private endpoint connections.'
    foreach ($accountName in @($outputs.landingStorageAccount.value, $lakeAccount)) {
        $accountId = "/subscriptions/$SubscriptionId/resourceGroups/$resourceGroupName/providers/Microsoft.Storage/storageAccounts/$accountName"
        $connections = Invoke-Az @(
            'network', 'private-endpoint-connection', 'list', '--id', $accountId, '-o', 'json'
        ) 'Could not list private endpoint connections' | ConvertFrom-Json
        foreach ($connection in $connections) {
            if ($connection.properties.privateLinkServiceConnectionState.status -eq 'Pending') {
                Invoke-Az @(
                    'network', 'private-endpoint-connection', 'approve'
                    '--id', $connection.id
                    '--description', 'Approved by Deploy-Accelerator'
                    '-o', 'none'
                ) "Could not approve $($connection.name)"
                Write-Host "  approved $($connection.name)"
            }
        }
    }
}
finally {
    if ($startedVerificationClient) {
        Write-Host "  deallocating $clientName to avoid idle compute charges"
        Invoke-Az @('vm', 'deallocate', '-g', $resourceGroupName, '-n', $clientName,
            '--subscription', $SubscriptionId, '-o', 'none') 'Could not deallocate the verification client'
    }
}

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
    referenceContainer = $outputs.referenceContainer.value
    verificationVm    = $clientName
    stagingFactory    = $outputs.stagingFactoryName.value
    stagingPipeline   = $outputs.stagingPipelineName.value
    taxonomy          = $taxonomy
    storageActionsTask       = $outputs.storageActionsTaskName.value
    storageActionsAssignment = $outputs.storageActionsAssignmentName.value
    identities        = [ordered]@{
        ingestion = $outputs.ingestionIdentityClientId.value
        staging   = $outputs.stagingIdentityClientId.value
        pipeline  = $outputs.pipelineIdentityClientId.value
    }
}

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $environmentFile) | Out-Null
$environment | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $environmentFile -Encoding utf8

$elapsed = (Get-Date) - $deploymentStarted
Write-Host ("Deployed in {0:mm\:ss} (provisioning plus in-network taxonomy creation)." -f $elapsed)
Write-Host "Deployed. Environment recorded in $environmentFile (untracked)."
Write-Host "Tear down with: ./scripts/Remove-Accelerator.ps1 -EnvironmentName $EnvironmentName"
