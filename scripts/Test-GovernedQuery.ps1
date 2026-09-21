#Requires -Version 7.2
[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string] $EnvironmentFile = (Join-Path (Split-Path -Parent $PSScriptRoot) '.azure/environment.env.json'),

    [ValidateRange(1, 65535)]
    [int] $ServicePort = 8080,

    [ValidateNotNullOrEmpty()]
    [string] $ArtifactPath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'openspec\changes\add-genomics-variant-accelerator\evidence\private-query-live-2026-09-21.json'),

    [ValidateNotNullOrEmpty()]
    [string] $ReferenceVersionOrDigest = 'manifest-sha256:synthetic-reference-001'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Az {
    param([Parameter(Mandatory)][string[]] $Arguments, [string] $ErrorMessage = 'Azure CLI call failed')

    $output = & az @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$ErrorMessage`n$output"
    }
    return $output
}

if (-not (Test-Path -LiteralPath $EnvironmentFile)) {
    throw "Environment file not found: $EnvironmentFile"
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$environment = Get-Content -LiteralPath $EnvironmentFile -Raw | ConvertFrom-Json
$remoteTemplatePath = Join-Path $repositoryRoot 'scripts\templates\governed-query-live.sh.template'
$variantFixturePath = Join-Path $repositoryRoot 'tests\fixtures\governed-query\synthetic-variants.csv'
$manifestFixturePath = Join-Path $repositoryRoot 'tests\fixtures\governed-query\synthetic-dataset-manifest.json'
$generatedScriptPath = Join-Path $repositoryRoot '.azure\governed-query-live.generated.sh'
$datasetRelativePath = 'SampleData/Genomics/private-query/task-8-7/synthetic-governed-variants.csv'
$manifestRelativePath = 'SampleData/Genomics/private-query/task-8-7/synthetic-governed-query-manifest.json'

$variantDataBase64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($variantFixturePath))
$manifestDataBase64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($manifestFixturePath))

$vmView = Invoke-Az @(
    'vm', 'show', '-g', $environment.resourceGroupName, '-n', $environment.verificationVm,
    '--subscription', $environment.subscriptionId,
    '--show-details',
    '-o', 'json'
) 'Could not read the verification VM details' | ConvertFrom-Json

$startedVm = $false
if ($vmView.powerState -ne 'VM running') {
    Invoke-Az @(
        'vm', 'start', '-g', $environment.resourceGroupName, '-n', $environment.verificationVm,
        '--subscription', $environment.subscriptionId, '-o', 'none'
    ) 'Could not start the verification VM'
    $startedVm = $true
    $vmView = Invoke-Az @(
        'vm', 'show', '-g', $environment.resourceGroupName, '-n', $environment.verificationVm,
        '--subscription', $environment.subscriptionId,
        '--show-details',
        '-o', 'json'
    ) 'Could not refresh the verification VM details' | ConvertFrom-Json
}

$privateIp = $vmView.privateIps
if (-not $privateIp) {
    throw 'The verification VM does not report a private IP address.'
}

$serviceBaseUrl = "http://$privateIp`:$ServicePort"
$localServiceUrl = "http://127.0.0.1:$ServicePort"
$response = $null

try {
    $scriptText = Get-Content -LiteralPath $remoteTemplatePath -Raw
    $replacements = [ordered]@{
        '__VM_USERNAME__' = 'genomicsops'
        '__VARIANT_DATA_BASE64__' = $variantDataBase64
        '__MANIFEST_DATA_BASE64__' = $manifestDataBase64
        '__STAGING_CLIENT_ID__' = $environment.identities.staging
        '__LAKE_ACCOUNT__' = $environment.lakeAccount
        '__LAKE_FILESYSTEM__' = $environment.lakeFilesystem
        '__DATASET_RELATIVE_PATH__' = $datasetRelativePath
        '__MANIFEST_RELATIVE_PATH__' = $manifestRelativePath
        '__LOCAL_SERVICE_URL__' = $localServiceUrl
        '__REFERENCE_VERSION_OR_DIGEST__' = $ReferenceVersionOrDigest
    }

    foreach ($entry in $replacements.GetEnumerator()) {
        $scriptText = $scriptText.Replace($entry.Key, $entry.Value)
    }

    [IO.File]::WriteAllText($generatedScriptPath, $scriptText.Replace("`r`n", "`n"))

    $response = Invoke-Az @(
        'vm', 'run-command', 'invoke'
        '--name', $environment.verificationVm
        '--resource-group', $environment.resourceGroupName
        '--subscription', $environment.subscriptionId
        '--command-id', 'RunShellScript'
        '--scripts', "@$generatedScriptPath"
        '-o', 'json'
    ) 'Governed query verification failed' | ConvertFrom-Json
}
finally {
    Remove-Item -LiteralPath $generatedScriptPath -Force -ErrorAction SilentlyContinue
    if ($startedVm -and -not $response) {
        Invoke-Az @(
            'vm', 'deallocate', '-g', $environment.resourceGroupName, '-n', $environment.verificationVm,
            '--subscription', $environment.subscriptionId, '-o', 'none'
        ) 'Could not deallocate the verification VM'
    }
}

$message = $response.value[0].message
$startMarker = 'BEGIN_GOVERNED_QUERY_RESULT'
$endMarker = 'END_GOVERNED_QUERY_RESULT'
$startIndex = $message.IndexOf($startMarker)
$endIndex = $message.IndexOf($endMarker)
if ($startIndex -lt 0 -or $endIndex -lt 0 -or $endIndex -le $startIndex) {
    throw "Governed query result markers were not found.`n$message"
}

$jsonText = $message.Substring($startIndex + $startMarker.Length, $endIndex - ($startIndex + $startMarker.Length)).Trim()
$artifact = $jsonText | ConvertFrom-Json

$outsideNetworkStatus = 'not-run'
$outsideNetworkDetail = ''
try {
    Invoke-WebRequest -Uri "$serviceBaseUrl/health" -TimeoutSec 15 -UseBasicParsing | Out-Null
    $outsideNetworkStatus = 'unexpected-success'
    $outsideNetworkDetail = 'The governed query service responded from outside the VNet.'
}
catch {
    $outsideNetworkStatus = 'refused'
    $outsideNetworkDetail = $_.Exception.Message
}

$artifact | Add-Member -NotePropertyName verification_vm -NotePropertyValue $environment.verificationVm
$artifact | Add-Member -NotePropertyName verification_vm_resource_id -NotePropertyValue $vmView.id
$artifact | Add-Member -NotePropertyName verification_vm_private_ip -NotePropertyValue $privateIp
$artifact | Add-Member -NotePropertyName run_command_resource_id -NotePropertyValue "/subscriptions/$($environment.subscriptionId)/resourceGroups/$($environment.resourceGroupName)/providers/Microsoft.Compute/virtualMachines/$($environment.verificationVm)/runCommands/install-governed-query-service"
$artifact | Add-Member -NotePropertyName resource_group -NotePropertyValue $environment.resourceGroupName
$artifact | Add-Member -NotePropertyName lake_account -NotePropertyValue $environment.lakeAccount
$artifact | Add-Member -NotePropertyName outside_network_status -NotePropertyValue $outsideNetworkStatus
$artifact | Add-Member -NotePropertyName outside_network_detail -NotePropertyValue $outsideNetworkDetail

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ArtifactPath) | Out-Null
$artifact | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ArtifactPath -Encoding utf8

if ($startedVm) {
    Invoke-Az @(
        'vm', 'deallocate', '-g', $environment.resourceGroupName, '-n', $environment.verificationVm,
        '--subscription', $environment.subscriptionId, '-o', 'none'
    ) 'Could not deallocate the verification VM'
}

$artifact | ConvertTo-Json -Depth 6
