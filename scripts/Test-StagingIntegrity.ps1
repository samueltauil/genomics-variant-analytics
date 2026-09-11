#Requires -Version 7.2
<#
.SYNOPSIS
    Verifies staging integrity checking and the staging record (tasks 3.2, 3.3).
.DESCRIPTION
    Reads a staged artifact and its landing-zone source from inside the network, compares SHA-256
    digests, records the outcome, then deliberately corrupts the destination and re-verifies.
    Requires Test-Staging.ps1 to have staged the demo run first.
#>
[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string] $EnvironmentFile,

    [ValidateNotNullOrEmpty()]
    [string] $SourcePath = 'RUN-A/SAMPLE-1_S1_L001_R1_001.fastq.gz',

    [ValidateNotNullOrEmpty()]
    [string] $DestinationPath = 'Ingest/Genomics/FASTQ/RUN-A/SAMPLE-1_S1_L001_R1_001.fastq.gz'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
if (-not $EnvironmentFile) {
    $EnvironmentFile = Join-Path $repositoryRoot '.azure/environment.env.json'
}
$environment = Get-Content -LiteralPath $EnvironmentFile -Raw | ConvertFrom-Json

function Invoke-Az {
    param([Parameter(Mandatory)][string[]] $Arguments, [string] $ErrorMessage = 'Azure CLI call failed')

    $output = & az @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$ErrorMessage`n$output"
    }
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
import hashlib, json, sys, urllib.error, urllib.request
sys.path.insert(0, "/opt/genomics")
from scripts.stage_landing import API_VERSION, managed_identity_token
from scripts.stage_records import StagingLog

LANDING, SHARE = "__LANDING__", "__SHARE__"
LAKE, FILESYSTEM = "__LAKE__", "__FILESYSTEM__"
SOURCE, DESTINATION = "__SOURCE__", "__DESTINATION__"

files_token = managed_identity_token("__INGESTION__")
blob_token = managed_identity_token("__STAGING__")

def send(url, token, method="GET", extra=None, body=None):
    request = urllib.request.Request(url, method=method, data=body)
    request.add_header("Authorization", "Bearer " + token)
    request.add_header("x-ms-version", API_VERSION)
    for key, value in (extra or {}).items():
        request.add_header(key, value)
    return urllib.request.urlopen(request, timeout=120)

source_url = "https://%s.file.core.windows.net/%s/%s" % (LANDING, SHARE, SOURCE)
blob_url = "https://%s.blob.core.windows.net/%s/%s" % (LAKE, FILESYSTEM, DESTINATION)

def source_digest():
    with send(source_url, files_token, extra={"x-ms-file-request-intent": "backup"}) as response:
        return hashlib.sha256(response.read()).hexdigest()

def destination_state():
    with send(blob_url, blob_token) as response:
        payload = response.read()
        tier = response.headers.get("x-ms-access-tier") or "Hot"
    return hashlib.sha256(payload).hexdigest(), tier, len(payload)

def entry_for(source_checksum, destination_checksum, tier):
    return {
        "source_path": SOURCE,
        "run_id": SOURCE.split("/")[0],
        "sample_id": SOURCE.split("/")[-1].split("_")[0],
        "destination_uri": "abfss://%s@%s.dfs.core.windows.net/%s" % (FILESYSTEM, LAKE, DESTINATION),
        "storage_tier": tier,
        "classification": "genomic-primary",
        "source_checksum": source_checksum,
        "destination_checksum": destination_checksum,
    }

log = StagingLog("/tmp/staging-log.sqlite3")
try:
    expected = source_digest()
    actual, tier, size = destination_state()
    record = log.record(entry_for(expected, actual, tier), "2026-09-11T00:00:00Z")
    print("PHASE|intact|%s|%s|%s|%s|%d" % (record["state"], record["integrity_result"],
                                           record["storage_tier"], record["classification"],
                                           len(log.available_for_processing())))
    print("FIELDS|" + json.dumps({k: record[k] for k in (
        "source_path", "destination_uri", "state", "integrity_result",
        "storage_tier", "classification")}))

    # Deliberately corrupt the destination so verification has something real to catch.
    send(blob_url, blob_token, method="PUT",
         extra={"x-ms-blob-type": "BlockBlob", "Content-Type": "application/octet-stream"},
         body=b"corrupted" + b"\0" * (size - 9)).close()

    actual, tier, _ = destination_state()
    record = log.record(entry_for(expected, actual, tier), "2026-09-11T01:00:00Z")
    print("PHASE|corrupted|%s|%s|%s|%s|%d" % (record["state"], record["integrity_result"],
                                              record["storage_tier"], record["classification"],
                                              len(log.available_for_processing())))
    print("REPORT|%d" % len(log.report()))
finally:
    log.close()
'@

$driver = $driver.
    Replace('__LANDING__', $environment.landingAccount).
    Replace('__SHARE__', $environment.landingShare).
    Replace('__LAKE__', $environment.lakeAccount).
    Replace('__FILESYSTEM__', $environment.lakeFilesystem).
    Replace('__SOURCE__', $SourcePath).
    Replace('__DESTINATION__', $DestinationPath).
    Replace('__INGESTION__', $environment.identities.ingestion).
    Replace('__STAGING__', $environment.identities.staging)

$modules = 'scan_landing', 'validate_submission', 'stage_landing', 'stage_records'
$setup = @("set -eu", "install -d /opt/genomics/scripts", "cd /opt/genomics")
foreach ($module in $modules) {
    $setup += "cat >scripts/$module.py <<'MODEOF__$module'"
    $setup += (Get-Content (Join-Path $repositoryRoot "scripts/$module.py") -Raw).TrimEnd()
    $setup += "MODEOF__$module"
}
$setup += "cat >driver.py <<'DRIVEREOF'"
$setup += $driver.TrimEnd()
$setup += "DRIVEREOF"
$setup += "rm -f /tmp/staging-log.sqlite3"
$setup += "python3 driver.py"

$scriptPath = Join-Path ([IO.Path]::GetTempPath()) "genomics-integrity-$([guid]::NewGuid().ToString('n')).sh"
[IO.File]::WriteAllText($scriptPath, (($setup -join "`n") + "`n").Replace("`r`n", "`n"))

Write-Host 'Verifying staged artifact integrity from inside the network.'
try {
    $response = Invoke-Az @(
        'vm', 'run-command', 'invoke'
        '--name', $environment.verificationVm
        '--resource-group', $environment.resourceGroupName
        '--subscription', $environment.subscriptionId
        '--command-id', 'RunShellScript'
        '--scripts', "@$scriptPath"
        '-o', 'json'
    ) 'Integrity verification failed' | ConvertFrom-Json
}
finally {
    Remove-Item -LiteralPath $scriptPath -Force -ErrorAction SilentlyContinue
}

$message = $response.value[0].message
$phases = @{}
foreach ($line in ($message -split "`n")) {
    if ($line -match '^PHASE\|(?<p>[^|]+)\|(?<state>[^|]+)\|(?<integrity>[^|]+)\|(?<tier>[^|]+)\|(?<class>[^|]+)\|(?<available>\d+)') {
        $phases[$Matches.p] = [pscustomobject]@{
            Phase = $Matches.p; State = $Matches.state; Integrity = $Matches.integrity
            Tier = $Matches.tier; Classification = $Matches.class
            AvailableDownstream = [int]$Matches.available
        }
    }
}

if ($phases.Count -ne 2) {
    throw "Verification did not report both phases.`n$message"
}

$phases.Values | Sort-Object Phase -Descending | Format-Table -AutoSize | Out-String | Write-Host

if ($message -match 'FIELDS\|(?<json>\{.*\})') {
    $fields = $Matches.json | ConvertFrom-Json
    $missing = @($fields.PSObject.Properties | Where-Object { -not $_.Value } | ForEach-Object Name)
    if ($missing.Count -gt 0) { throw "Staging record fields empty: $($missing -join ', ')" }
    Write-Host "Staging record fields populated: $(($fields.PSObject.Properties.Name) -join ', ')"
}

$intact = $phases['intact']
$corrupted = $phases['corrupted']
if ($intact.State -ne 'staged' -or $intact.Integrity -ne 'verified' -or $intact.AvailableDownstream -ne 1) {
    throw 'An intact copy should verify and be available downstream.'
}
if ($corrupted.State -ne 'failed' -or $corrupted.Integrity -ne 'mismatch' -or $corrupted.AvailableDownstream -ne 0) {
    throw 'A corrupted destination should fail verification and be withheld downstream.'
}

Write-Host 'Integrity verification marks a corrupted destination failed and withholds it from processing.'
Write-Host 'Re-run Test-Staging.ps1 to restore an intact staged copy.'
