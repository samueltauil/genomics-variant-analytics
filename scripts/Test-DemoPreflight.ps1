#Requires -Version 7.2
<#
.SYNOPSIS
    Checks local delivery prerequisites and, when requested, Azure prerequisites.
.DESCRIPTION
    Local checks never contact Azure. -RequireAzureChecks enables the checks that
    must pass before Deploy-Accelerator.ps1 can create resources. A successful
    local-only report is not evidence of subscription, role, quota, or regional
    availability.
#>
[CmdletBinding()]
param(
    [ValidatePattern('^[a-z0-9]{2,10}$')]
    [string] $EnvironmentName = 'demo',

    [ValidateNotNullOrEmpty()]
    [string] $Location = 'eastus2',

    [ValidateRange(32, 262144)]
    [int] $ShareQuotaGiB = 128,

    [ValidateRange(3000, 102400)]
    [int] $ShareIops = 3000,

    [ValidateRange(125, 10340)]
    [int] $ShareBandwidthMibps = 200,

    [ValidateNotNullOrEmpty()]
    [string] $SubscriptionId,

    [ValidatePattern('^[0-9a-fA-F-]{36}$')]
    [string] $DeployerObjectId,

    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string] $SnapshotPath,

    [switch] $RequireAzureChecks
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$checks = [System.Collections.Generic.List[object]]::new()
$requiredComponents = @(
    'Azure Files SMB',
    'ADLS Gen2',
    'Data Factory Copy',
    'managed identities',
    'private endpoints',
    'Azure Batch or HPC',
    'Delta-capable analytics engine'
)

function Add-Check {
    param(
        [Parameter(Mandatory)][string] $Name,
        [Parameter(Mandatory)][ValidateSet('PASS', 'FAIL', 'UNVERIFIED')][string] $Status,
        [Parameter(Mandatory)][string] $Found,
        [Parameter(Mandatory)][string] $Required
    )
    $checks.Add([pscustomobject]@{
        Name     = $Name
        Status   = $Status
        Found    = $Found
        Required = $Required
    })
}

function Get-CommandVersion {
    param([Parameter(Mandatory)][string] $CommandName, [string] $Arguments = '--version')
    $command = Get-Command $CommandName -ErrorAction SilentlyContinue
    if (-not $command) {
        return $null
    }
    try {
        return (& $command.Source $Arguments 2>&1 | Select-Object -First 1).ToString()
    }
    catch {
        return $null
    }
}

function Invoke-AzJson {
    param([Parameter(Mandatory)][string[]] $Arguments)
    $output = & az @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ($output -join [Environment]::NewLine)
    }
    return ($output -join [Environment]::NewLine) | ConvertFrom-Json
}

function Compare-Version {
    param([string] $Found, [version] $Required)
    if (-not $Found -or $Found -notmatch '(?<major>\d+)\.(?<minor>\d+)') {
        return $false
    }
    return ([version]"$($Matches.major).$($Matches.minor)") -ge $Required
}

function Get-PropertyPath {
    # Strict mode turns a missing property into a terminating error, so walk the path defensively.
    param([Parameter(Mandatory)] $InputObject, [Parameter(Mandatory)][string[]] $Path)
    $current = $InputObject
    foreach ($name in $Path) {
        if ($null -eq $current -or $current.PSObject.Properties.Name -notcontains $name) {
            return $null
        }
        $current = $current.$name
    }
    return $current
}

function Add-ToolCheck {
    param(
        [Parameter(Mandatory)][string] $Name,
        [Parameter(Mandatory)][version] $Required,
        [string] $Override
    )
    $found = if ($Override) { $Override } else { Get-CommandVersion $Name }
    $status = if (Compare-Version $found $Required) { 'PASS' } else { 'FAIL' }
    Add-Check "tool:$Name" $status `
        $(if ($found) { $found.Trim() } else { 'not found' }) ">= $Required"
}

$minimumPowerShell = [version]'7.2'
$powerShellFound = $PSVersionTable.PSVersion
Add-Check 'powershell' $(if ($powerShellFound -ge $minimumPowerShell) { 'PASS' } else { 'FAIL' }) `
    $powerShellFound ">= $minimumPowerShell"

$pythonVersion = Get-CommandVersion 'python'
if ($pythonVersion -and $pythonVersion -match '(?<major>\d+)\.(?<minor>\d+)') {
    $pythonFound = [version]"$($Matches.major).$($Matches.minor)"
    Add-Check 'python' $(if ($pythonFound -ge [version]'3.10') { 'PASS' } else { 'FAIL' }) `
        $pythonVersion.Trim() '>= 3.10'
}
else {
    Add-Check 'python' 'FAIL' 'not found' '>= 3.10'
}

$gitVersion = Get-CommandVersion 'git'
Add-Check 'git' $(if ($gitVersion) { 'PASS' } else { 'FAIL' }) `
    $(if ($gitVersion) { $gitVersion.Trim() } else { 'not found' }) 'installed'

foreach ($path in @(
        'infra/main.bicep',
        'infra/main.bicepparam',
        'scripts/Deploy-Accelerator.ps1',
        'scripts/Remove-Accelerator.ps1',
        'docs/demo-runbook.md',
        'docs/claim-register.md'
    )) {
    $fullPath = Join-Path $repositoryRoot $path
    Add-Check "repository-file:$path" $(if (Test-Path -LiteralPath $fullPath -PathType Leaf) { 'PASS' } else { 'FAIL' }) `
        $(if (Test-Path -LiteralPath $fullPath -PathType Leaf) { 'present' } else { 'missing' }) 'present'
}

Add-Check 'environment-parameters' 'PASS' `
    "name=$EnvironmentName, location=$Location, share=${ShareQuotaGiB}GiB/${ShareIops}IOPS/${ShareBandwidthMibps}MiB/s" `
    'declared inputs satisfy script ranges'

if ($SnapshotPath) {
    $snapshot = Get-Content -LiteralPath $SnapshotPath -Raw | ConvertFrom-Json
    $subscription = $snapshot.subscription
    $subscriptionType = if ($subscription.type) { $subscription.type } else { 'not supplied' }
    $subscriptionState = if ($subscription.state) { $subscription.state } else { 'not supplied' }
    Add-Check 'subscription-type' `
        $(if ($subscriptionState -eq 'Enabled' -and $subscriptionType -ne 'not supplied') { 'PASS' } else { 'FAIL' }) `
        "$subscriptionType ($subscriptionState)" 'enabled Azure subscription with supported billing agreement'

    $roleNames = @($snapshot.roles)
    $hasDeploymentRole = @('Owner', 'Contributor') | Where-Object { $_ -in $roleNames }
    $hasRoleAssignment = @('Owner', 'User Access Administrator') | Where-Object { $_ -in $roleNames }
    Add-Check 'deployer-roles' `
        $(if ($hasDeploymentRole -and $hasRoleAssignment) { 'PASS' } else { 'FAIL' }) `
        ($roleNames -join ', ') 'Owner or Contributor plus Owner or User Access Administrator'

    $compute = $snapshot.quotas.compute_vcpus
    $computeFound = if ($compute) { "$($compute.current)/$($compute.limit)" } else { 'not supplied' }
    Add-Check 'compute-quota' `
        $(if ($compute -and [int]$compute.limit -ge 4 -and [int]$compute.current -le ([int]$compute.limit - 4)) { 'PASS' } else { 'FAIL' }) `
        $computeFound 'at least 4 unused vCPUs for the verification client and selected compute'

    $storage = $snapshot.quotas.storage_gib
    $storageFound = if ($storage) { "$($storage.current)/$($storage.limit) GiB" } else { 'not supplied' }
    Add-Check 'storage-quota' `
        $(if ($storage -and [int]$storage.limit -ge ([int]$storage.current + $ShareQuotaGiB)) { 'PASS' } else { 'FAIL' }) `
        $storageFound "at least $ShareQuotaGiB GiB available for the selected share"

    $available = @($snapshot.regionalAvailability.$Location)
    foreach ($component in $requiredComponents) {
        Add-Check "regional-availability:$component" `
            $(if ($component -in $available) { 'PASS' } else { 'FAIL' }) `
            $(if ($available.Count) { $available -join ', ' } else { 'none reported' }) `
            "$component available in $Location"
    }

    $tooling = $snapshot.tooling
    Add-ToolCheck 'azure-cli' ([version]'2.50') $(if ($tooling) { $tooling.azureCli } else { $null })
    Add-ToolCheck 'bicep' ([version]'0.20') $(if ($tooling) { $tooling.bicep } else { $null })
}
elseif ($RequireAzureChecks) {
    $az = Get-Command az -ErrorAction SilentlyContinue
    if (-not $az) {
        Add-Check 'azure-cli' 'FAIL' 'not found' 'Azure CLI available and authenticated'
    }
    elseif (-not $SubscriptionId) {
        Add-Check 'subscription' 'FAIL' 'not supplied' 'explicit subscription id'
    }
    else {
        try {
            $account = Invoke-AzJson @('account', 'show', '--subscription', $SubscriptionId, '-o', 'json')
            Add-Check 'subscription' 'PASS' "$($account.id) ($($account.name))" $SubscriptionId
        }
        catch {
            Add-Check 'subscription' 'FAIL' $_.Exception.Message 'subscription is readable'
            $account = $null
        }

        # quotaId names the billing agreement, and `az account show` omits it. Read it straight
        # from ARM: `az account subscription show` needs a preview extension that cannot be
        # installed non-interactively. Not every principal can read it, so absence is unverified.
        $subscriptionType = $null
        try {
            $details = Invoke-AzJson @(
                'rest', '--method', 'get', '--url',
                "https://management.azure.com/subscriptions/$($SubscriptionId)?api-version=2022-12-01"
            )
            $subscriptionType = Get-PropertyPath $details @('subscriptionPolicies', 'quotaId')
        }
        catch {
            $subscriptionType = $null
        }
        $subscriptionState = if ($account) { $account.state } else { 'unknown' }
        if (-not $subscriptionType) {
            Add-Check 'subscription-type' 'UNVERIFIED' `
                "billing agreement not exposed to this principal ($subscriptionState)" `
                'enabled Azure subscription with supported billing agreement'
        }
        else {
            Add-Check 'subscription-type' `
                $(if ($subscriptionState -eq 'Enabled') { 'PASS' } else { 'FAIL' }) `
                "$subscriptionType ($subscriptionState)" `
                'enabled Azure subscription with supported billing agreement'
        }

        try {
            $providers = Invoke-AzJson @('provider', 'list', '--subscription', $SubscriptionId, '-o', 'json')
            $requiredProviders = @(
                'Microsoft.Authorization',
                'Microsoft.Compute',
                'Microsoft.DataFactory',
                'Microsoft.ManagedIdentity',
                'Microsoft.Network',
                'Microsoft.Storage'
            )
            $registered = @($providers | Where-Object registrationState -eq 'Registered' | Select-Object -ExpandProperty namespace)
            $missing = @($requiredProviders | Where-Object { $_ -notin $registered })
            Add-Check 'resource-providers' $(if ($missing.Count -eq 0) { 'PASS' } else { 'FAIL' }) `
                $(if ($missing.Count -eq 0) { 'all required providers registered' } else { "missing: $($missing -join ', ')" }) `
                ($requiredProviders -join ', ')
        }
        catch {
            Add-Check 'resource-providers' 'FAIL' $_.Exception.Message 'required providers registered'
        }

        if (-not $DeployerObjectId) {
            Add-Check 'deployer-roles' 'FAIL' 'not supplied' 'object id with deployment and role-assignment rights'
        }
        else {
            try {
                # --all is mutually exclusive with --scope; scope alone already includes
                # assignments inherited from the subscription's management groups.
                $assignments = Invoke-AzJson @(
                    'role', 'assignment', 'list', '--assignee-object-id', $DeployerObjectId,
                    '--scope', "/subscriptions/$SubscriptionId",
                    '--include-inherited', '--fill-principal-name', 'false',
                    '--subscription', $SubscriptionId, '-o', 'json'
                )
                $roleNames = @($assignments | Select-Object -ExpandProperty roleDefinitionName -Unique)
                $hasDeploymentRole = @('Owner', 'Contributor') | Where-Object { $_ -in $roleNames }
                $hasRoleAssignment = @('Owner', 'User Access Administrator') | Where-Object { $_ -in $roleNames }
                $roleStatus = if ($hasDeploymentRole -and $hasRoleAssignment) { 'PASS' } else { 'FAIL' }
                Add-Check 'deployer-roles' $roleStatus ($roleNames -join ', ') `
                    'Owner or Contributor plus Owner or User Access Administrator'
            }
            catch {
                Add-Check 'deployer-roles' 'FAIL' $_.Exception.Message 'deployment and role-assignment rights'
            }
        }

        try {
            $usage = Invoke-AzJson @('vm', 'list-usage', '--location', $Location, '--subscription', $SubscriptionId, '-o', 'json')
            $vcpus = @($usage | Where-Object {
                $_.name.value -match '^(standard|standardDSv|standardDasv).*vcpus$' -or
                $_.name.localizedValue -match 'vCPUs'
            } | Select-Object -First 1)
            if ($vcpus) {
                $availableVcpus = [int]$vcpus.limit - [int]$vcpus.currentValue
                Add-Check 'compute-quota' $(if ($availableVcpus -ge 4) { 'PASS' } else { 'FAIL' }) `
                    "$($vcpus.currentValue)/$($vcpus.limit) reported" `
                    'at least 4 unused vCPUs for the verification client and selected compute'
            }
            else {
                Add-Check 'compute-quota' 'FAIL' 'usage API returned no matching family' `
                    'at least 4 unused vCPUs for the verification client and selected compute'
            }
        }
        catch {
            Add-Check 'compute-quota' 'FAIL' $_.Exception.Message `
                'at least 4 unused vCPUs for the verification client and selected compute'
        }

        foreach ($component in $requiredComponents) {
            Add-Check "regional-availability:$component" 'UNVERIFIED' $Location `
                "$component availability in $Location"
        }
        Add-Check 'storage-quota' 'UNVERIFIED' "$ShareQuotaGiB GiB requested" `
            "at least $ShareQuotaGiB GiB available for the selected share"
    }
}
else {
    Add-Check 'azure-subscription' 'UNVERIFIED' 'not queried' 'subscription type, roles, quota, and region'
    foreach ($component in $requiredComponents) {
        Add-Check "regional-availability:$component" 'UNVERIFIED' $Location `
            "$component availability in $Location"
    }
    Add-Check 'storage-quota' 'UNVERIFIED' "$ShareQuotaGiB GiB requested" `
        "at least $ShareQuotaGiB GiB available for the selected share"
}

$blocking = @($checks | Where-Object Status -eq 'FAIL')
$unverified = @($checks | Where-Object Status -eq 'UNVERIFIED')
$ready = $blocking.Count -eq 0 -and (($RequireAzureChecks -or $SnapshotPath) -or $unverified.Count -eq 0)
$report = [pscustomobject]@{
    Mode = if ($SnapshotPath) { 'snapshot-preflight' } elseif ($RequireAzureChecks) { 'azure-preflight' } else { 'local-preflight' }
    GeneratedOn = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    EnvironmentName = $EnvironmentName
    Location = $Location
    Ready = $ready
    Checks = $checks
    BlockingFailures = $blocking.Count
    UnverifiedChecks = $unverified.Count
}
$report | ConvertTo-Json -Depth 5
if (-not $ready) {
    exit 1
}
