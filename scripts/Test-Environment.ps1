#Requires -Version 7.2
<#
.SYNOPSIS
    Runs the deployed acceptance checks for the landing zone and object storage.
.DESCRIPTION
    Exercises the private data planes from the in-VNet client: the folder taxonomy exists, the
    staging identity can write it, the processing identity cannot, and the SMB share sustains a
    sequential write. Reports measured values rather than asserting the design is correct.
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 1024)]
    [int] $WriteSizeGiB = 100,

    [switch] $SkipThroughput,

    [ValidateNotNullOrEmpty()]
    [string] $EnvironmentFile
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
if (-not $EnvironmentFile) {
    $EnvironmentFile = Join-Path $repositoryRoot '.azure/environment.env.json'
}
if (-not (Test-Path -LiteralPath $EnvironmentFile)) {
    throw "No deployed environment found at $EnvironmentFile. Run Deploy-Accelerator.ps1 first."
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

$share = Invoke-Az @(
    'storage', 'share-rm', 'show'
    '--storage-account', $environment.landingAccount
    '--resource-group', $environment.resourceGroupName
    '--subscription', $environment.subscriptionId
    '--name', $environment.landingShare
    '-o', 'json'
) 'Could not read the landing share' | ConvertFrom-Json

$provisionedIops = $share.provisionedIops
$provisionedMibps = $share.provisionedBandwidthMibps

$landingAccount = Invoke-Az @(
    'storage', 'account', 'show'
    '--name', $environment.landingAccount
    '--resource-group', $environment.resourceGroupName
    '--subscription', $environment.subscriptionId
    '-o', 'json'
) 'Could not read the landing account' | ConvertFrom-Json

$template = @'
set -eu

imds_token() {
  curl -s -m 30 -H Metadata:true "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=$1&client_id=$2" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'
}

STORAGE_RESOURCE=https%3A%2F%2Fstorage.azure.com%2F
FILES_RESOURCE=https%3A%2F%2Fstorage.azure.com%2F
ARM_RESOURCE=https%3A%2F%2Fmanagement.azure.com%2F
LAKE=https://__LAKE_ACCOUNT__.dfs.core.windows.net/__FILESYSTEM__

staging=$(imds_token $STORAGE_RESOURCE __STAGING_CLIENT_ID__)
pipeline=$(imds_token $STORAGE_RESOURCE __PIPELINE_CLIENT_ID__)

missing=0
total=0
for directory in __DIRECTORIES__; do
  total=$((total+1))
  code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $staging" -H 'x-ms-version: 2021-06-08' "$LAKE/$directory")
  [ "$code" = "200" ] || missing=$((missing+1))
done
if [ $missing -eq 0 ]; then
  echo "CHECK|taxonomy-paths-exist|PASS|$total directories return 200"
else
  echo "CHECK|taxonomy-paths-exist|FAIL|$missing of $total missing"
fi

code=$(curl -s -o /dev/null -w '%{http_code}' -X PUT -H "Authorization: Bearer $staging" -H 'x-ms-version: 2021-06-08' -H 'Content-Length: 0' "$LAKE/Ingest/Genomics/FASTQ/.acceptance-probe?resource=file")
if [ "$code" = "201" ]; then
  echo "CHECK|staging-identity-writes|PASS|created probe file"
else
  echo "CHECK|staging-identity-writes|FAIL|http $code"
fi

code=$(curl -s -o /dev/null -w '%{http_code}' -X PUT -H "Authorization: Bearer $pipeline" -H 'x-ms-version: 2021-06-08' -H 'Content-Length: 0' "$LAKE/Ingest/Genomics/FASTQ/.denied-probe?resource=file")
if [ "$code" = "403" ]; then
  echo "CHECK|processing-identity-write-denied|PASS|http 403"
else
  echo "CHECK|processing-identity-write-denied|FAIL|http $code"
fi

code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $pipeline" -H 'x-ms-version: 2021-06-08' "$LAKE/Ingest")
if [ "$code" = "200" ]; then
  echo "CHECK|processing-identity-reads|PASS|http 200"
else
  echo "CHECK|processing-identity-reads|FAIL|http $code"
fi

code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $pipeline" -H 'x-ms-version: 2022-11-02' -H 'x-ms-file-request-intent: backup' "https://__LANDING_ACCOUNT__.file.core.windows.net/__SHARE__?restype=directory&comp=list")
if [ "$code" = "403" ]; then
  echo "CHECK|processing-identity-landing-read-denied|PASS|http 403"
else
  echo "CHECK|processing-identity-landing-read-denied|FAIL|http $code"
fi

files=$(imds_token $FILES_RESOURCE __INGESTION_CLIENT_ID__)
if [ __RUN_THROUGHPUT__ -eq 1 ]; then
cat >/tmp/filewrite.py <<'PYEOF'
import concurrent.futures, sys, time, urllib.error, urllib.request

account, share, path, token, total_mib = sys.argv[1:6]
total = int(total_mib) * 1024 * 1024
chunk = 4 * 1024 * 1024
base = "https://%s.file.core.windows.net/%s/%s" % (account, share, path)
common = {
    "Authorization": "Bearer " + token,
    "x-ms-version": "2022-11-02",
    "x-ms-file-request-intent": "backup",
}

def send(method, url, extra, body=None):
    request = urllib.request.Request(url, method=method, data=body)
    for key, value in dict(common, **extra).items():
        request.add_header(key, value)
    with urllib.request.urlopen(request) as response:
        return response.status

send("PUT", base, {"x-ms-type": "file", "x-ms-content-length": str(total), "Content-Length": "0"})
buffer = b"\0" * chunk
throttled = []

def upload(offset):
    last = min(offset + chunk, total) - 1
    body = buffer[: last - offset + 1]
    headers = {"x-ms-write": "update", "x-ms-range": "bytes=%d-%d" % (offset, last)}
    delay = 0.5
    for attempt in range(9):
        try:
            return send("PUT", base + "?comp=range", headers, body)
        except urllib.error.HTTPError as error:
            # Provisioned shares answer 503 once the provisioned rate is exceeded.
            if error.code not in (500, 503) or attempt == 8:
                raise
            throttled.append(1)
            time.sleep(delay)
            delay = min(delay * 2, 8)

started = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
    for _ in pool.map(upload, range(0, total, chunk)):
        pass
elapsed = max(time.time() - started, 0.001)
print("%s MiB in %.0fs = %.0f MiB/s, %d throttled responses"
      % (total_mib, elapsed, total / 1048576 / elapsed, len(throttled)))
PYEOF

if result=$(python3 /tmp/filewrite.py __LANDING_ACCOUNT__ __SHARE__ acceptance-sequential.bin "$files" __WRITE_MIB__ 2>/tmp/filewrite.log); then
  echo "CHECK|share-sequential-write|MEASURED|$result over private endpoint (REST, not SMB)"
else
  echo "CHECK|share-sequential-write|FAIL|$(tail -c 200 /tmp/filewrite.log | tr '\n' ' ')"
fi

curl -s -o /dev/null -X DELETE -H "Authorization: Bearer $files" -H 'x-ms-version: 2022-11-02' -H 'x-ms-file-request-intent: backup' "https://__LANDING_ACCOUNT__.file.core.windows.net/__SHARE__/acceptance-sequential.bin"
fi
'@

$directoryList = ($environment.taxonomy | ForEach-Object { "'$_'" }) -join ' '
$script = $template.
    Replace('__LAKE_ACCOUNT__', $environment.lakeAccount).
    Replace('__FILESYSTEM__', $environment.lakeFilesystem).
    Replace('__LANDING_ACCOUNT__', $environment.landingAccount).
    Replace('__SHARE__', $environment.landingShare).
    Replace('__SUBSCRIPTION__', $environment.subscriptionId).
    Replace('__RESOURCE_GROUP__', $environment.resourceGroupName).
    Replace('__STAGING_CLIENT_ID__', $environment.identities.staging).
    Replace('__PIPELINE_CLIENT_ID__', $environment.identities.pipeline).
    Replace('__INGESTION_CLIENT_ID__', $environment.identities.ingestion).
    Replace('__DIRECTORIES__', $directoryList).
    Replace('__RUN_THROUGHPUT__', $(if ($SkipThroughput) { '0' } else { '1' })).
    Replace('__WRITE_MIB__', ($WriteSizeGiB * 1024).ToString())

$scriptPath = Join-Path ([IO.Path]::GetTempPath()) "genomics-acceptance-$([guid]::NewGuid().ToString('n')).sh"
[IO.File]::WriteAllText($scriptPath, $script.Replace("`r`n", "`n"))

$sizeNote = if ($SkipThroughput) { 'throughput skipped' } else { "writing $WriteSizeGiB GiB" }
Write-Host "Running acceptance checks on $($environment.verificationVm) ($sizeNote)."
try {
    $response = Invoke-Az @(
        'vm', 'run-command', 'invoke'
        '--name', $environment.verificationVm
        '--resource-group', $environment.resourceGroupName
        '--subscription', $environment.subscriptionId
        '--command-id', 'RunShellScript'
        '--scripts', "@$scriptPath"
        '-o', 'json'
    ) 'Acceptance run failed' | ConvertFrom-Json
}
finally {
    Remove-Item -LiteralPath $scriptPath -Force -ErrorAction SilentlyContinue
}

$message = $response.value[0].message
$results = foreach ($line in ($message -split "`n")) {
    if ($line -match '^CHECK\|(?<name>[^|]+)\|(?<status>[^|]+)\|(?<detail>.*)$') {
        [pscustomobject]@{
            Check  = $Matches.name
            Status = $Matches.status
            Detail = $Matches.detail.Trim()
        }
    }
}

if (-not $results) {
    throw "No checks reported.`n$message"
}

$results + [pscustomobject]@{
    Check  = 'smb-key-authentication'
    Status = if ($landingAccount.allowSharedKeyAccess) { 'AVAILABLE' } else { 'BLOCKED' }
    Detail = if ($landingAccount.allowSharedKeyAccess) {
        'shared key enabled; SMB NTLMv2 mount is possible'
    }
    else {
        'subscription policy disables allowSharedKeyAccess, which Azure Files SMB NTLMv2 requires'
    }
} + [pscustomobject]@{
    Check  = 'share-provisioned-ceiling'
    Status = 'MEASURED'
    Detail = "$provisionedIops IOPS, $provisionedMibps MiB/s provisioned"
} | Format-Table -AutoSize | Out-String | Write-Host

$measured = $results | Where-Object Check -eq 'share-sequential-write'
if ($measured -and $measured.Detail -match '= (\d+) MiB/s') {
    $rate = [int]$Matches[1]
    $ratio = [math]::Round(100 * $rate / $provisionedMibps)
    Write-Host "Sequential write reached $rate MiB/s, $ratio% of the $provisionedMibps MiB/s provisioned."
}

$failed = @($results | Where-Object Status -eq 'FAIL')
if ($failed.Count -gt 0) {
    throw "$($failed.Count) acceptance check(s) failed."
}
Write-Host 'All reported checks passed.'
