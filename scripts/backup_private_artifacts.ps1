<#
DEC-091: local private copy with Windows DPAPI CurrentUser.
Never prints file names, content, credentials or encryption material.
The archive is a standard ZIP protected by DPAPI, not a portable/off-site backup.
Plain ZIP data and restore verification remain in memory. Originals are read only.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SourceDirectory,
    [Parameter(Mandatory = $true)][string]$DestinationDirectory
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$script:Workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$script:Runtime = Join-Path $script:Workspace '.runtime'
$script:MaxBytes = 256MB

function Require-Backup([bool]$Condition) {
    if (-not $Condition) { throw [InvalidOperationException]::new('PRIVATE_BACKUP_INVALID') }
}

function Initialize-BackupPlatform {
    Require-Backup ($env:OS -eq 'Windows_NT')
    Require-Backup ([IO.DriveInfo]::new([IO.Path]::GetPathRoot($script:Workspace)).DriveFormat -eq 'NTFS')
    Add-Type -AssemblyName System.Security
    Add-Type -AssemblyName System.IO.Compression
    if (-not ('TccBackupFileIdentity' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class TccBackupFileIdentity {
    [StructLayout(LayoutKind.Sequential)] private struct Times { public uint Low, High; }
    [StructLayout(LayoutKind.Sequential)] private struct Info {
        public uint Attributes; public Times Creation, Access, Write;
        public uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
    }
    [DllImport("kernel32.dll", SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle file, out Info info);
    public static string Read(FileStream file) {
        Info i;
        if (!GetFileInformationByHandle(file.SafeFileHandle, out i) || i.Links != 1)
            throw new InvalidOperationException("PRIVATE_BACKUP_FILE_ID_INVALID");
        return String.Format("{0:x8}:{1:x8}:{2:x8}", i.Volume, i.IndexHigh, i.IndexLow);
    }
}
'@
    }
}

function Assert-BackupChain([string]$Path, [bool]$AllowMissing = $false) {
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $info = Get-Item -LiteralPath $current -Force
            Require-Backup (($info.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0)
        } else { Require-Backup $AllowMissing }
        $parent = [IO.Path]::GetDirectoryName($current)
        if ($parent -eq $current) { break }
        $current = $parent
    }
}

function Resolve-BackupPath([string]$Path) {
    $full = if ([IO.Path]::IsPathRooted($Path)) { [IO.Path]::GetFullPath($Path) }
            else { [IO.Path]::GetFullPath((Join-Path $script:Workspace $Path)) }
    $full = $full.TrimEnd('\')
    Require-Backup ($full.StartsWith($script:Runtime + '\', [StringComparison]::OrdinalIgnoreCase))
    & git -C $script:Workspace check-ignore --quiet -- $full 2>$null
    Require-Backup ($LASTEXITCODE -eq 0)
    return $full
}

function Get-BackupHash([IO.Stream]$Stream) {
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hasher.ComputeHash($Stream))).Replace('-', '').ToLowerInvariant() }
    finally { $hasher.Dispose() }
}

function Get-BackupFileRecord([string]$Path, [string]$Root) {
    Assert-BackupChain $Path
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        Assert-BackupChain $Path
        $identity = [TccBackupFileIdentity]::Read($stream)
        $info = Get-Item -LiteralPath $Path -Force
        $length = $stream.Length
        $written = $info.LastWriteTimeUtc.Ticks
        Require-Backup ($length -le $script:MaxBytes -and $info.Length -eq $length)
        $hash = Get-BackupHash $stream
        $info.Refresh()
        Require-Backup ($stream.Length -eq $length -and $info.Length -eq $length -and
            $info.LastWriteTimeUtc.Ticks -eq $written -and [TccBackupFileIdentity]::Read($stream) -eq $identity)
        Assert-BackupChain $Path
        return [pscustomobject][ordered]@{ relative_path = $Path.Substring($Root.Length + 1).Replace('\', '/');
            length = $length; last_write_utc_ticks = $written; file_id = $identity; sha256 = $hash }
    } finally { $stream.Dispose() }
}

function Get-BackupInventory([string]$Root) {
    Assert-BackupChain $Root
    $queue = [Collections.Generic.Queue[string]]::new()
    $queue.Enqueue($Root)
    $files = [Collections.Generic.List[string]]::new()
    $directories = [Collections.Generic.List[string]]::new()
    [long]$total = 0
    while ($queue.Count) {
        $directory = $queue.Dequeue()
        Assert-BackupChain $directory
        foreach ($item in Get-ChildItem -LiteralPath $directory -Force) {
            Require-Backup (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0)
            if ($item.PSIsContainer) {
                $queue.Enqueue($item.FullName)
                $directories.Add($item.FullName.Substring($Root.Length + 1).Replace('\', '/') + '/')
            } else {
                $total += $item.Length
                Require-Backup ($total -le $script:MaxBytes)
                $files.Add($item.FullName)
            }
        }
    }
    Require-Backup ($files.Count -gt 0)
    $records = @($files | Sort-Object | ForEach-Object { Get-BackupFileRecord $_ $Root })
    Require-Backup (($records | Measure-Object -Property length -Sum).Sum -eq $total)
    return [pscustomobject]@{ files = $records; directories = @($directories | Sort-Object); total_bytes = $total }
}

function Assert-BackupInventoryEqual($Before, $After) {
    Require-Backup (($Before | ConvertTo-Json -Depth 8 -Compress) -ceq ($After | ConvertTo-Json -Depth 8 -Compress))
}

function Write-BackupExclusive([string]$Path, [byte[]]$Bytes) {
    Assert-BackupChain ([IO.Path]::GetDirectoryName($Path))
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $stream.Write($Bytes, 0, $Bytes.Length)
        $stream.Flush($true)
        return [TccBackupFileIdentity]::Read($stream)
    } finally { $stream.Dispose() }
}

$stage = 'INITIALIZE'
try {
    Initialize-BackupPlatform
    $stage = 'VALIDATE_PATHS'
    $source = Resolve-BackupPath $SourceDirectory
    $destination = Resolve-BackupPath $DestinationDirectory
    $custody = Join-Path $script:Runtime 'custody'
    $secrets = Join-Path $script:Runtime 'secrets'
    Require-Backup ($source -ne $secrets -and -not $source.StartsWith($secrets + '\', [StringComparison]::OrdinalIgnoreCase))
    Require-Backup ($source -ne $custody -and -not $source.StartsWith($custody + '\', [StringComparison]::OrdinalIgnoreCase))
    Require-Backup ($destination -eq $custody -or $destination.StartsWith($custody + '\', [StringComparison]::OrdinalIgnoreCase))
    Require-Backup (-not $destination.StartsWith($source + '\', [StringComparison]::OrdinalIgnoreCase) -and
                    -not $source.StartsWith($destination + '\', [StringComparison]::OrdinalIgnoreCase))
    Require-Backup ([IO.Directory]::Exists($source))
    Assert-BackupChain $source
    Assert-BackupChain $destination $true
    $stage = 'SNAPSHOT_INPUTS'
    $before = Get-BackupInventory $source
    $stage = 'PACKAGE_MEMORY'
    $memory = [IO.MemoryStream]::new()
    $archive = [IO.Compression.ZipArchive]::new($memory, [IO.Compression.ZipArchiveMode]::Create, $true)
    try {
        foreach ($directory in $before.directories) { $null = $archive.CreateEntry($directory) }
        foreach ($record in $before.files) {
            $path = Join-Path $source $record.relative_path.Replace('/', '\')
            Assert-BackupChain $path
            $stream = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
            try {
                Assert-BackupChain $path
                Require-Backup ([TccBackupFileIdentity]::Read($stream) -eq $record.file_id -and $stream.Length -eq $record.length)
                Require-Backup ((Get-BackupHash $stream) -eq $record.sha256)
                $stream.Position = 0
                $entry = $archive.CreateEntry($record.relative_path, [IO.Compression.CompressionLevel]::Optimal)
                $output = $entry.Open()
                try { $stream.CopyTo($output) } finally { $output.Dispose() }
                Require-Backup ([TccBackupFileIdentity]::Read($stream) -eq $record.file_id -and $stream.Length -eq $record.length)
                Require-Backup ($memory.Length -le $script:MaxBytes)
            } finally { $stream.Dispose() }
        }
    } finally { $archive.Dispose() }
    Require-Backup ($memory.Length -le $script:MaxBytes)
    [byte[]]$plainZip = $memory.ToArray()
    $memory.Dispose()
    $stage = 'PROTECT_MEMORY'
    [byte[]]$encrypted = [Security.Cryptography.ProtectedData]::Protect($plainZip, $null,
        [Security.Cryptography.DataProtectionScope]::CurrentUser)
    [Array]::Clear($plainZip, 0, $plainZip.Length)
    Require-Backup ($encrypted.Length -le $script:MaxBytes + 1MB)
    $expectedMemory = [IO.MemoryStream]::new($encrypted, $false)
    try { $expectedEncryptedHash = Get-BackupHash $expectedMemory } finally { $expectedMemory.Dispose() }
    $stage = 'PERSIST_ENCRYPTED'
    $null = [IO.Directory]::CreateDirectory($destination)
    Assert-BackupChain $destination
    $backupId = [Guid]::NewGuid().ToString('N')
    $backup = Join-Path $destination $backupId
    Require-Backup (-not (Test-Path -LiteralPath $backup))
    $null = New-Item -ItemType Directory -Path $backup
    Assert-BackupChain $backup
    $encryptedPath = Join-Path $backup 'artifacts.zip.dpapi'
    $encryptedIdentity = Write-BackupExclusive $encryptedPath $encrypted
    [byte[]]$stored = [IO.File]::ReadAllBytes($encryptedPath)
    $storedMemory = [IO.MemoryStream]::new($stored, $false)
    try { $encryptedHash = Get-BackupHash $storedMemory } finally { $storedMemory.Dispose() }
    Require-Backup ($stored.Length -eq $encrypted.Length -and $encryptedHash -eq $expectedEncryptedHash)
    $stage = 'RESTORE_VERIFY_MEMORY'
    [byte[]]$restoredZip = [Security.Cryptography.ProtectedData]::Unprotect($stored, $null,
        [Security.Cryptography.DataProtectionScope]::CurrentUser)
    $restoredMemory = [IO.MemoryStream]::new($restoredZip, $false)
    $restored = [IO.Compression.ZipArchive]::new($restoredMemory, [IO.Compression.ZipArchiveMode]::Read, $false)
    try {
        Require-Backup ($restored.Entries.Count -eq $before.files.Count + $before.directories.Count)
        $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        foreach ($entry in $restored.Entries) {
            Require-Backup ($seen.Add($entry.FullName))
            if ($entry.FullName.EndsWith('/')) {
                Require-Backup ($before.directories -ccontains $entry.FullName)
            } else {
                $original = @($before.files | Where-Object { $_.relative_path -ceq $entry.FullName })
                Require-Backup ($original.Count -eq 1 -and $entry.Length -eq $original[0].length)
                $stream = $entry.Open()
                try { Require-Backup ((Get-BackupHash $stream) -eq $original[0].sha256) } finally { $stream.Dispose() }
            }
        }
    } finally { $restored.Dispose(); [Array]::Clear($restoredZip, 0, $restoredZip.Length) }
    $stage = 'RECHECK_ORIGINALS'
    $after = Get-BackupInventory $source
    Assert-BackupInventoryEqual $before $after
    $encryptedRecord = Get-BackupFileRecord $encryptedPath $backup
    Require-Backup ($encryptedRecord.file_id -eq $encryptedIdentity -and $encryptedRecord.sha256 -eq $encryptedHash)
    $stage = 'PERSIST_MANIFEST'
    $manifest = [ordered]@{ schema_version = 'private-local-backup/v1'; status = 'PASS'; backup_id = $backupId;
        created_utc = [DateTime]::UtcNow.ToString('o'); protection = 'Windows-DPAPI-CurrentUser';
        local_only = $true; portable = $false; offsite = $false; immutable = $false;
        source_directory = $source.Substring($script:Workspace.Length + 1).Replace('\', '/');
        original_files_unchanged = $true; restore_verified = $true; encrypted_sha256 = $encryptedHash;
        encrypted_bytes = $stored.Length; file_count = $before.files.Count; directories = $before.directories;
        original_bytes = $before.total_bytes; files = $before.files }
    [byte[]]$manifestBytes = [Text.UTF8Encoding]::new($false).GetBytes(($manifest | ConvertTo-Json -Depth 10) + "`n")
    $manifestPath = Join-Path $backup 'manifest.json'
    $null = Write-BackupExclusive $manifestPath $manifestBytes
    $manifestRecord = Get-BackupFileRecord $manifestPath $backup
    [ordered]@{ status = 'PASS'; backup_id = $backupId; file_count = $before.files.Count;
        restore_verified = $true; originals_unchanged = $true; protection = 'Windows-DPAPI-CurrentUser';
        encrypted_sha256 = $encryptedHash; manifest_sha256 = $manifestRecord.sha256;
        local_only = $true; portable = $false; offsite = $false; immutable = $false } | ConvertTo-Json -Compress
} catch {
    [ordered]@{ status = 'FAIL'; code = 'PRIVATE_BACKUP_FAILED'; stage = $stage } | ConvertTo-Json -Compress
    exit 1
}
