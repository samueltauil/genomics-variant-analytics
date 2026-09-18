#Requires -Version 7.2
<#
.SYNOPSIS
    Verifies the reference inventory and write-once semantics (tasks 4.1, 4.2).
.DESCRIPTION
    Lists published entries, attempts a direct overwrite of a published artifact, attempts to
    republish an existing version, then publishes a successor version and confirms the prior one
    remains retrievable. The successor test uses a small synthetic entry rather than inventing a
    reference build version.
#>
[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string] $EnvironmentFile
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
if (-not $EnvironmentFile) { $EnvironmentFile = Join-Path $repositoryRoot '.azure/environment.env.json' }
$environment = Get-Content -LiteralPath $EnvironmentFile -Raw | ConvertFrom-Json

function Invoke-Az {
    param([Parameter(Mandatory)][string[]] $Arguments, [string] $ErrorMessage = 'Azure CLI call failed')

    $output = & az @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$ErrorMessage`n$output" }
    return $output
}

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

$driver = @'
import io, json, sys, urllib.error
sys.path.insert(0, "/opt/genomics")
from scripts.blob_transport import BlobTransport
from scripts.publish_reference import ReferenceExistsError, ReferenceZone, reference_path
from scripts.stage_landing import managed_identity_token

transport = BlobTransport("__ACCOUNT__", "__CONTAINER__", managed_identity_token("__CLIENT_ID__"))
# None governor: this acceptance probe has no durable audit store; see task 4.4.
zone = ReferenceZone(transport, None, None)

inventory = zone.inventory()
print("INVENTORY|" + json.dumps(inventory))

published = [e for e in inventory if e["type"] == "genome"]
target = {k: published[0][k] for k in ("type", "name", "version")}
manifest_path = reference_path(target)

# A published artifact must not be replaceable in place.
try:
    transport.put_bytes(manifest_path, b'{"tampered": true}')
    print("OVERWRITE|ACCEPTED|the immutability policy did not reject the write")
except urllib.error.HTTPError as error:
    code = error.headers.get("x-ms-error-code") or str(error.code)
    print("OVERWRITE|REJECTED|%s %s" % (error.code, code))

# The publisher refuses before writing anything, independent of the storage policy.
try:
    zone.publish(target, [{"filename": "probe.txt", "open": lambda: io.BytesIO(b"x"),
                           "source": None}], "2026-09-11T00:00:00Z")
    print("REPUBLISH|ACCEPTED|the publisher allowed an existing version to be rewritten")
except ReferenceExistsError:
    print("REPUBLISH|REJECTED|publisher refused an already-published version")

probe_v1 = {"type": "knowledge-base", "name": "acceptance-probe", "version": "v1"}
probe_v2 = {"type": "knowledge-base", "name": "acceptance-probe", "version": "v2"}
if not zone.is_published(probe_v1):
    zone.publish(probe_v1, [{"filename": "entries.txt", "open": lambda: io.BytesIO(b"first"),
                             "source": None}], "2026-09-11T00:00:00Z")
if not zone.is_published(probe_v2):
    zone.publish(probe_v2, [{"filename": "entries.txt", "open": lambda: io.BytesIO(b"corrected"),
                             "source": None}], "2026-09-11T01:00:00Z")

first = transport.get(reference_path(probe_v1, "entries.txt"))
second = transport.get(reference_path(probe_v2, "entries.txt"))
print("SUCCESSOR|%s|%s|%s" % (
    "PUBLISHED" if zone.get_manifest(probe_v2) else "MISSING",
    "RETRIEVABLE" if first == b"first" else "ALTERED",
    second.decode(),
))

digests = zone.get_manifest(target)["artifacts"][0]
print("MANIFEST|%s|%s|%d" % (digests["filename"], digests["sha256"][:16], digests["size_bytes"]))
'@

$driver = $driver.
    Replace('__ACCOUNT__', $environment.lakeAccount).
    Replace('__CONTAINER__', $environment.referenceContainer).
    Replace('__CLIENT_ID__', $environment.identities.staging)

$modules = 'scan_landing', 'validate_submission', 'stage_landing', 'publish_reference', 'blob_transport'
$lines = @('set -eu', 'install -d /opt/genomics/scripts', 'cd /opt/genomics')
foreach ($module in $modules) {
    $lines += "cat >scripts/$module.py <<'MOD__$module'"
    $lines += (Get-Content (Join-Path $repositoryRoot "scripts/$module.py") -Raw).TrimEnd()
    $lines += "MOD__$module"
}
$lines += "cat >driver.py <<'DRIVEREOF'"
$lines += $driver.TrimEnd()
$lines += 'DRIVEREOF'
$lines += 'python3 driver.py'

$path = Join-Path ([IO.Path]::GetTempPath()) "genomics-reference-$([guid]::NewGuid().ToString('n')).sh"
[IO.File]::WriteAllText($path, (($lines -join "`n") + "`n").Replace("`r`n", "`n"))

Write-Host 'Verifying the reference inventory and write-once semantics.'
try {
    $response = Invoke-Az @(
        'vm', 'run-command', 'invoke'
        '--name', $environment.verificationVm
        '--resource-group', $environment.resourceGroupName
        '--subscription', $environment.subscriptionId
        '--command-id', 'RunShellScript'
        '--scripts', "@$path"
        '-o', 'json'
    ) 'Reference verification failed' | ConvertFrom-Json
}
finally {
    Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
}

$message = $response.value[0].message

if ($message -match 'INVENTORY\|(?<json>\[.*\])') {
    $inventory = $Matches.json | ConvertFrom-Json
    $inventory | Format-Table type, name, version, artifact_count -AutoSize | Out-String | Write-Host
    $incomplete = @($inventory | Where-Object { -not $_.type -or -not $_.name -or -not $_.version })
    if ($incomplete.Count -gt 0) { throw 'Inventory entries must report type, name and version.' }
}
else { throw "No inventory reported.`n$message" }

$results = foreach ($name in 'OVERWRITE', 'REPUBLISH') {
    if ($message -match "$name\|(?<status>[A-Z]+)\|(?<detail>[^\r\n]*)") {
        [pscustomobject]@{ Check = $name; Status = $Matches.status; Detail = $Matches.detail.Trim() }
    }
}
$results | Format-Table -AutoSize | Out-String | Write-Host

foreach ($result in $results) {
    if ($result.Status -ne 'REJECTED') {
        throw "$($result.Check) was not rejected: $($result.Detail)"
    }
}

if ($message -match 'SUCCESSOR\|(?<published>\w+)\|(?<prior>\w+)\|(?<content>\w+)') {
    Write-Host "Successor version: $($Matches.published); prior version: $($Matches.prior) (successor holds '$($Matches.content)')"
    if ($Matches.published -ne 'PUBLISHED' -or $Matches.prior -ne 'RETRIEVABLE') {
        throw 'A new version must publish while the prior version stays retrievable.'
    }
}
else { throw "Successor publication was not reported.`n$message" }

if ($message -match 'MANIFEST\|(?<file>[^|]+)\|(?<digest>[0-9a-f]+)\|(?<size>\d+)') {
    Write-Host "Manifest records $($Matches.file) as sha256 $($Matches.digest)... over $([int]$Matches.size) bytes."
}

Write-Host 'Published versions are immutable, and a successor leaves the prior version retrievable.'
