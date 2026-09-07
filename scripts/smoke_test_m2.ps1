param(
    [switch]$KeepRunning
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

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
$documentsDirectory = Join-Path $runtimeDirectory 'documents'
$evidenceDirectory = Join-Path $runtimeDirectory 'evidence'
$documentPath = Join-Path $documentsDirectory 'm2-benign-001.pdf'
$evidencePath = Join-Path $evidenceDirectory 'm2-smoke.json'
$labLockPath = Join-Path $repositoryRoot 'reproducibility\lab-environment.lock.json'
$completed = $false

Push-Location $repositoryRoot
try {
    New-Item -ItemType Directory -Force -Path $documentsDirectory | Out-Null
    New-Item -ItemType Directory -Force -Path $evidenceDirectory | Out-Null
    if (Test-Path -LiteralPath $documentPath) {
        Remove-Item -LiteralPath $documentPath -Force
    }
    if (Test-Path -LiteralPath $evidencePath) {
        Remove-Item -LiteralPath $evidencePath -Force
    }

    Write-Host '=== Revalidating M1 prerequisites without deleting volumes ===' -ForegroundColor Cyan
    & powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\smoke_test.ps1 -KeepRunning
    if ($LASTEXITCODE -ne 0) { throw 'M1 prerequisite smoke failed' }

    Write-Host '=== Running M2 PDF-to-C0-draft vertical slice ===' -ForegroundColor Cyan
    & docker compose run --rm gateway python /opt/tcc/scripts/smoke_test_m2.py
    if ($LASTEXITCODE -ne 0) { throw 'M2 gateway smoke failed' }
    if (-not (Test-Path -LiteralPath $evidencePath -PathType Leaf)) {
        throw 'M2 smoke did not produce its local evidence file'
    }

    $evidence = Get-Content -Raw -Encoding utf8 -LiteralPath $evidencePath | ConvertFrom-Json
    if ($evidence.status -ne 'pass' -or $evidence.milestone -ne 'M2') {
        throw 'M2 evidence status or milestone is invalid'
    }
    if ($evidence.synthetic_data -ne $true -or $evidence.fiscal_value -ne $false) {
        throw 'M2 evidence is not marked as synthetic and without fiscal value'
    }
    if ($evidence.scientific_baseline -ne $false) {
        throw 'M2 deterministic flow must not be marked as the scientific baseline'
    }
    if ($evidence.adapter.allowed_for_scientific_runs -ne $false) {
        throw 'M2 deterministic adapter must be prohibited from scientific runs'
    }
    if ($evidence.initial_state_sha256 -ne $evidence.restored_state_sha256) {
        throw 'M2 reset hash differs from the initial hash'
    }
    if ($evidence.created_state_sha256 -eq $evidence.initial_state_sha256) {
        throw 'M2 created-state hash did not change after creating the draft bill'
    }
    if ($evidence.document.sha256 -notmatch '^[0-9a-f]{64}$') {
        throw 'M2 document digest is malformed'
    }
    if ($evidence.proposal.sha256 -notmatch '^[0-9a-f]{64}$') {
        throw 'M2 proposal digest is malformed'
    }

    $labLock = Get-Content -Raw -Encoding utf8 -LiteralPath $labLockPath | ConvertFrom-Json
    $labLock.status = 'm2-smoke-passed-pre-freeze'
    # A versao do gateway nao pode ser fixada aqui: fixada em 0.2.0, esta linha
    # gravava no lock uma versao diferente da efetivamente testada, que avancou
    # para 0.5.0 em G3c. O Compose e a fonte de verdade do artefato construido.
    $composedGatewayImage = (& docker compose config --format json | ConvertFrom-Json).services.gateway.image
    if ([string]::IsNullOrWhiteSpace($composedGatewayImage)) {
        throw 'could not resolve the gateway image tag from the Compose configuration'
    }
    $labLock.components.gateway.localImageTag = $composedGatewayImage
    $labLock.components.gateway.version = ($composedGatewayImage -split ':')[-1]
    $m2Smoke = [ordered]@{
        status = 'pass'
        scenarioId = [string]$evidence.scenario_id
        adapterId = [string]$evidence.adapter.id
        scientificBaseline = $false
        documentSha256 = [string]$evidence.document.sha256
        textSha256 = [string]$evidence.document.text_sha256
        proposalSha256 = [string]$evidence.proposal.sha256
        initialStateSha256 = [string]$evidence.initial_state_sha256
        createdStateSha256 = [string]$evidence.created_state_sha256
        restoredStateSha256 = [string]$evidence.restored_state_sha256
        invariantsAllPassed = (@($evidence.invariants.PSObject.Properties | Where-Object { -not $_.Value }).Count -eq 0)
        completedAt = (Get-Date).ToUniversalTime().ToString('o')
    }

    # Mesclar, nao substituir. Substituir o no inteiro apagava campos gravados por
    # versoes anteriores do script que esta execucao nao sabe gerar, como a
    # contagem de testes e o hash do schema da proposta. Evidencia que nao pode
    # ser regenerada nao deve ser silenciosamente descartada.
    if ($labLock.PSObject.Properties['m2Smoke'] -and $null -ne $labLock.m2Smoke) {
        # `unitTestsPassed` nao e herdado: a contagem verdadeira passa a viver em
        # components.gateway, escrita pela execucao que rodou a suite. Herdar aqui
        # perpetuaria um numero de uma suite que ja mudou de tamanho.
        $naoHerdar = @('unitTestsPassed')
        foreach ($previous in $labLock.m2Smoke.PSObject.Properties) {
            if ((-not $m2Smoke.Contains($previous.Name)) -and ($naoHerdar -notcontains $previous.Name)) {
                $m2Smoke[$previous.Name] = $previous.Value
            }
        }
    }
    $labLock | Add-Member -NotePropertyName m2Smoke -NotePropertyValue $m2Smoke -Force

    # Nao sobrescrever pendingEvidence com uma lista fixa: a que estava aqui era
    # anterior a DEC-018 e apagava o estado real das pendencias a cada execucao.
    # As pendencias sao normativas e vivem no plano e no decision log; o lock
    # aponta para elas em vez de duplica-las.
    $labLock.pendingEvidence = @(
        'Pendencias normativas de G3c, C0 cientifico competente, C1, dataset, piloto e freeze estao no plano-mestre e em docs/decision-log.md; este lock registra somente evidencia executada.'
    )
    Write-JsonFile $labLockPath $labLock

    $completed = $true
    Write-Host '=== M2 smoke PASSED ===' -ForegroundColor Green
    Write-Host "Document:               $($evidence.document.sha256)"
    Write-Host "Proposal:               $($evidence.proposal.sha256)"
    Write-Host "Initial/restored state: $($evidence.initial_state_sha256)"
    Write-Host "Created state:          $($evidence.created_state_sha256)"
}
catch {
    Write-Host '=== M2 smoke FAILED ===' -ForegroundColor Red
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
