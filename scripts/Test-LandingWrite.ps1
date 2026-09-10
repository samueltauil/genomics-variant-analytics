#Requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string] $Directory,
    [ValidateRange(1, 1073741824)]
    [long] $ByteCount = 16MB
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Directory -match '^[\\/]{2}' -or -not [IO.Path]::IsPathFullyQualified($Directory)) {
    throw 'An absolute local filesystem directory is required; UNC and device paths are prohibited.'
}
if ($Directory -match '(^|[\\/])\.{1,2}([\\/]|$)') {
    throw 'Dot path segments are prohibited.'
}
$fullPath = [IO.Path]::GetFullPath($Directory)
$root = [IO.Path]::GetPathRoot($fullPath)
$drive = [IO.DriveInfo]::new($root)
if ($drive.DriveType -ne [IO.DriveType]::Fixed) {
    throw 'Only a fixed local drive is supported; network and removable drives are prohibited.'
}
$currentPath = $root
$components = @('') + @($fullPath.Substring($root.Length) -split '[\\/]' | Where-Object { $_ })
foreach ($component in $components) {
    if ($component) {
        $currentPath = [IO.Path]::Combine($currentPath, $component)
    }
    $item = Get-Item -LiteralPath $currentPath -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Reparse points, junctions and symbolic links are prohibited in the directory path.'
    }
    if (-not $item.PSIsContainer) {
        throw 'The target must be an existing directory.'
    }
}
if ($drive.AvailableFreeSpace -lt $ByteCount + 16MB) {
    throw 'Insufficient free space for the requested write plus a 16 MiB reserve.'
}

$buffer = [byte[]]::new([int][Math]::Min(1MB, $ByteCount))
[Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
$expectedHasher = [Security.Cryptography.IncrementalHash]::CreateHash([Security.Cryptography.HashAlgorithmName]::SHA256)
try {
    $remaining = $ByteCount
    while ($remaining -gt 0) {
        $length = [int][Math]::Min($buffer.Length, $remaining)
        $expectedHasher.AppendData($buffer, 0, $length)
        $remaining -= $length
    }
    $expectedHash = [Convert]::ToHexString($expectedHasher.GetHashAndReset()).ToLowerInvariant()
}
finally {
    $expectedHasher.Dispose()
}

$scratchPath = [IO.Path]::Combine($fullPath, "landing-write-$([Guid]::NewGuid().ToString('N')).tmp")
$stream = $null
$actualHasher = $null
try {
    $stream = [IO.FileStream]::new(
        $scratchPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::ReadWrite,
        [IO.FileShare]::None, 1MB,
        ([IO.FileOptions]::SequentialScan -bor [IO.FileOptions]::DeleteOnClose)
    )
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $remaining = $ByteCount
    while ($remaining -gt 0) {
        $length = [int][Math]::Min($buffer.Length, $remaining)
        $stream.Write($buffer, 0, $length)
        $remaining -= $length
    }
    $stream.Flush($true)
    $timer.Stop()
    if ($stream.Length -ne $ByteCount) {
        throw 'Written file length does not match the requested byte count.'
    }
    $stream.Position = 0
    $actualHasher = [Security.Cryptography.SHA256]::Create()
    $actualHash = [Convert]::ToHexString($actualHasher.ComputeHash($stream)).ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw 'Read-back SHA-256 does not match the synthetic input.'
    }
}
finally {
    if ($null -ne $actualHasher) {
        $actualHasher.Dispose()
    }
    if ($null -ne $stream) {
        $stream.Dispose()
    }
}
if ([IO.File]::Exists($scratchPath)) {
    throw 'Scratch file cleanup could not be confirmed.'
}

[pscustomobject]@{
    SchemaVersion = 1
    Mode = 'local-smoke'
    ByteCount = $ByteCount
    DurationSeconds = $timer.Elapsed.TotalSeconds
    ThroughputMiBPerSecond = ($ByteCount / 1MB) / $timer.Elapsed.TotalSeconds
    TimingScope = 'sequential-write-and-flush-to-disk'
    ExpectedSha256 = $expectedHash
    ActualSha256 = $actualHash
    IntegrityVerified = $true
    ScratchFileRemoved = $true
    SmbAcceptancePassed = $false
    IopsCeilingVerified = $false
    AzureReadiness = 'not-evaluated'
} | ConvertTo-Json