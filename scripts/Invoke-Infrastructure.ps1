#Requires -Version 7.2
[CmdletBinding()]
param(
    [ValidateSet('Validate')]
    [string] $Action = 'Validate',
    [string] $InventoryPath = (Join-Path $PSScriptRoot '../infra/asset-inventory.json')
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$schemaPath = Join-Path $PSScriptRoot '../infra/asset-inventory.schema.json'
$tasksPath = Join-Path $PSScriptRoot '../openspec/changes/add-genomics-variant-accelerator/tasks.md'
$content = Get-Content -LiteralPath $InventoryPath -Raw
if (-not (Test-Json -Json $content -SchemaFile $schemaPath -ErrorAction Stop)) {
    throw 'Invalid infrastructure asset inventory.'
}
$inventory = ConvertFrom-Json -InputObject $content -AsHashtable
$taskIds = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
foreach ($match in [regex]::Matches((Get-Content -LiteralPath $tasksPath -Raw), '(?m)^- \[[ x]\] (\d+\.\d+) ')) {
    $null = $taskIds.Add($match.Groups[1].Value)
}
$assetsById = [System.Collections.Generic.Dictionary[string, object]]::new([StringComparer]::Ordinal)
foreach ($asset in $inventory.assets) {
    if (-not $assetsById.TryAdd($asset.id, $asset)) {
        throw "Duplicate asset id: $($asset.id)"
    }
    foreach ($task in $asset.tasks) {
        if (-not $taskIds.Contains($task)) {
            throw "Unknown OpenSpec task '$task' in asset '$($asset.id)'."
        }
    }
}
foreach ($asset in $inventory.assets) {
    foreach ($dependency in $asset.dependsOn) {
        if (-not $assetsById.ContainsKey($dependency)) {
            throw "Unknown dependency '$dependency' in asset '$($asset.id)'."
        }
    }
}
$ordered = [System.Collections.Generic.List[string]]::new()
$remaining = [System.Collections.Generic.List[object]]::new()
foreach ($asset in $inventory.assets) {
    $remaining.Add($asset)
}
while ($remaining.Count -gt 0) {
    $ready = @($remaining | Where-Object {
        @($_.dependsOn | Where-Object { -not $ordered.Contains($_) }).Count -eq 0
    })
    if ($ready.Count -eq 0) {
        throw "Dependency cycle among: $(($remaining.id) -join ', ')"
    }
    foreach ($asset in $ready) {
        $ordered.Add($asset.id)
        $null = $remaining.Remove($asset)
    }
}

[pscustomobject]@{
    Action = $Action
    Mode = 'local-only'
    InventoryValid = $true
    AssetCount = $ordered.Count
    PreparationOrder = $ordered.ToArray()
    TemplatesBuilt = $false
    AzureReadiness = 'not-evaluated'
    DeploymentSupported = $false
}