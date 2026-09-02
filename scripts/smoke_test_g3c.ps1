param(
    [switch]$ConfirmRealCall,
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

if (-not $ConfirmRealCall) {
    throw 'G3c realiza uma chamada real. Execute novamente com -ConfirmRealCall apos autorizacao operacional.'
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$projectName = 'tcc-g3c-deepseek'
$composePrefix = @(
    'compose',
    '--project-name', $projectName,
    '--env-file', (Join-Path $repositoryRoot '.env.example'),
    '--profile', 'g3c'
)
$keyPath = Join-Path $repositoryRoot '.runtime\secrets\deepseek_api_key'
$evidenceDirectory = Join-Path $repositoryRoot '.runtime\evidence'
$evidencePath = Join-Path $evidenceDirectory 'g3c-deepseek-smoke.json'
$attemptPath = Join-Path $evidenceDirectory 'g3c-deepseek-smoke.attempt.json'
$servicesStarted = $false
$attemptStarted = $false

Push-Location $repositoryRoot
try {
    if (-not (Test-Path -LiteralPath $keyPath -PathType Leaf)) {
        throw 'A chave DeepSeek local nao foi encontrada no caminho ignorado esperado.'
    }
    $keyItem = Get-Item -LiteralPath $keyPath
    if ($keyItem.Length -lt 20) {
        throw 'O arquivo local da chave DeepSeek esta vazio ou estruturalmente invalido.'
    }
    & git check-ignore --quiet -- $keyPath
    if ($LASTEXITCODE -ne 0) {
        throw 'A chave DeepSeek nao esta coberta pelo ignore do repositorio.'
    }

    New-Item -ItemType Directory -Force -Path $evidenceDirectory | Out-Null
    if (Test-Path -LiteralPath $evidencePath) {
        throw 'Ja existe evidencia G3c local; o script recusa uma segunda chamada automatica.'
    }
    if (Test-Path -LiteralPath $attemptPath) {
        throw 'Ja existe marcador de tentativa G3c; revise a tentativa antes de autorizar qualquer nova chamada.'
    }

    $worktreeStatus = (& git status --porcelain --untracked-files=normal) -join "`n"
    if (-not [string]::IsNullOrWhiteSpace($worktreeStatus)) {
        throw 'G3c exige arvore Git limpa para vincular a chamada ao commit implementado.'
    }
    $gitCommit = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $gitCommit -notmatch '^[0-9a-f]{40}$') {
        throw 'Nao foi possivel fixar o commit da implementacao G3c.'
    }

    & python .\scripts\test_g3c_topology.py
    if ($LASTEXITCODE -ne 0) { throw 'A validacao estatica da topologia G3c falhou.' }

    & docker @composePrefix build llm-client-g3c g3c-runner egress-proxy
    if ($LASTEXITCODE -ne 0) { throw 'O build das imagens G3c falhou.' }

    & docker run --rm --network none --read-only --tmpfs '/tmp:size=64m,mode=1777' `
        tcc-gateway:0.5.0 python -m pytest -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'A suite offline do gateway/llm-client G3c falhou.' }

    & docker run --rm --network none --read-only --tmpfs '/tmp:size=32m,mode=1777' `
        tcc-egress-proxy:0.1.0 python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'A suite offline do proxy G3c falhou.' }

    & docker @composePrefix up -d --wait egress-proxy llm-client-g3c
    if ($LASTEXITCODE -ne 0) { throw 'O proxy e o llm-client G3c nao ficaram saudaveis.' }
    $servicesStarted = $true

    $attempt = [ordered]@{
        schema_version = 'g3c-deepseek-attempt/v1'
        status = 'started-call-outcome-unknown-until-evidence-validation'
        task_id = 'G3-05'
        implementation_git_commit = $gitCommit
        started_at_utc = (Get-Date).ToUniversalTime().ToString('o')
        automatic_retry_allowed = $false
    }
    Write-JsonFile -Path $attemptPath -Value $attempt
    $attemptStarted = $true

    # Docker Compose escreve progresso normal em stderr. Com ErrorActionPreference
    # Stop, o Windows PowerShell 5.1 pode promover essa linha a erro terminante e
    # interromper um container que acabou de iniciar. Capture com Continue e use
    # exclusivamente o exit code nativo para decidir o resultado.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $runnerOutput = (& docker @composePrefix run --rm --no-deps `
            -e "TCC_GIT_COMMIT=$gitCommit" g3c-runner 2>&1) -join "`n"
        $runnerExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($runnerExitCode -ne 0) {
        $proxyLogsAfterFailure = (& docker @composePrefix logs --no-color egress-proxy 2>&1) -join "`n"
        $attempt.runner_exit_code = $runnerExitCode
        $attempt.proxy_allow_events = [regex]::Matches(
            $proxyLogsAfterFailure,
            'proxy_event=allow'
        ).Count
        foreach ($line in ($runnerOutput -split "`r?`n")) {
            if ($line.TrimStart().StartsWith('{')) {
                try {
                    $runnerStatus = $line | ConvertFrom-Json
                    if ($runnerStatus.status -eq 'error' -and `
                        $runnerStatus.category -match '^[a-z0-9_]+$') {
                        $attempt.runner_error_category = [string]$runnerStatus.category
                    }
                }
                catch {
                    # Linhas de progresso nao JSON nao alteram a evidencia saneada.
                }
            }
        }
        $attempt.status = 'failed-or-call-outcome-uncertain-no-automatic-retry'
        $attempt.completed_at_utc = (Get-Date).ToUniversalTime().ToString('o')
        Write-JsonFile -Path $attemptPath -Value $attempt
        throw 'O runner G3c falhou; nenhuma repeticao automatica foi realizada.'
    }
    if (-not (Test-Path -LiteralPath $evidencePath -PathType Leaf)) {
        $attempt.status = 'call-outcome-uncertain-evidence-missing-no-automatic-retry'
        $attempt.completed_at_utc = (Get-Date).ToUniversalTime().ToString('o')
        Write-JsonFile -Path $attemptPath -Value $attempt
        throw 'O runner terminou sem evidencia; nenhuma repeticao automatica foi realizada.'
    }

    $evidenceText = Get-Content -Raw -Encoding utf8 -LiteralPath $evidencePath
    $evidence = $evidenceText | ConvertFrom-Json
    if ($evidence.schema_version -ne 'g3c-deepseek-smoke/v1' -or $evidence.status -ne 'pass') {
        throw 'A evidencia G3c possui schema ou status invalido.'
    }
    if ($evidence.real_provider_calls -ne 1 -or $evidence.retry_count -ne 0) {
        throw 'A evidencia G3c nao comprova exatamente uma chamada e zero retries.'
    }
    if ($evidence.scientific_run -ne $false) {
        throw 'O smoke G3c nao pode ser classificado como run cientifica.'
    }
    if ($evidence.synthetic_data -ne $true -or $evidence.fiscal_value -ne $false) {
        throw 'A evidencia G3c nao esta marcada como sintetica e sem valor fiscal.'
    }
    if ($evidence.implementation_git_commit -ne $gitCommit) {
        throw 'O commit da evidencia G3c diverge da arvore executada.'
    }
    if ($evidence.provider.name -ne 'deepseek') {
        throw 'A evidencia G3c identifica provedor inesperado.'
    }
    if ($evidence.provider.requested_model -ne 'deepseek-v4-flash') {
        throw 'A evidencia G3c identifica alias solicitado inesperado.'
    }
    if ($evidence.provider.thinking -ne 'disabled' -or $evidence.provider.temperature -ne 0) {
        throw 'A evidencia G3c diverge dos parametros nucleares pre-piloto.'
    }
    if ($evidence.provider.response_id -notmatch '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$') {
        throw 'A evidencia G3c nao possui request ID saneado.'
    }
    if ($evidence.hashes.request_sha256 -notmatch '^[0-9a-f]{64}$' -or `
        $evidence.hashes.response_body_sha256 -notmatch '^[0-9a-f]{64}$' -or `
        $evidence.hashes.proposal_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw 'A evidencia G3c contem hash ausente ou malformado.'
    }
    if ($evidence.latency_ns.adapter_total -le 0 -or $evidence.latency_ns.runner_wall_total -le 0) {
        throw 'A evidencia G3c nao possui latencia positiva.'
    }

    $proxyLogs = (& docker @composePrefix logs --no-color egress-proxy 2>&1) -join "`n"
    $clientLogs = (& docker @composePrefix logs --no-color llm-client-g3c 2>&1) -join "`n"
    $combinedInspectable = $runnerOutput + "`n" + $proxyLogs + "`n" + $clientLogs + "`n" + $evidenceText
    $keyValue = [System.IO.File]::ReadAllText($keyPath).Trim()
    if ([string]::IsNullOrWhiteSpace($keyValue) -or $combinedInspectable.Contains($keyValue)) {
        throw 'A varredura G3c detectou segredo ou chave local invalida.'
    }
    $forbiddenLogMarkers = @(
        '(?i)authorization\s*:',
        '(?i)bearer\s+',
        'DOCUMENTO SINTETICO',
        '(?i)vendor_ref',
        'SENSITIVE-'
    )
    foreach ($marker in $forbiddenLogMarkers) {
        if ($combinedInspectable -match $marker) {
            throw 'A varredura G3c detectou uma classe proibida em log ou evidencia.'
        }
    }
    $allowedTunnelCount = [regex]::Matches($proxyLogs, 'proxy_event=allow').Count
    if ($allowedTunnelCount -ne 1) {
        throw 'O proxy G3c nao registrou exatamente um tunel permitido.'
    }

    $evidenceSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $evidencePath).Hash.ToLowerInvariant()
    $attempt.status = 'completed-pass'
    $attempt.completed_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    $attempt.evidence_sha256 = $evidenceSha256
    Write-JsonFile -Path $attemptPath -Value $attempt

    Write-Host 'G3c DeepSeek safety smoke: PASS' -ForegroundColor Green
    Write-Host 'Real provider calls: 1; retries: 0; raw request/response persisted: false'
    Write-Host "Requested model: $($evidence.provider.requested_model)"
    Write-Host "Returned model:  $($evidence.provider.returned_model)"
    Write-Host "Evidence SHA-256: $evidenceSha256"
}
catch {
    if ($attemptStarted -and (Test-Path -LiteralPath $attemptPath)) {
        Write-Warning 'Uma tentativa G3c foi iniciada. Nao execute novamente sem revisar o marcador local.'
    }
    Write-Host 'G3c DeepSeek safety smoke: FAILED' -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    throw
}
finally {
    if ($servicesStarted -and -not $KeepRunning) {
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = 'SilentlyContinue'
        & docker @composePrefix down --remove-orphans *> $null
        $ErrorActionPreference = $previousPreference
    }
    Pop-Location
}
