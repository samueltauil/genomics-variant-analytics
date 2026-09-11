#Requires -Version 7.2
<#
.SYNOPSIS
    Verifies that staging copies only files the inventory reports complete (task 3.1).
.DESCRIPTION
    Seeds a synthetic run on the landing share, inventories it twice so the stability rule can
    classify each file, runs the Data Factory pipeline over the complete set only, and checks
    the destination. Synthetic zero-filled files only; no genomic data is used.
#>
[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string] $EnvironmentFile
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
if (-not $EnvironmentFile) {
    $EnvironmentFile = Join-Path $repositoryRoot '.azure/environment.env.json'
}
$environment = Get-Content -LiteralPath $EnvironmentFile -Raw | ConvertFrom-Json
$destinationFolder = 'Ingest/Genomics/FASTQ/RUN-A'

function Invoke-Az {
    param([Parameter(Mandatory)][string[]] $Arguments, [string] $ErrorMessage = 'Azure CLI call failed')

    $output = & az @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$ErrorMessage`n$output"
    }
    return $output
}

function Invoke-Client {
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

$seeder = @'
import sys, urllib.error, urllib.request
sys.path.insert(0, "/opt/genomics")
from stage_landing import API_VERSION, managed_identity_token

token = managed_identity_token("__CLIENT_ID__")
base = "https://__ACCOUNT__.file.core.windows.net/__SHARE__"
RUN = "RUN-A"
COMPLETE = RUN + "/SAMPLE-1_S1_L001_R1_001.fastq.gz"
ARRIVING = RUN + "/SAMPLE-1_S1_L001_R2_001.fastq.gz"

def send(method, url, extra=None, body=None):
    request = urllib.request.Request(url, method=method, data=body)
    request.add_header("Authorization", "Bearer " + token)
    request.add_header("x-ms-version", API_VERSION)
    request.add_header("x-ms-file-request-intent", "backup")
    for key, value in (extra or {}).items():
        request.add_header(key, value)
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.status

def make_directory(path):
    try:
        send("PUT", "%s/%s?restype=directory" % (base, path))
    except urllib.error.HTTPError as error:
        if error.code != 409:
            raise

def write(path, size):
    send("PUT", "%s/%s" % (base, path),
         {"x-ms-type": "file", "x-ms-content-length": str(size), "Content-Length": "0"})
    send("PUT", "%s/%s?comp=range" % (base, path),
         {"x-ms-write": "update", "x-ms-range": "bytes=0-%d" % (size - 1)}, b"\0" * size)

def grow(path, size):
    send("PUT", "%s/%s?comp=properties" % (base, path),
         {"x-ms-content-length": str(size), "Content-Length": "0"})
    half = size // 2
    send("PUT", "%s/%s?comp=range" % (base, path),
         {"x-ms-write": "update", "x-ms-range": "bytes=%d-%d" % (half, size - 1)}, b"\0" * (size - half))

if sys.argv[1] == "create":
    make_directory(RUN)
    write(COMPLETE, 1048576)
    write(ARRIVING, 1048576)
elif sys.argv[1] == "grow":
    grow(ARRIVING, 2097152)
print("seed " + sys.argv[1] + " ok")
'@

$seeder = $seeder.
    Replace('__CLIENT_ID__', $environment.identities.ingestion).
    Replace('__ACCOUNT__', $environment.landingAccount).
    Replace('__SHARE__', $environment.landingShare)

$scanCommand = "python3 stage_landing.py --account $($environment.landingAccount) --share $($environment.landingShare) --inventory /tmp/inventory.sqlite3 --client-id $($environment.identities.ingestion)"

$setup = @"
set -eu
install -d /opt/genomics
cd /opt/genomics
cat >scan_landing.py <<'SCANEOF'
$(Get-Content (Join-Path $repositoryRoot 'scripts/scan_landing.py') -Raw)
SCANEOF
cat >stage_landing.py <<'STAGEEOF'
$(Get-Content (Join-Path $repositoryRoot 'scripts/stage_landing.py') -Raw)
STAGEEOF
cat >seed.py <<'SEEDEOF'
$seeder
SEEDEOF
rm -f /tmp/inventory.sqlite3
python3 seed.py create
$scanCommand > /tmp/scan1.json
python3 seed.py grow
$scanCommand > /tmp/scan2.json
echo '---INVENTORY---'
cat /tmp/scan2.json
"@

Write-Host 'Seeding the landing share and inventorying it twice.'
$message = Invoke-Client $setup 'Could not inventory the landing share'
$json = ($message -split '---INVENTORY---', 2)[1]
if (-not $json) {
    throw "Inventory produced no report.`n$message"
}

$report = $json.Trim() -replace '(?s)\[stderr\].*$', '' | ConvertFrom-Json
$complete = @($report.files | Where-Object { $_.state -eq 'complete' -and -not $_.metadata_error })
$arriving = @($report.files | Where-Object { $_.state -eq 'arriving' })

Write-Host "Inventory: $($complete.Count) complete, $($arriving.Count) arriving."
$report.files | Select-Object path, state, size_bytes | Format-Table -AutoSize | Out-String | Write-Host

if ($complete.Count -eq 0) {
    throw 'No file reached the complete state; staging would have nothing to copy.'
}

$items = foreach ($file in $complete) {
    @{
        sourceFolder      = [IO.Path]::GetDirectoryName($file.path).Replace('\', '/')
        fileName          = [IO.Path]::GetFileName($file.path)
        destinationFolder = $destinationFolder
    }
}

$body = @{ completeFiles = @($items) } | ConvertTo-Json -Depth 6 -Compress
$bodyPath = Join-Path ([IO.Path]::GetTempPath()) "adf-$([guid]::NewGuid().ToString('n')).json"
[IO.File]::WriteAllText($bodyPath, $body)

$factoryPath = "/subscriptions/$($environment.subscriptionId)/resourceGroups/$($environment.resourceGroupName)/providers/Microsoft.DataFactory/factories/$($environment.stagingFactory)"
try {
    $run = Invoke-Az @(
        'rest', '--method', 'post'
        '--url', "https://management.azure.com$factoryPath/pipelines/$($environment.stagingPipeline)/createRun?api-version=2018-06-01"
        '--body', "@$bodyPath"
        '-o', 'json'
    ) 'Could not start the staging pipeline' | ConvertFrom-Json
}
finally {
    Remove-Item -LiteralPath $bodyPath -Force -ErrorAction SilentlyContinue
}

Write-Host "Staging run $($run.runId) started."
$deadline = (Get-Date).AddMinutes(20)
do {
    Start-Sleep -Seconds 20
    $status = Invoke-Az @(
        'rest', '--method', 'get'
        '--url', "https://management.azure.com$factoryPath/pipelineruns/$($run.runId)?api-version=2018-06-01"
        '-o', 'json'
    ) 'Could not read the staging run' | ConvertFrom-Json
    Write-Host "  status: $($status.status)"
} while ($status.status -in @('Queued', 'InProgress') -and (Get-Date) -lt $deadline)

if ($status.status -ne 'Succeeded') {
    throw "Staging run ended as $($status.status): $($status.message)"
}

$listing = Invoke-Client @"
set -eu
cd /opt/genomics
python3 - <<'PYEOF'
import sys, urllib.request
sys.path.insert(0, "/opt/genomics")
from stage_landing import managed_identity_token
token = managed_identity_token("$($environment.identities.staging)")
url = "https://$($environment.lakeAccount).dfs.core.windows.net/$($environment.lakeFilesystem)?resource=filesystem&recursive=true&directory=$destinationFolder"
request = urllib.request.Request(url)
request.add_header("Authorization", "Bearer " + token)
request.add_header("x-ms-version", "2021-06-08")
import json
with urllib.request.urlopen(request, timeout=60) as response:
    for path in json.load(response).get("paths", []):
        print("STAGED|" + path["name"])
PYEOF
"@ 'Could not list the staged output'

$staged = [regex]::Matches($listing, 'STAGED\|(?<path>\S+)') | ForEach-Object { $_.Groups['path'].Value }
Write-Host "Staged objects:"
$staged | ForEach-Object { Write-Host "  $_" }

$expected = $complete | ForEach-Object { "$destinationFolder/$([IO.Path]::GetFileName($_.path))" }
$unexpected = @($staged | Where-Object { $_ -notin $expected })
$missing = @($expected | Where-Object { $_ -notin $staged })
$arrivingNames = $arriving | ForEach-Object { [IO.Path]::GetFileName($_.path) }
$leaked = @($staged | Where-Object { [IO.Path]::GetFileName($_) -in $arrivingNames })

if ($missing.Count -gt 0) { throw "Complete files were not staged: $($missing -join ', ')" }
if ($leaked.Count -gt 0) { throw "Files still arriving were staged: $($leaked -join ', ')" }
if ($unexpected.Count -gt 0) { throw "Unexpected objects staged: $($unexpected -join ', ')" }

Write-Host "Staging copied $($complete.Count) complete file(s) and skipped $($arriving.Count) still arriving."
