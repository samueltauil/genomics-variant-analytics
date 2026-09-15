#Requires -Version 7.2
<#
.SYNOPSIS
    Removes the disposable Azure environment created by Deploy-Accelerator.ps1.
.DESCRIPTION
    Deletes only a resource group carrying this accelerator's project tag, so an unrelated
    resource group cannot be removed by mistake. Reports resources that survive deletion,
    such as soft-deleted accounts, rather than claiming the subscription is clean.
#>
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [ValidatePattern('^[a-z0-9]{2,10}$')]
    [string] $EnvironmentName = 'demo',

    [ValidateNotNullOrEmpty()]
    [string] $SubscriptionId
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$expectedProjectTag = 'genomics-variant-accelerator'
$resourceGroupName = "rg-genomics-$EnvironmentName"

function Invoke-Az {
    param([Parameter(Mandatory)][string[]] $Arguments, [string] $ErrorMessage = 'Azure CLI call failed')

    $output = & az @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$ErrorMessage`n$output"
    }
    return $output
}

if (-not $SubscriptionId) {
    # Deleting against whatever the CLI default happens to be is not acceptable.
    $recorded = Join-Path (Split-Path -Parent $PSScriptRoot) '.azure/environment.env.json'
    if (Test-Path -LiteralPath $recorded) {
        $SubscriptionId = (Get-Content -LiteralPath $recorded -Raw | ConvertFrom-Json).subscriptionId
    }
    else {
        $SubscriptionId = Invoke-Az @('account', 'show', '--query', 'id', '-o', 'tsv') 'No subscription selected.'
    }
}

$group = Invoke-Az @(
    'group', 'show', '--name', $resourceGroupName, '--subscription', $SubscriptionId, '-o', 'json'
) "Resource group $resourceGroupName does not exist." | ConvertFrom-Json

$projectTag = $group.tags.project
if ($projectTag -ne $expectedProjectTag) {
    throw "Refusing to delete ${resourceGroupName}: project tag is '$projectTag', expected '$expectedProjectTag'."
}

$resources = Invoke-Az @(
    'resource', 'list', '--resource-group', $resourceGroupName, '--subscription', $SubscriptionId,
    '--query', '[].{name:name,type:type}', '-o', 'json'
) 'Could not list resources' | ConvertFrom-Json

Write-Host "Resource group : $resourceGroupName"
Write-Host "Resources      : $($resources.Count)"
$resources | Format-Table -AutoSize | Out-String | Write-Host

if (-not $PSCmdlet.ShouldProcess($resourceGroupName, 'delete resource group and every resource in it')) {
    Write-Host 'No changes made.'
    return
}

# An active container immutability policy blocks container and account deletion, so unlocked
# policies are removed first. A locked policy cannot be removed and will stop this deletion.
foreach ($account in @($resources | Where-Object type -eq 'Microsoft.Storage/storageAccounts')) {
    $accountPath = "/subscriptions/$SubscriptionId/resourceGroups/$resourceGroupName" +
                   "/providers/Microsoft.Storage/storageAccounts/$($account.name)"
    $containers = Invoke-Az @(
        'rest', '--method', 'get'
        '--url', "https://management.azure.com$accountPath/blobServices/default/containers?api-version=2025-01-01"
        '-o', 'json'
    ) 'Could not list containers' | ConvertFrom-Json

    foreach ($container in $containers.value) {
        $policy = $container.properties.immutabilityPolicy
        if (-not $policy) { continue }
        if ($policy.properties.state -eq 'Locked') {
            throw "Container $($container.name) has a locked immutability policy; it cannot be deleted until retention expires."
        }
        Invoke-Az @(
            'rest', '--method', 'delete'
            '--url', "https://management.azure.com$accountPath/blobServices/default/containers/$($container.name)/immutabilityPolicies/default?api-version=2025-01-01"
            '--headers', "If-Match=$($policy.etag)"
            '-o', 'none'
        ) "Could not remove the immutability policy on $($container.name)"
        Write-Host "  removed immutability policy on $($container.name)"
    }
}

Invoke-Az @('group', 'delete', '--name', $resourceGroupName, '--subscription', $SubscriptionId, '--yes') 'Deletion failed'

$remaining = & az group exists --name $resourceGroupName --subscription $SubscriptionId
if ($remaining -eq 'true') {
    throw "Resource group $resourceGroupName still exists after deletion."
}

Write-Host "Deleted $resourceGroupName."
Write-Host 'Storage accounts remain recoverable during their soft-delete window; blob soft delete retains data for 7 days.'
