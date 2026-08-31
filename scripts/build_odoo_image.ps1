$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repositoryRoot

try {
    $expectedCommit = 'a4b877245c9cb5e3d7152d1593a518170f115ca1'

    if (-not (Test-Path -LiteralPath '.env')) {
        Write-Host '=== Generating local environment ===' -ForegroundColor Cyan
        & powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\new_local_env.ps1
        if ($LASTEXITCODE -ne 0) { throw 'new_local_env.ps1 failed' }
    }

    Write-Host '=== Building Odoo image ===' -ForegroundColor Cyan
    & docker compose build --progress=plain odoo
    if ($LASTEXITCODE -ne 0) { throw 'docker compose build failed' }

    $imageTag = 'tcc-odoo:19.0-a4b8772'
    Write-Host "=== Inspecting image $imageTag ===" -ForegroundColor Cyan

    # Extract OCI labels
    $inspectJson = docker inspect --format '{{json .Config.Labels}}' $imageTag 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'docker inspect failed' }
    $labels = $inspectJson | ConvertFrom-Json

    $revisionLabel = $labels.'org.opencontainers.image.revision'
    if ($revisionLabel -ne $expectedCommit) {
        throw "Image revision label '$revisionLabel' does not match expected commit '$expectedCommit'"
    }
    Write-Host "  revision label: PASS ($revisionLabel)" -ForegroundColor Green

    # Get image digest (local ID; the real OCI content-addressable digest requires push)
    $imageId = (docker inspect --format '{{.Id}}' $imageTag 2>&1).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'docker inspect for ID failed' }
    Write-Host "  image ID: $imageId" -ForegroundColor Gray

    # Update lab-environment.lock.json
    $lockPath = Join-Path $repositoryRoot 'reproducibility\lab-environment.lock.json'
    $lock = Get-Content -Raw -Encoding utf8 -LiteralPath $lockPath | ConvertFrom-Json
    $lock.components.odoo.imageDigest = $imageId
    $lock.components.odoo.buildStatus = 'built-locally'
    $lock.status = 'images-locked'

    $lockJson = $lock | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($lockPath, $lockJson, [System.Text.UTF8Encoding]::new($false))
    Write-Host '  lab-environment.lock.json updated' -ForegroundColor Green

    # Verify source commit evidence inside image
    Write-Host '=== Verifying source commit evidence inside image ===' -ForegroundColor Cyan
    $commitEvidence = docker run --rm --entrypoint cat $imageTag /opt/odoo/.tcc-source-commit 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'Failed to read .tcc-source-commit from image' }
    $commitEvidence = $commitEvidence.Trim()
    if ($commitEvidence -ne $expectedCommit) {
        throw "Source commit evidence '$commitEvidence' does not match expected '$expectedCommit'"
    }
    Write-Host "  source commit evidence: PASS" -ForegroundColor Green

    Write-Host "`n=== Build complete ===" -ForegroundColor Green
    Write-Host "Image: $imageTag"
    Write-Host "ID:    $imageId"
    Write-Host "Commit: $expectedCommit (verified)"
}
finally {
    Pop-Location
}
