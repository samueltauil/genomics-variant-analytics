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
    $SubscriptionId = Invoke-Az @('account', 'show', '--query', 'id', '-o', 'tsv') 'No subscription selected.'
}

$group = Invoke-Az @(
    'group', 'show', '--name', $resourceGroupName, '--subscription', $SubscriptionId, '-o', 'json'
) "Resource group $resourceGroupName does not exist." | ConvertFrom-Json

$projectTag = $group.tags.project
if ($projectTag -ne $expectedProjectTag) {
    throw "Refusing to delete $resourceGroupName: project tag is '$projectTag', expected '$expectedProjectTag'."
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

Invoke-Az @('group', 'delete', '--name', $resourceGroupName, '--subscription', $SubscriptionId, '--yes') 'Deletion failed'

$remaining = & az group exists --name $resourceGroupName --subscription $SubscriptionId
if ($remaining -eq 'true') {
    throw "Resource group $resourceGroupName still exists after deletion."
}

Write-Host "Deleted $resourceGroupName."
Write-Host 'Storage accounts remain recoverable during their soft-delete window; blob soft delete retains data for 7 days.'
