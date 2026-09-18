#Requires -Version 7.2
<#
.SYNOPSIS
    Publishes pinned reference versions into the write-once reference zone (task 4.1).
.DESCRIPTION
    Streams each artifact from its pinned source into the reference container, recording a SHA-256
    per artifact in a manifest that commits the version. Already-published versions are skipped, so
    an interrupted run can simply be repeated.
#>
[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string] $EnvironmentFile,

    [ValidateNotNullOrEmpty()]
    [string] $CatalogFile,

    [Parameter(HelpMessage = 'Publish only entries whose type/name/version contains this text.')]
    [string] $Only
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
if (-not $EnvironmentFile) { $EnvironmentFile = Join-Path $repositoryRoot '.azure/environment.env.json' }
if (-not $CatalogFile) { $CatalogFile = Join-Path $repositoryRoot 'infra/reference-sources.json' }

$environment = Get-Content -LiteralPath $EnvironmentFile -Raw | ConvertFrom-Json

function Invoke-Az {
    param([Parameter(Mandatory)][string[]] $Arguments, [string] $ErrorMessage = 'Azure CLI call failed')

    $output = & az @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$ErrorMessage`n$output" }
    return $output
}

function Start-VerificationClient {
    $power = Invoke-Az @(
        'vm', 'get-instance-view', '-g', $environment.resourceGroupName, '-n', $environment.verificationVm,
        '--subscription', $environment.subscriptionId, '--query',
        'instanceView.statuses[?starts_with(code, ''PowerState'')].displayStatus', '-o', 'tsv'
    ) 'Could not read the client power state'

    if ($power -notmatch 'running') {
        Write-Host "Starting $($environment.verificationVm)."
        Invoke-Az @('vm', 'start', '-g', $environment.resourceGroupName, '-n', $environment.verificationVm,
            '--subscription', $environment.subscriptionId, '-o', 'none') 'Could not start the client'
    }
}

function New-ClientScript {
    param([Parameter(Mandatory)][string] $Driver, [string[]] $Modules, [hashtable] $Files = @{})

    $lines = @('set -eu', 'install -d /opt/genomics/scripts', 'cd /opt/genomics')
    foreach ($module in $Modules) {
        $lines += "cat >scripts/$module.py <<'MOD__$module'"
        $lines += (Get-Content (Join-Path $repositoryRoot "scripts/$module.py") -Raw).TrimEnd()
        $lines += "MOD__$module"
    }
    foreach ($name in $Files.Keys) {
        $lines += "cat >$name <<'FILE__$($name -replace '\W', '_')'"
        $lines += $Files[$name].TrimEnd()
        $lines += "FILE__$($name -replace '\W', '_')"
    }
    $lines += "cat >driver.py <<'DRIVEREOF'"
    $lines += $Driver.TrimEnd()
    $lines += 'DRIVEREOF'
    $lines += 'python3 driver.py'
    return ($lines -join "`n") + "`n"
}

function Invoke-ClientScript {
    param([Parameter(Mandatory)][string] $Script, [string] $ErrorMessage = 'Client script failed')

    $path = Join-Path ([IO.Path]::GetTempPath()) "genomics-$([guid]::NewGuid().ToString('n')).sh"
    [IO.File]::WriteAllText($path, $Script.Replace("`r`n", "`n"))
    try {
        $response = Invoke-Az @(
            'vm', 'run-command', 'invoke'
            '--name', $environment.verificationVm
            '--resource-group', $environment.resourceGroupName
            '--subscription', $environment.subscriptionId
            '--command-id', 'RunShellScript'
            '--scripts', "@$path"
            '-o', 'json'
        ) $ErrorMessage | ConvertFrom-Json
        return $response.value[0].message
    }
    finally {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
}

$driver = @'
import json, sys, urllib.request
from datetime import datetime, timezone
sys.path.insert(0, "/opt/genomics")
from scripts.blob_transport import BlobTransport
from scripts.publish_reference import ReferenceZone
from scripts.stage_landing import managed_identity_token

catalog = json.load(open("/opt/genomics/reference-sources.json"))
# None governor: this client run has no durable audit store, so it publishes unaudited by
# explicit request. Routing it through the governed interface is tracked by task 4.4.
zone = ReferenceZone(BlobTransport("__ACCOUNT__", "__CONTAINER__",
                                   managed_identity_token("__CLIENT_ID__")), None, None)
selector = "__ONLY__"

for spec in catalog["entries"]:
    entry = {key: spec[key] for key in ("type", "name", "version")}
    label = "%s/%s/%s" % (entry["type"], entry["name"], entry["version"])
    if selector and selector not in label:
        continue
    if zone.is_published(entry):
        print("SKIP|" + label)
        continue
    artifacts = [{
        "filename": a["filename"],
        "source": a["source"],
        "open": (lambda url=a["source"]: urllib.request.urlopen(url, timeout=900)),
    } for a in spec["artifacts"]]
    document = zone.publish(entry, artifacts, datetime.now(timezone.utc).isoformat())
    print("PUBLISHED|%s|%d" % (label, sum(a["size_bytes"] for a in document["artifacts"])))

print("---INVENTORY---")
print(json.dumps(zone.inventory(), indent=2))
'@

$driver = $driver.
    Replace('__ACCOUNT__', $environment.lakeAccount).
    Replace('__CONTAINER__', $environment.referenceContainer).
    Replace('__CLIENT_ID__', $environment.identities.staging).
    Replace('__ONLY__', $Only)

Start-VerificationClient

$script = New-ClientScript -Driver $driver `
    -Modules @('scan_landing', 'validate_submission', 'stage_landing', 'publish_reference', 'blob_transport') `
    -Files @{ 'reference-sources.json' = (Get-Content -LiteralPath $CatalogFile -Raw) }

Write-Host 'Publishing reference versions. Artifacts stream from their pinned sources.'
$message = Invoke-ClientScript $script 'Reference publication failed'

foreach ($line in ($message -split "`n")) {
    if ($line -match '^(?<action>PUBLISHED|SKIP)\|(?<label>[^|]+)(\|(?<bytes>\d+))?') {
        $size = if ($Matches.ContainsKey('bytes') -and $Matches.bytes) {
            '{0,8:N1} MiB' -f ([double]$Matches.bytes / 1MB)
        } else { '' }
        Write-Host ('  {0,-9} {1,-46} {2}' -f $Matches.action, $Matches.label, $size)
    }
}

$inventoryJson = ($message -split '---INVENTORY---', 2)[1]
if (-not $inventoryJson) { throw "Publication reported no inventory.`n$message" }

$inventory = ($inventoryJson -replace '(?s)\[stderr\].*$', '').Trim() | ConvertFrom-Json
Write-Host "`nPublished reference inventory:"
$inventory | Format-Table type, name, version, artifact_count -AutoSize | Out-String | Write-Host

$incomplete = @($inventory | Where-Object { -not $_.type -or -not $_.name -or -not $_.version })
if ($incomplete.Count -gt 0) { throw 'Inventory entries must report type, name and version.' }
Write-Host "Inventory reports type, name and version for all $($inventory.Count) entries."
