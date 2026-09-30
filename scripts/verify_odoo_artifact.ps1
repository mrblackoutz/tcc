param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Write-Host 'Candidate verification only; does not select or authorize.' -ForegroundColor Cyan

# Read-only inputs and daemon inspection. Only fresh ignored evidence is written;
# no build, pull, load, push, lock update, database access or deletion occurs.
$repositoryRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$buildRoot = [IO.Path]::GetFullPath((Join-Path $repositoryRoot '.runtime\build'))
$expectedCommit = 'a4b877245c9cb5e3d7152d1593a518170f115ca1'
$expectedRepository = 'https://github.com/odoo/odoo.git'
$expectedBase = 'python:3.12-slim-bookworm@sha256:4427763a1ba36f5aa8f656a03e5d00f3b8d61f5dd950c73df6c14f8c7640f8ab'
$expectedUser = '10001:10001'
$expectedPlatform = 'linux/amd64'
$imageTag = 'tcc-odoo:19.0-a4b8772'
$verificationRoot = Join-Path $buildRoot ('verify-current-' + [Guid]::NewGuid().ToString('N'))
$verificationStage = 'INPUTS'

function Assert-Within {
    param([string]$Path, [string]$Root)
    $absolute = [IO.Path]::GetFullPath($Path)
    $prefix = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    if (-not $absolute.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Verification path is outside its intended directory'
    }
    return $absolute
}

function Assert-NoReparsePoint {
    param([string]$Path)
    $current = [IO.Path]::GetFullPath($Path)
    while ($current -and $current.Length -ge $repositoryRoot.Length) {
        if (Test-Path -LiteralPath $current) {
            if ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Reparse points are not allowed in verification paths'
            }
        }
        if ($current -eq $repositoryRoot) { break }
        $current = Split-Path -Parent $current
    }
}

function Get-RequiredProperty {
    param($Object, [string]$Name)
    if ($null -eq $Object -or $null -eq $Object.PSObject.Properties[$Name]) {
        throw 'Required verification property is missing'
    }
    return $Object.PSObject.Properties[$Name].Value
}

function Assert-Digest {
    param([string]$Digest)
    if ($Digest -cnotmatch '^sha256:[0-9a-f]{64}$') { throw 'Malformed SHA-256 digest' }
}

function Assert-Size {
    param($Expected, [string]$Path)
    if (($Expected -isnot [int] -and $Expected -isnot [long]) -or $Expected -lt 1) {
        throw 'Invalid descriptor size'
    }
    if ((Get-Item -LiteralPath $Path).Length -ne $Expected) { throw 'Descriptor size does not match artifact bytes' }
}

function Get-Digest {
    param([string]$Path)
    return 'sha256:' + (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-BlobMember {
    param([string]$Digest)
    Assert-Digest $Digest
    return 'blobs/sha256/' + $Digest.Substring(7)
}

function Invoke-QuietNative {
    param([string]$Executable, [string[]]$Arguments, [string]$Failure)
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $captured = @(& $Executable @Arguments 2>&1)
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { throw $Failure }
    return (($captured | ForEach-Object { [string]$_ }) -join [Environment]::NewLine)
}

function Expand-VerifiedMembers {
    param([string]$Archive, [string]$Destination, [string[]]$Members)
    $safeDestination = Assert-Within $Destination $verificationRoot
    Assert-NoReparsePoint $safeDestination
    $unique = @($Members | Select-Object -Unique)
    foreach ($member in $unique) {
        if ($member -cnotmatch '^(index\.json|oci-layout|manifest\.json|blobs/sha256/[0-9a-f]{64})$') {
            throw 'Unsafe tar member path'
        }
    }
    $names = Invoke-QuietNative 'tar' (@('-t', '-f', $Archive) + $unique) 'Unable to list required archive members'
    $listed = @($names -split '\r?\n' | Where-Object { $_ -ne '' })
    if ($listed.Count -ne $unique.Count) { throw 'Missing or duplicate archive member' }
    foreach ($member in $unique) {
        if (@($listed | Where-Object { $_ -ceq $member }).Count -ne 1) { throw 'Unexpected archive member name' }
    }
    $verbose = Invoke-QuietNative 'tar' (@('-t', '-v', '-f', $Archive) + $unique) 'Unable to verify archive member types'
    $details = @($verbose -split '\r?\n' | Where-Object { $_ -ne '' })
    if ($details.Count -ne $unique.Count -or @($details | Where-Object { -not $_.StartsWith('-') }).Count -ne 0) {
        throw 'Archive verification members must be regular files'
    }
    New-Item -ItemType Directory -Path $safeDestination -Force | Out-Null
    $null = Invoke-QuietNative 'tar' (@('-x', '-f', $Archive, '-C', $safeDestination, '--no-same-owner', '--no-same-permissions') + $unique) 'Archive extraction failed'
    foreach ($member in $unique) {
        $resolved = Assert-Within (Join-Path $safeDestination ($member -replace '/', [IO.Path]::DirectorySeparatorChar)) $safeDestination
        Assert-NoReparsePoint $resolved
        if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) { throw 'Extracted verification member is missing' }
    }
}

function Get-LayerDiffId {
    param([string]$Path, [string]$MediaType)
    $stream = [IO.File]::OpenRead($Path)
    $expanded = $null
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $first = $stream.ReadByte()
        $second = $stream.ReadByte()
        $stream.Position = 0
        $gzip = $first -eq 31 -and $second -eq 139
        if ($MediaType -eq 'application/vnd.oci.image.layer.v1.tar+gzip' -and -not $gzip) { throw 'Layer compression disagrees with OCI media type' }
        if ($MediaType -eq 'application/vnd.oci.image.layer.v1.tar' -and $gzip) { throw 'Layer compression disagrees with OCI media type' }
        if ($gzip) {
            $expanded = [IO.Compression.GZipStream]::new($stream, [IO.Compression.CompressionMode]::Decompress, $true)
            $bytes = $sha.ComputeHash($expanded)
        }
        else { $bytes = $sha.ComputeHash($stream) }
        return 'sha256:' + ([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
    }
    finally {
        if ($expanded) { $expanded.Dispose() }
        $sha.Dispose()
        $stream.Dispose()
    }
}

function Assert-Labels {
    param($Labels)
    $required = @{
        'org.opencontainers.image.source' = $expectedRepository
        'org.opencontainers.image.revision' = $expectedCommit
        'org.opencontainers.image.base.name' = $expectedBase
        'br.edu.fci.tcc.platform' = $expectedPlatform
        'org.opencontainers.image.version' = '19.0'
    }
    foreach ($key in $required.Keys) {
        if ([string](Get-RequiredProperty $Labels $key) -cne $required[$key]) { throw 'Image provenance label mismatch' }
    }
}

try {
    Assert-NoReparsePoint $buildRoot
    $metadataPath = Assert-Within (Join-Path $buildRoot 'odoo-oci-metadata.json') $buildRoot
    $ociArchive = Assert-Within (Join-Path $buildRoot 'odoo-image.oci.tar') $buildRoot
    $dockerArchive = Assert-Within (Join-Path $buildRoot 'odoo-image.docker.tar') $buildRoot
    foreach ($path in @($metadataPath, $ociArchive, $dockerArchive)) {
        Assert-NoReparsePoint $path
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Required candidate artifact is unavailable' }
    }
    $lockPath = Assert-Within (Join-Path $repositoryRoot 'reproducibility\odoo-source.lock.json') $repositoryRoot
    Assert-NoReparsePoint $lockPath
    $sourceLock = Get-Content -Raw -Encoding utf8 -LiteralPath $lockPath | ConvertFrom-Json
    if ($sourceLock.selected_commit -cne $expectedCommit -or $sourceLock.repository -cne $expectedRepository -or
        $sourceLock.image.base_image_reference -cne $expectedBase -or $sourceLock.image.runtime_platform -cne $expectedPlatform) {
        throw 'Fixed source, base or platform differs from expected laboratory provenance'
    }
    $dockerfilePath = Assert-Within (Join-Path $repositoryRoot 'odoo\Dockerfile') $repositoryRoot
    Assert-NoReparsePoint $dockerfilePath
    $dockerfileSha256 = (Get-Digest $dockerfilePath).Substring(7)
    if ($dockerfileSha256 -cne $sourceLock.image.dockerfile_sha256) { throw 'Current Dockerfile differs from provenance lock' }

    $metadata = Get-Content -Raw -Encoding utf8 -LiteralPath $metadataPath | ConvertFrom-Json
    $verificationStage = 'BUILD_METADATA'
    $manifestDigest = [string](Get-RequiredProperty $metadata 'containerimage.digest')
    $configDigest = [string](Get-RequiredProperty $metadata 'containerimage.config.digest')
    Assert-Digest $manifestDigest
    Assert-Digest $configDigest
    if ($manifestDigest -ceq $configDigest) { throw 'Manifest and config identities must differ' }
    $descriptor = Get-RequiredProperty $metadata 'containerimage.descriptor'
    if ($descriptor.digest -cne $manifestDigest -or $descriptor.mediaType -cne 'application/vnd.oci.image.manifest.v1+json' -or
        $descriptor.platform.os -cne 'linux' -or $descriptor.platform.architecture -cne 'amd64') {
        throw 'Candidate metadata descriptor is inconsistent'
    }
    $provenance = Get-RequiredProperty $metadata 'buildx.build.provenance'
    $arguments = $provenance.invocation.parameters.args
    if ((Get-RequiredProperty $arguments 'build-arg:ODOO_COMMIT') -cne $expectedCommit -or
        (Get-RequiredProperty $arguments 'build-arg:ODOO_REPOSITORY') -cne $expectedRepository -or
        (Get-RequiredProperty $arguments 'build-arg:PYTHON_BASE_IMAGE') -cne $expectedBase -or
        $provenance.invocation.environment.platform -cne $expectedPlatform) {
        throw 'Build metadata source arguments are inconsistent'
    }

    $null = Assert-Within $verificationRoot $buildRoot
    New-Item -ItemType Directory -Path $verificationRoot | Out-Null
    $ociDirectory = Join-Path $verificationRoot 'oci'
    $dockerDirectory = Join-Path $verificationRoot 'docker'
    $manifestMember = Get-BlobMember $manifestDigest
    $configMember = Get-BlobMember $configDigest
    $verificationStage = 'OCI_METADATA'
    Expand-VerifiedMembers $ociArchive $ociDirectory @('index.json', 'oci-layout', $manifestMember, $configMember)
    $manifestPath = Join-Path $ociDirectory ($manifestMember -replace '/', '\')
    $configPath = Join-Path $ociDirectory ($configMember -replace '/', '\')
    if ((Get-Digest $manifestPath) -cne $manifestDigest -or (Get-Digest $configPath) -cne $configDigest) { throw 'OCI manifest or config bytes fail digest verification' }
    Assert-Size $descriptor.size $manifestPath
    $layout = Get-Content -Raw -Encoding utf8 -LiteralPath (Join-Path $ociDirectory 'oci-layout') | ConvertFrom-Json
    if ($layout.imageLayoutVersion -cne '1.0.0') { throw 'Unsupported OCI layout version' }
    $index = Get-Content -Raw -Encoding utf8 -LiteralPath (Join-Path $ociDirectory 'index.json') | ConvertFrom-Json
    $entries = @($index.manifests)
    if ($index.schemaVersion -ne 2 -or $entries.Count -ne 1 -or $entries[0].digest -cne $manifestDigest -or
        $entries[0].mediaType -cne $descriptor.mediaType -or $entries[0].platform.os -cne 'linux' -or
        $entries[0].platform.architecture -cne 'amd64') { throw 'OCI index must contain exactly one selected linux/amd64 manifest' }
    Assert-Size $entries[0].size $manifestPath
    $manifest = Get-Content -Raw -Encoding utf8 -LiteralPath $manifestPath | ConvertFrom-Json
    if ($manifest.schemaVersion -ne 2 -or $manifest.mediaType -cne $descriptor.mediaType -or
        $manifest.config.digest -cne $configDigest -or $manifest.config.mediaType -cne 'application/vnd.oci.image.config.v1+json') { throw 'OCI manifest config linkage is invalid' }
    Assert-Size $manifest.config.size $configPath
    $config = Get-Content -Raw -Encoding utf8 -LiteralPath $configPath | ConvertFrom-Json
    if ($config.os -cne 'linux' -or $config.architecture -cne 'amd64' -or $config.config.User -cne $expectedUser -or $config.rootfs.type -cne 'layers') { throw 'OCI config platform, user or rootfs is inconsistent' }
    Assert-Labels $config.config.Labels
    $layers = @($manifest.layers)
    $diffIds = @($config.rootfs.diff_ids)
    if ($layers.Count -lt 1 -or $layers.Count -gt 64 -or $layers.Count -ne $diffIds.Count) { throw 'OCI layer count does not match rootfs' }
    $layerMembers = @($layers | ForEach-Object { Get-BlobMember ([string]$_.digest) })
    $verificationStage = 'OCI_LAYERS'
    Expand-VerifiedMembers $ociArchive $ociDirectory $layerMembers
    $layerEvidence = @()
    for ($i = 0; $i -lt $layers.Count; $i++) {
        Assert-Digest ([string]$diffIds[$i])
        $layer = $layers[$i]
        if ($layer.mediaType -cne 'application/vnd.oci.image.layer.v1.tar+gzip' -and $layer.mediaType -cne 'application/vnd.oci.image.layer.v1.tar') { throw 'Unsupported OCI layer media type' }
        $layerPath = Join-Path $ociDirectory ($layerMembers[$i] -replace '/', '\')
        Assert-Size $layer.size $layerPath
        if ((Get-Digest $layerPath) -cne $layer.digest -or (Get-LayerDiffId $layerPath $layer.mediaType) -cne $diffIds[$i]) { throw 'OCI layer bytes or uncompressed rootfs identity mismatch' }
        $layerEvidence += [ordered]@{ digest = [string]$layer.digest; size = [long]$layer.size; diffId = [string]$diffIds[$i] }
    }

    $verificationStage = 'DOCKER_EXPORT'
    Expand-VerifiedMembers $dockerArchive $dockerDirectory @('manifest.json')
    $dockerManifestPath = Join-Path $dockerDirectory 'manifest.json'
    # PowerShell 5.1 does not enumerate the JSON outer array in a pipeline.
    $parsedDockerManifest = Get-Content -Raw -Encoding utf8 -LiteralPath $dockerManifestPath | ConvertFrom-Json
    $dockerEntries = @($parsedDockerManifest)
    if ($dockerEntries.Count -ne 1) { throw 'Docker archive must contain exactly one image' }
    $dockerEntry = $dockerEntries[0]
    $dockerLayers = @($dockerEntry.Layers)
    $dockerTags = @($dockerEntry.RepoTags)
    if ($dockerEntry.Config -cne $configMember -or $dockerTags.Count -ne 1 -or $dockerTags[0] -cne $imageTag -or $dockerLayers.Count -ne $layers.Count) { throw 'Docker archive config, tag or layer linkage is inconsistent' }
    Expand-VerifiedMembers $dockerArchive $dockerDirectory (@($configMember) + $dockerLayers)
    $dockerConfigPath = Join-Path $dockerDirectory ($configMember -replace '/', '\')
    if ((Get-Digest $dockerConfigPath) -cne $configDigest) { throw 'Docker archive config differs from OCI config' }
    Assert-Size $manifest.config.size $dockerConfigPath
    for ($i = 0; $i -lt $dockerLayers.Count; $i++) {
        $member = [string]$dockerLayers[$i]
        $path = Join-Path $dockerDirectory ($member -replace '/', '\')
        $digest = 'sha256:' + $member.Substring('blobs/sha256/'.Length)
        if ((Get-Digest $path) -cne $digest -or (Get-LayerDiffId $path '') -cne $diffIds[$i]) { throw 'Docker archive layer hash or rootfs linkage mismatch' }
        if ($digest -ceq $layers[$i].digest) { Assert-Size $layers[$i].size $path }
    }

    # Public registry metadata only: imagetools does not pull/load an image.
    $verificationStage = 'BASE_REGISTRY'
    $baseJson = Invoke-QuietNative 'docker' @('buildx', 'imagetools', 'inspect', '--format', '{{json .Image}}', $expectedBase) 'Unable to verify public base metadata'
    $base = $baseJson | ConvertFrom-Json
    $baseDiffIds = @($base.rootfs.diff_ids)
    if ($base.os -cne 'linux' -or $base.architecture -cne 'amd64' -or $base.rootfs.type -cne 'layers' -or
        $baseDiffIds.Count -lt 1 -or $baseDiffIds.Count -gt $diffIds.Count) { throw 'Public base platform or rootfs is inconsistent' }
    for ($i = 0; $i -lt $baseDiffIds.Count; $i++) {
        Assert-Digest ([string]$baseDiffIds[$i])
        if ($baseDiffIds[$i] -cne $diffIds[$i]) { throw 'Image rootfs does not preserve the fixed base prefix' }
    }

    $verificationStage = 'LOADED_IMAGE'
    $loadedId = (Invoke-QuietNative 'docker' @('image', 'inspect', '--format', '{{json .Id}}', $imageTag) 'Unable to inspect candidate image identity' | ConvertFrom-Json)
    if ($loadedId -ceq $configDigest) { $loadedIdentity = 'config_digest' }
    elseif ($loadedId -ceq $manifestDigest) { $loadedIdentity = 'manifest_digest' }
    else { throw 'Loaded image identity differs from candidate config and manifest' }
    $loadedOs = Invoke-QuietNative 'docker' @('image', 'inspect', '--format', '{{json .Os}}', $loadedId) 'Unable to inspect image OS' | ConvertFrom-Json
    $loadedArchitecture = Invoke-QuietNative 'docker' @('image', 'inspect', '--format', '{{json .Architecture}}', $loadedId) 'Unable to inspect image architecture' | ConvertFrom-Json
    $loadedUser = Invoke-QuietNative 'docker' @('image', 'inspect', '--format', '{{json .Config.User}}', $loadedId) 'Unable to inspect image user' | ConvertFrom-Json
    if ($loadedOs -cne 'linux' -or $loadedArchitecture -cne 'amd64' -or $loadedUser -cne $expectedUser) { throw 'Loaded image platform or user differs from OCI config' }
    $loadedLabels = Invoke-QuietNative 'docker' @('image', 'inspect', '--format', '{{json .Config.Labels}}', $loadedId) 'Unable to inspect image provenance labels' | ConvertFrom-Json
    Assert-Labels $loadedLabels
    $loadedRootfs = Invoke-QuietNative 'docker' @('image', 'inspect', '--format', '{{json .RootFS}}', $loadedId) 'Unable to inspect image rootfs' | ConvertFrom-Json
    $loadedDiffIds = @($loadedRootfs.Layers)
    if ($loadedRootfs.Type -cne 'layers' -or $loadedDiffIds.Count -ne $diffIds.Count) { throw 'Loaded rootfs layer count differs from OCI config' }
    for ($i = 0; $i -lt $diffIds.Count; $i++) {
        if ($loadedDiffIds[$i] -cne $diffIds[$i]) { throw 'Loaded image rootfs differs from OCI config' }
    }
    $verificationStage = 'SOURCE_MARKER'
    $marker = Invoke-QuietNative 'docker' @('run', '--pull', 'never', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--entrypoint', 'cat', $loadedId, '/opt/odoo/.tcc-source-commit') 'Unable to verify source marker in isolated image'
    if ($marker.Trim() -cne $expectedCommit) { throw 'Source marker differs from fixed Odoo revision' }

    $verificationStage = 'EVIDENCE'
    $evidence = [ordered]@{
        schemaVersion = 'odoo-artifact-verification/v1'; status = 'candidate-verified-not-selected'
        verifiedAt = (Get-Date).ToUniversalTime().ToString('o'); selectionAuthorized = $false
        sourceCommit = $expectedCommit; sourceRepository = $expectedRepository
        platform = $expectedPlatform; imageUser = $expectedUser; imageReference = $imageTag
        ociManifestDigest = $manifestDigest; configDigest = $configDigest
        loadedImageId = [string]$loadedId; loadedIdentityKind = $loadedIdentity
        dockerfileSha256 = $dockerfileSha256; baseReference = $expectedBase
        baseRootfsPrefixVerified = $true; baseRootfsDiffIds = $baseDiffIds
        sourceMarkerVerified = $true; layers = $layerEvidence
        metadataSha256 = (Get-Digest $metadataPath).Substring(7)
        ociArchiveSha256 = (Get-Digest $ociArchive).Substring(7)
        dockerArchiveSha256 = (Get-Digest $dockerArchive).Substring(7)
        dockerManifestSha256 = (Get-Digest $dockerManifestPath).Substring(7)
        ociArchiveBytes = (Get-Item -LiteralPath $ociArchive).Length
        dockerArchiveBytes = (Get-Item -LiteralPath $dockerArchive).Length
        limits = @('No lock selection or authorization performed', 'No historical smoke acceptance transferred', 'No bit-for-bit rebuild or remote publication demonstrated')
    }
    $evidencePath = Assert-Within (Join-Path $verificationRoot 'verification.json') $verificationRoot
    [IO.File]::WriteAllText($evidencePath, (($evidence | ConvertTo-Json -Depth 12) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
    Write-Host 'PASS: candidate bytes, Docker linkage, fixed base prefix and source marker verified.' -ForegroundColor Green
    Write-Host ('Evidence: .runtime/build/' + (Split-Path -Leaf $verificationRoot) + '/verification.json')
}
catch {
    # Native output, configuration/environment and raw archive JSON never escape.
    Write-Host ('FAIL at ' + $verificationStage + ': candidate verification incomplete; no selection or lock change performed.') -ForegroundColor Red
    throw 'Odoo artifact verification failed; preserved ignored verification files require local inspection'
}
