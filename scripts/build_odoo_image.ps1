$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Set-JsonProperty {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $false)]$Value
    )

    if ($null -ne $Object.PSObject.Properties[$Name]) {
        $Object.$Name = $Value
    }
    else {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Write-JsonFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )

    $json = $Value | ConvertTo-Json -Depth 20
    [System.IO.File]::WriteAllText(
        $Path,
        $json + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Test-BuildxBuilder {
    param([Parameter(Mandatory = $true)][string]$Name)

    $previousPreference = $ErrorActionPreference
    $exitCode = 1
    try {
        $ErrorActionPreference = 'SilentlyContinue'
        & docker buildx inspect $Name *> $null
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    return $exitCode -eq 0
}

function Assert-Sha256Digest {
    param(
        [Parameter(Mandatory = $true)][string]$Digest,
        [Parameter(Mandatory = $true)][string]$Description
    )

    if ($Digest -notmatch '^sha256:[0-9a-f]{64}$') {
        throw "$Description is absent or malformed"
    }
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$expectedCommit = 'a4b877245c9cb5e3d7152d1593a518170f115ca1'
$odooRepository = 'https://github.com/odoo/odoo.git'
$imageTag = 'tcc-odoo:19.0-a4b8772'
$platform = 'linux/amd64'
$builderName = 'tcc-oci-builder'
$pythonBaseReference = 'python:3.12-slim-bookworm@sha256:4427763a1ba36f5aa8f656a03e5d00f3b8d61f5dd950c73df6c14f8c7640f8ab'
$pythonBaseDigest = 'sha256:4427763a1ba36f5aa8f656a03e5d00f3b8d61f5dd950c73df6c14f8c7640f8ab'
$runtimeBuildDirectory = Join-Path $repositoryRoot '.runtime\build'
$metadataPath = Join-Path $runtimeBuildDirectory 'odoo-export-metadata.json'
$ociArchivePath = Join-Path $runtimeBuildDirectory 'odoo-image.oci.tar'
$dockerArchivePath = Join-Path $runtimeBuildDirectory 'odoo-image.docker.tar'
$verificationDirectory = $null

Push-Location $repositoryRoot
try {
    New-Item -ItemType Directory -Force -Path $runtimeBuildDirectory | Out-Null
    foreach ($generatedPath in @($metadataPath, $ociArchivePath, $dockerArchivePath)) {
        if (Test-Path -LiteralPath $generatedPath) {
            Remove-Item -LiteralPath $generatedPath -Force
        }
    }

    if (-not (Test-BuildxBuilder -Name $builderName)) {
        Write-Host "=== Creating isolated OCI builder: $builderName ===" -ForegroundColor Cyan
        & docker buildx create --name $builderName --driver docker-container
        if ($LASTEXITCODE -ne 0) { throw 'docker buildx create failed' }
    }

    & docker buildx inspect $builderName --bootstrap | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'docker buildx builder bootstrap failed' }

    Write-Host '=== Building Odoo and exporting OCI + Docker artifacts ===' -ForegroundColor Cyan
    & docker buildx build `
        --builder $builderName `
        --platform $platform `
        --file .\odoo\Dockerfile `
        --tag $imageTag `
        --build-arg "PYTHON_BASE_IMAGE=$pythonBaseReference" `
        --build-arg "ODOO_REPOSITORY=$odooRepository" `
        --build-arg "ODOO_COMMIT=$expectedCommit" `
        --provenance=false `
        --metadata-file $metadataPath `
        --output "type=oci,dest=$ociArchivePath" `
        --output "type=docker,dest=$dockerArchivePath" `
        .
    if ($LASTEXITCODE -ne 0) { throw 'docker buildx build failed' }

    foreach ($requiredPath in @($metadataPath, $ociArchivePath, $dockerArchivePath)) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            throw "BuildKit did not produce required artifact: $requiredPath"
        }
    }

    $metadata = Get-Content -Raw -Encoding utf8 -LiteralPath $metadataPath | ConvertFrom-Json
    $manifestDigest = [string]$metadata.'containerimage.digest'
    $configDigest = [string]$metadata.'containerimage.config.digest'
    $descriptor = $metadata.'containerimage.descriptor'
    Assert-Sha256Digest -Digest $manifestDigest -Description 'OCI manifest digest'
    Assert-Sha256Digest -Digest $configDigest -Description 'OCI config digest'
    if ($manifestDigest -eq $configDigest) {
        throw 'OCI manifest digest must be distinct from the image config digest'
    }
    if ([string]$descriptor.digest -ne $manifestDigest) {
        throw 'BuildKit descriptor digest does not match containerimage.digest'
    }
    if ([string]$descriptor.mediaType -ne 'application/vnd.oci.image.manifest.v1+json') {
        throw 'BuildKit did not export an OCI image manifest descriptor'
    }
    if ([string]$descriptor.platform.os -ne 'linux' -or [string]$descriptor.platform.architecture -ne 'amd64') {
        throw 'BuildKit descriptor platform is not linux/amd64'
    }

    # Verify the descriptor against the actual bytes in the local OCI layout.
    $manifestHex = $manifestDigest.Substring('sha256:'.Length)
    $configHex = $configDigest.Substring('sha256:'.Length)
    $manifestMember = "blobs/sha256/$manifestHex"
    $configMember = "blobs/sha256/$configHex"
    $verificationDirectory = Join-Path $runtimeBuildDirectory ('verify-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $verificationDirectory | Out-Null

    & tar -xf $ociArchivePath -C $verificationDirectory index.json $manifestMember $configMember
    if ($LASTEXITCODE -ne 0) { throw 'failed to extract OCI verification members' }

    $indexPath = Join-Path $verificationDirectory 'index.json'
    $manifestPath = Join-Path $verificationDirectory ($manifestMember -replace '/', '\')
    $configPath = Join-Path $verificationDirectory ($configMember -replace '/', '\')
    $actualManifestDigest = 'sha256:' + (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $actualConfigDigest = 'sha256:' + (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualManifestDigest -ne $manifestDigest) {
        throw 'OCI manifest bytes do not match the BuildKit descriptor digest'
    }
    if ($actualConfigDigest -ne $configDigest) {
        throw 'OCI config bytes do not match the BuildKit config digest'
    }

    $ociIndex = Get-Content -Raw -Encoding utf8 -LiteralPath $indexPath | ConvertFrom-Json
    $matchingDescriptors = @(
        $ociIndex.manifests | Where-Object {
            $_.digest -eq $manifestDigest -and
            $_.mediaType -eq 'application/vnd.oci.image.manifest.v1+json' -and
            $_.platform.os -eq 'linux' -and
            $_.platform.architecture -eq 'amd64'
        }
    )
    if ($matchingDescriptors.Count -ne 1) {
        throw 'OCI index does not contain exactly one matching linux/amd64 manifest'
    }

    $ociManifest = Get-Content -Raw -Encoding utf8 -LiteralPath $manifestPath | ConvertFrom-Json
    if ([string]$ociManifest.config.digest -ne $configDigest) {
        throw 'OCI manifest does not reference the exported config digest'
    }
    if ([int64]$ociManifest.config.size -ne (Get-Item -LiteralPath $configPath).Length) {
        throw 'OCI manifest config size does not match the exported config bytes'
    }

    Write-Host '=== Loading the Docker artifact from the same build resolution ===' -ForegroundColor Cyan
    & docker load --input $dockerArchivePath
    if ($LASTEXITCODE -ne 0) { throw 'docker load failed' }

    $inspect = @(docker image inspect $imageTag 2>&1)
    if ($LASTEXITCODE -ne 0) { throw 'docker image inspect failed' }
    $image = ($inspect -join [Environment]::NewLine | ConvertFrom-Json)[0]
    if ([string]$image.Id -ne $configDigest) {
        throw 'loaded Docker image config digest differs from the OCI artifact'
    }

    $labels = $image.Config.Labels
    if ($labels.'org.opencontainers.image.revision' -ne $expectedCommit) {
        throw 'Image revision label does not match the selected Odoo commit'
    }
    if ($labels.'org.opencontainers.image.source' -ne $odooRepository) {
        throw 'Image source label does not match the official Odoo repository'
    }
    if ($labels.'org.opencontainers.image.base.name' -ne $pythonBaseReference) {
        throw 'Image base label does not match the locked Python base image'
    }
    if ($labels.'br.edu.fci.tcc.platform' -ne $platform) {
        throw 'Image platform label does not match the laboratory platform'
    }
    if ($image.Os -ne 'linux' -or $image.Architecture -ne 'amd64') {
        throw 'Loaded image platform is not linux/amd64'
    }

    $commitEvidence = @(
        docker run --rm --entrypoint cat $imageTag /opt/odoo/.tcc-source-commit 2>&1
    ) -join ''
    if ($LASTEXITCODE -ne 0) { throw 'Failed to read source evidence from the image' }
    if ($commitEvidence.Trim() -ne $expectedCommit) {
        throw 'Source evidence inside the image does not match the selected commit'
    }

    $dockerfileHash = (Get-FileHash -LiteralPath .\odoo\Dockerfile -Algorithm SHA256).Hash.ToLowerInvariant()
    $builtAt = (Get-Date).ToUniversalTime().ToString('o')

    $labLockPath = Join-Path $repositoryRoot 'reproducibility\lab-environment.lock.json'
    $labLock = Get-Content -Raw -Encoding utf8 -LiteralPath $labLockPath | ConvertFrom-Json
    Set-JsonProperty $labLock 'status' 'odoo-image-built-m1-smoke-pending'
    Set-JsonProperty $labLock.components.odoo 'imageDigest' $manifestDigest
    Set-JsonProperty $labLock.components.odoo 'imageDigestKind' 'oci_manifest'
    Set-JsonProperty $labLock.components.odoo 'manifestMediaType' ([string]$descriptor.mediaType)
    Set-JsonProperty $labLock.components.odoo 'digestScope' 'local_buildkit_oci_layout_manifest'
    Set-JsonProperty $labLock.components.odoo 'localConfigDigest' $configDigest
    Set-JsonProperty $labLock.components.odoo 'buildStatus' 'built-and-source-verified'
    Set-JsonProperty $labLock.components.odoo 'buildPlatform' $platform
    Set-JsonProperty $labLock.components.odoo 'buildxBuilderDriver' 'docker-container'
    Set-JsonProperty $labLock.components.odoo 'dockerfileSha256' $dockerfileHash
    Set-JsonProperty $labLock.components.odoo 'builtAt' $builtAt
    Set-JsonProperty $labLock.components.odoo 'sourceCommitEvidencePath' '/opt/odoo/.tcc-source-commit'
    Set-JsonProperty $labLock 'pendingEvidence' @(
        'Smoke M1 com conta de fornecedor via JSON-2 e igualdade do hash após reset.'
    )
    Write-JsonFile $labLockPath $labLock

    $sourceLockPath = Join-Path $repositoryRoot 'reproducibility\odoo-source.lock.json'
    $sourceLock = Get-Content -Raw -Encoding utf8 -LiteralPath $sourceLockPath | ConvertFrom-Json
    Set-JsonProperty $sourceLock.image 'reference' $imageTag
    Set-JsonProperty $sourceLock.image 'oci_digest' $manifestDigest
    Set-JsonProperty $sourceLock.image 'digest_scope' 'local_buildkit_oci_layout_manifest'
    Set-JsonProperty $sourceLock.image 'manifest_media_type' ([string]$descriptor.mediaType)
    Set-JsonProperty $sourceLock.image 'local_config_digest' $configDigest
    Set-JsonProperty $sourceLock.image 'runtime_platform' $platform
    Set-JsonProperty $sourceLock.image 'dockerfile_sha256' $dockerfileHash
    Set-JsonProperty $sourceLock.image 'base_image_reference' $pythonBaseReference
    Set-JsonProperty $sourceLock.image 'base_image_oci_digest' $pythonBaseDigest
    Set-JsonProperty $sourceLock.image 'built_at' $builtAt
    Set-JsonProperty $sourceLock.image.source_image_linkage 'status' 'verified'
    Set-JsonProperty $sourceLock.image.source_image_linkage 'evidence' 'OCI manifest bytes, config digest, loaded image labels, and /opt/odoo/.tcc-source-commit verified'
    Set-JsonProperty $sourceLock.image 'status' 'built-and-source-verified'
    Write-JsonFile $sourceLockPath $sourceLock

    Write-Host '=== Odoo build verified ===' -ForegroundColor Green
    Write-Host "Image reference: $imageTag"
    Write-Host "OCI manifest digest: $manifestDigest"
    Write-Host "Local config digest: $configDigest"
    Write-Host "Source commit: $expectedCommit"
}
finally {
    if ($verificationDirectory) {
        $resolvedBuildDirectory = [System.IO.Path]::GetFullPath($runtimeBuildDirectory).TrimEnd('\') + '\'
        $resolvedVerificationDirectory = [System.IO.Path]::GetFullPath($verificationDirectory)
        $verificationLeaf = Split-Path -Leaf $resolvedVerificationDirectory
        if (
            $resolvedVerificationDirectory.StartsWith(
                $resolvedBuildDirectory,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -and
            $verificationLeaf -like 'verify-*' -and
            (Test-Path -LiteralPath $resolvedVerificationDirectory)
        ) {
            Remove-Item -LiteralPath $resolvedVerificationDirectory -Recurse -Force
        }
    }
    Pop-Location
}
