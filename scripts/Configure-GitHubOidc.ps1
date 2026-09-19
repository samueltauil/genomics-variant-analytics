#Requires -Version 7.2
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[0-9a-fA-F-]{36}$')]
    [string] $SubscriptionId,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string] $ResourceGroupName,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string] $IdentityName,

    [Parameter(Mandatory)]
    [ValidatePattern('^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')]
    [string] $Repository,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string] $ContainerRegistryName
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Az {
    param([string[]] $Arguments, [string] $Failure)
    $output = & az @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "$Failure`n$($output -join [Environment]::NewLine)"
    }
    return $output
}

function Invoke-Gh {
    param([string[]] $Arguments, [string] $Failure)
    $output = & gh @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "$Failure`n$($output -join [Environment]::NewLine)"
    }
    return $output
}

function Invoke-GhInput {
    param([string] $Content, [string[]] $Arguments, [string] $Failure)
    $output = $Content | & gh @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "$Failure`n$($output -join [Environment]::NewLine)"
    }
    return $output
}

$identity = Invoke-Az @(
    'identity', 'show',
    '--subscription', $SubscriptionId,
    '--resource-group', $ResourceGroupName,
    '--name', $IdentityName,
    '-o', 'json'
) 'Could not read the managed identity.' | ConvertFrom-Json

$account = Invoke-Az @(
    'account', 'show', '--subscription', $SubscriptionId, '-o', 'json'
) 'Could not read the Azure subscription.' | ConvertFrom-Json

$registry = Invoke-Az @(
    'acr', 'show',
    '--subscription', $SubscriptionId,
    '--resource-group', $ResourceGroupName,
    '--name', $ContainerRegistryName,
    '-o', 'json'
) 'Could not read the container registry.' | ConvertFrom-Json

$oidcCustomization = Invoke-Gh @(
    'api',
    '-H', 'Accept: application/vnd.github+json',
    "repos/$Repository/actions/oidc/customization/sub"
) 'Could not read the repository OIDC subject configuration.' | ConvertFrom-Json

$repositorySubject = "repo:$Repository"
if (
    $oidcCustomization.use_immutable_subject -eq $true -and
    -not [string]::IsNullOrWhiteSpace([string]$oidcCustomization.sub_claim_prefix)
) {
    $repositorySubject = [string]$oidcCustomization.sub_claim_prefix
}

$subjects = [ordered]@{
    'github-release-build' = "${repositorySubject}:environment:release-build"
    'github-clinical'      = "${repositorySubject}:environment:clinical"
    'github-research'      = "${repositorySubject}:environment:research"
}

foreach ($entry in $subjects.GetEnumerator()) {
    $existingJson = & az identity federated-credential show `
        --subscription $SubscriptionId `
        --resource-group $ResourceGroupName `
        --identity-name $IdentityName `
        --name $entry.Key `
        -o json 2>$null
    if ($LASTEXITCODE -eq 0) {
        $existing = $existingJson | ConvertFrom-Json
        if ([string]$existing.subject -eq $entry.Value) {
            Write-Host "Federated credential $($entry.Key) already matches the GitHub subject."
            continue
        }
        if ($PSCmdlet.ShouldProcess(
            $IdentityName,
            "update $($entry.Key) subject to $($entry.Value)"
        )) {
            Invoke-Az @(
                'identity', 'federated-credential', 'update',
                '--subscription', $SubscriptionId,
                '--resource-group', $ResourceGroupName,
                '--identity-name', $IdentityName,
                '--name', $entry.Key,
                '--issuer', 'https://token.actions.githubusercontent.com',
                '--subject', $entry.Value,
                '--audiences', 'api://AzureADTokenExchange',
                '-o', 'none'
            ) "Could not update federated credential $($entry.Key)." | Out-Null
        }
        continue
    }
    if ($PSCmdlet.ShouldProcess($IdentityName, "create $($entry.Key) for $($entry.Value)")) {
        Invoke-Az @(
            'identity', 'federated-credential', 'create',
            '--subscription', $SubscriptionId,
            '--resource-group', $ResourceGroupName,
            '--identity-name', $IdentityName,
            '--name', $entry.Key,
            '--issuer', 'https://token.actions.githubusercontent.com',
            '--subject', $entry.Value,
            '--audiences', 'api://AzureADTokenExchange',
            '-o', 'none'
        ) "Could not create federated credential $($entry.Key)." | Out-Null
    }
}

$environmentPayload = @{
    wait_timer = 0
    can_admins_bypass = $true
    deployment_branch_policy = @{
        protected_branches = $false
        custom_branch_policies = $true
    }
} | ConvertTo-Json -Depth 4 -Compress

if ($PSCmdlet.ShouldProcess($Repository, 'configure the release-build environment')) {
    Invoke-GhInput $environmentPayload @(
        'api', '--method', 'PUT',
        '-H', 'Accept: application/vnd.github+json',
        "repos/$Repository/environments/release-build",
        '--input', '-'
    ) 'Could not configure the release-build environment.' | Out-Null

    $policies = Invoke-Gh @(
        'api', "repos/$Repository/environments/release-build/deployment-branch-policies"
    ) 'Could not list release-build deployment policies.' | ConvertFrom-Json
    if (-not ($policies.branch_policies | Where-Object {
        $_.name -eq 'v*' -and $_.type -eq 'tag'
    })) {
        Invoke-GhInput '{"name":"v*","type":"tag"}' @(
            'api', '--method', 'POST',
            '-H', 'Accept: application/vnd.github+json',
            "repos/$Repository/environments/release-build/deployment-branch-policies",
            '--input', '-'
        ) 'Could not restrict release-build to release tags.' | Out-Null
    }
}

$variables = [ordered]@{
    AZURE_CLIENT_ID       = [string]$identity.clientId
    AZURE_TENANT_ID       = [string]$account.tenantId
    AZURE_SUBSCRIPTION_ID = $SubscriptionId
    AZURE_RESOURCE_GROUP  = $ResourceGroupName
    ACR_NAME              = [string]$registry.name
    ACR_LOGIN_SERVER      = [string]$registry.loginServer
}
foreach ($entry in $variables.GetEnumerator()) {
    if ($PSCmdlet.ShouldProcess($Repository, "set repository variable $($entry.Key)")) {
        Invoke-Gh @(
            'variable', 'set', $entry.Key,
            '--repo', $Repository,
            '--body', $entry.Value
        ) "Could not set repository variable $($entry.Key)." | Out-Null
    }
}

$secretNames = Invoke-Gh @(
    'secret', 'list', '--repo', $Repository, '--json', 'name'
) 'Could not enumerate repository secrets.' | ConvertFrom-Json
$azureCredentialNames = @(
    $secretNames | Where-Object {
        $_.name -match '(?i)(azure|storage|connection|client).*(secret|key|string)'
    }
)
if ($azureCredentialNames.Count -ne 0) {
    throw "Azure credential-shaped repository secrets remain configured: $($azureCredentialNames.name -join ', ')"
}

[ordered]@{
    repository = $Repository
    identity = $IdentityName
    clientId = $identity.clientId
    environments = @($subjects.Values)
    registry = $registry.loginServer
    repositoryVariables = @($variables.Keys)
    azureCredentialSecrets = @()
} | ConvertTo-Json -Depth 4
