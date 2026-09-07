param(
    [switch]$RecreateVolumes,
    [switch]$KeepRunning
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-ComposeService {
    param([Parameter(Mandatory = $true)][string]$Service)

    $jsonLines = @(& docker compose ps --format json 2>$null)
    if ($LASTEXITCODE -ne 0) { return $null }
    $services = @(
        $jsonLines |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            ForEach-Object { $_ | ConvertFrom-Json }
    )
    return $services | Where-Object { $_.Service -eq $Service } | Select-Object -First 1
}

function Wait-ComposeHealth {
    param(
        [Parameter(Mandatory = $true)][string]$Service,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [int]$PollSeconds = 2
    )

    $elapsed = 0
    while ($elapsed -lt $TimeoutSeconds) {
        $status = Get-ComposeService -Service $Service
        if ($status -and $status.Health -eq 'healthy') {
            Write-Host "  $Service healthy after ${elapsed}s" -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds $PollSeconds
        $elapsed += $PollSeconds
    }
    throw "$Service did not become healthy within ${TimeoutSeconds}s"
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

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$runtimeDirectory = Join-Path $repositoryRoot '.runtime'
$secretsDirectory = Join-Path $runtimeDirectory 'secrets'
$evidenceDirectory = Join-Path $runtimeDirectory 'evidence'
$documentsDirectory = Join-Path $runtimeDirectory 'documents'
$evidencePath = Join-Path $evidenceDirectory 'm1-smoke.json'
$labLockPath = Join-Path $repositoryRoot 'reproducibility\lab-environment.lock.json'
$sourceLockPath = Join-Path $repositoryRoot 'reproducibility\odoo-source.lock.json'
$completed = $false

Push-Location $repositoryRoot
try {
    if (-not (Test-Path -LiteralPath '.env')) {
        Write-Host '=== Generating local environment ===' -ForegroundColor Cyan
        & powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\new_local_env.ps1
        if ($LASTEXITCODE -ne 0) { throw 'new_local_env.ps1 failed' }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $runtimeDirectory 'odoo.conf'))) {
        throw 'Missing .runtime/odoo.conf; rotate the local environment intentionally with new_local_env.ps1 -Force'
    }
    New-Item -ItemType Directory -Force -Path $secretsDirectory | Out-Null
    New-Item -ItemType Directory -Force -Path $evidenceDirectory | Out-Null
    New-Item -ItemType Directory -Force -Path $documentsDirectory | Out-Null
    if (Test-Path -LiteralPath $evidencePath) {
        Remove-Item -LiteralPath $evidencePath -Force
    }

    if ($RecreateVolumes) {
        Write-Host '=== Recreating only the tcc-odoo-lab synthetic volumes ===' -ForegroundColor Cyan
        $unexpectedVolumes = @(
            docker volume ls `
                --filter 'label=com.docker.compose.project=tcc-odoo-lab' `
                --format '{{.Name}}' 2>$null |
                Where-Object { $_ -and $_ -notlike 'tcc-odoo-lab_*' }
        )
        if ($unexpectedVolumes.Count -gt 0) {
            throw 'A volume with the project label is outside the expected tcc-odoo-lab_* namespace'
        }
        & docker compose down --volumes --remove-orphans
        if ($LASTEXITCODE -ne 0) { throw 'docker compose down --volumes failed' }
    }

    & powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_odoo_image.ps1
    if ($LASTEXITCODE -ne 0) { throw 'build_odoo_image.ps1 failed' }

    $sourceLock = Get-Content -Raw -Encoding utf8 -LiteralPath $sourceLockPath | ConvertFrom-Json
    if ($sourceLock.image.status -ne 'built-and-source-verified') {
        throw 'Odoo source lock is not verified; refusing to start a run'
    }
    if ([string]$sourceLock.image.oci_digest -notmatch '^sha256:[0-9a-f]{64}$') {
        throw 'Odoo manifest digest is absent or malformed; refusing to start a run'
    }

    Write-Host '=== Building and unit-testing the Python 3.12 gateway ===' -ForegroundColor Cyan
    & docker compose build gateway
    if ($LASTEXITCODE -ne 0) { throw 'gateway image build failed' }
    # A tag do gateway nao pode ser fixada aqui: ela avancou de 0.2.0 (M2) para
    # 0.3.0 (G3a), 0.4.0 (G3b) e 0.5.0 (G3c) sem que este script acompanhasse.
    # Com a tag fixa, o smoke testava uma imagem antiga quando ela ainda existia
    # localmente, e falhava em maquina limpa. A tag e resolvida do Compose, que e
    # a fonte de verdade do artefato construido logo acima.
    $gatewayImage = (& docker compose config --format json | ConvertFrom-Json).services.gateway.image
    if ($LASTEXITCODE -ne 0) { throw 'docker compose config failed' }
    if ([string]::IsNullOrWhiteSpace($gatewayImage)) {
        throw 'could not resolve the gateway image tag from the Compose configuration'
    }
    Write-Host ("Gateway image under test: {0}" -f $gatewayImage)
    & docker run --rm --entrypoint python $gatewayImage -m pytest -q -p no:cacheprovider /opt/tcc/gateway/tests
    if ($LASTEXITCODE -ne 0) { throw 'gateway unit tests failed' }

    Write-Host '=== Starting PostgreSQL 18 ===' -ForegroundColor Cyan
    & docker compose up -d db
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up db failed' }
    Wait-ComposeHealth -Service 'db' -TimeoutSeconds 90

    Write-Host '=== Initializing Odoo Community modules ===' -ForegroundColor Cyan
    & docker compose run --rm -T odoo python /opt/odoo/odoo-bin `
        -c /etc/odoo/odoo.conf `
        -d tcc_ap_lab `
        -i base,web,rpc,account,purchase `
        --without-demo=True `
        --stop-after-init `
        --no-http
    if ($LASTEXITCODE -ne 0) { throw 'Odoo module initialization failed' }

    Write-Host '=== Loading deterministic M1 fixtures and C0 identity ===' -ForegroundColor Cyan
    $bootstrapSource = Get-Content -Raw -Encoding utf8 -LiteralPath .\odoo\fixtures\bootstrap_m1.py
    # Canalizar uma string do PowerShell para um comando nativo a recodifica com
    # [Console]::OutputEncoding. No Windows PowerShell 5.1 isso prefixa um BOM e
    # transcodifica os acentos; como o `odoo shell` le o script por stdin, o
    # interpretador falha com "invalid non-printable character U+FEFF" antes de
    # executar qualquer fixture. Forcar UTF-8 sem BOM apenas ao redor do pipe, e
    # remover um BOM residual do proprio arquivo, torna o bootstrap independente
    # da edicao do PowerShell e da configuracao de console do host.
    $previousOutputEncoding = $OutputEncoding
    $previousConsoleEncoding = [Console]::OutputEncoding
    try {
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        $OutputEncoding = $utf8NoBom
        [Console]::OutputEncoding = $utf8NoBom
        $bootstrapSource = $bootstrapSource.TrimStart([char]0xFEFF)
        $bootstrapSource | & docker compose run --rm -T odoo python /opt/odoo/odoo-bin `
            shell `
            -c /etc/odoo/odoo.conf `
            -d tcc_ap_lab `
            --no-http
    }
    finally {
        $OutputEncoding = $previousOutputEncoding
        [Console]::OutputEncoding = $previousConsoleEncoding
    }
    if ($LASTEXITCODE -ne 0) { throw 'M1 fixture bootstrap failed' }
    if (-not (Test-Path -LiteralPath (Join-Path $secretsDirectory 'odoo_api_key'))) {
        throw 'C0 API key was not written to the ignored runtime secret path'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $secretsDirectory 'm1_fixture.json'))) {
        throw 'M1 fixture manifest was not written to the ignored runtime path'
    }

    Write-Host '=== Starting Odoo 19.0 ===' -ForegroundColor Cyan
    & docker compose up -d odoo
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up odoo failed' }
    Wait-ComposeHealth -Service 'odoo' -TimeoutSeconds 180 -PollSeconds 3

    Write-Host '=== Running M1 JSON-2 draft vendor bill smoke ===' -ForegroundColor Cyan
    & docker compose run --rm gateway
    if ($LASTEXITCODE -ne 0) { throw 'M1 JSON-2 gateway smoke failed' }
    if (-not (Test-Path -LiteralPath $evidencePath -PathType Leaf)) {
        throw 'M1 smoke did not produce its local evidence file'
    }

    $evidence = Get-Content -Raw -Encoding utf8 -LiteralPath $evidencePath | ConvertFrom-Json
    if ($evidence.status -ne 'pass') { throw 'M1 evidence status is not pass' }
    if ($evidence.synthetic_data -ne $true -or $evidence.fiscal_value -ne $false) {
        throw 'M1 evidence is not marked as synthetic and without fiscal value'
    }
    if ($evidence.initial_state_sha256 -ne $evidence.restored_state_sha256) {
        throw 'M1 reset hash differs from the initial hash'
    }
    if ($evidence.created_state_sha256 -eq $evidence.initial_state_sha256) {
        throw 'M1 created-state hash did not change after creating the draft bill'
    }

    $labLock = Get-Content -Raw -Encoding utf8 -LiteralPath $labLockPath | ConvertFrom-Json
    $labLock.status = 'm1-smoke-passed-pre-freeze'
    $labLock.m1Smoke.status = 'pass'
    $labLock.m1Smoke.initialStateSha256 = $evidence.initial_state_sha256
    $labLock.m1Smoke.createdStateSha256 = $evidence.created_state_sha256
    $labLock.m1Smoke.restoredStateSha256 = $evidence.restored_state_sha256
    $labLock.m1Smoke.completedAt = (Get-Date).ToUniversalTime().ToString('o')
    $labLock.pendingEvidence = @()
    Write-JsonFile $labLockPath $labLock

    $completed = $true
    Write-Host '=== M1 smoke PASSED ===' -ForegroundColor Green
    Write-Host "Initial/restored state: $($evidence.initial_state_sha256)"
    Write-Host "Created state:          $($evidence.created_state_sha256)"
}
catch {
    Write-Host '=== M1 smoke FAILED ===' -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    throw
}
finally {
    if (-not $KeepRunning) {
        $previousPreference = $ErrorActionPreference
        $shutdownExitCode = 1
        try {
            $ErrorActionPreference = 'SilentlyContinue'
            & docker compose down --remove-orphans *> $null
            $shutdownExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousPreference
        }
        if ($shutdownExitCode -ne 0) {
            Write-Warning 'Best-effort container shutdown failed; inspect docker compose ps.'
        }
    }
    Pop-Location
}

if (-not $completed) {
    exit 1
}
