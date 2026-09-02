param()

$ErrorActionPreference = 'Stop'

$repoRoot = (& git rev-parse --show-toplevel 2>$null).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repoRoot)) {
    throw 'Execute este script dentro do repositório Git.'
}

$projectName = 'tcc-g3b-offline'
$composePrefix = @(
    'compose',
    '--project-name', $projectName,
    '--env-file', (Join-Path $repoRoot '.env.example'),
    '--profile', 'g3b'
)
$servicesStarted = $false

Push-Location $repoRoot
try {
    & python .\scripts\test_g3b_topology.py
    if ($LASTEXITCODE -ne 0) { throw 'A validação estática da topologia G3b falhou.' }

    & docker @composePrefix build llm-client egress-proxy
    if ($LASTEXITCODE -ne 0) { throw 'O build das imagens G3b falhou.' }

    & docker run --rm --network none --read-only --tmpfs '/tmp:size=64m,mode=1777' `
        tcc-gateway:0.5.0 python -m pytest -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'A suíte do gateway/llm-client falhou.' }

    & docker run --rm --network none --read-only --tmpfs '/tmp:size=32m,mode=1777' `
        tcc-egress-proxy:0.1.0 python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'A suíte do proxy de egress falhou.' }

    & docker @composePrefix up -d --wait egress-proxy llm-client
    if ($LASTEXITCODE -ne 0) { throw 'Os serviços offline de G3b não ficaram saudáveis.' }
    $servicesStarted = $true

    & docker @composePrefix exec -T llm-client python -m tcc_gateway.g3b_probe
    if ($LASTEXITCODE -ne 0) { throw 'O probe runtime offline de G3b falhou.' }

    $logs = (& docker @composePrefix logs --no-color egress-proxy llm-client 2>&1) -join "`n"
    $forbiddenLogMarkers = @(
        '(?i)authorization\s*:',
        '(?i)bearer\s+',
        '(?i)api[_-]?key',
        'DOCUMENTO SINTETICO',
        'SENSITIVE-'
    )
    foreach ($marker in $forbiddenLogMarkers) {
        if ($logs -match $marker) {
            throw 'Os logs G3b contêm uma classe de conteúdo proibida.'
        }
    }

    Write-Host 'G3b offline safety smoke: PASS (no provider call, no secret, no model download)' -ForegroundColor Green
}
finally {
    if ($servicesStarted) {
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        & docker @composePrefix down --remove-orphans 2>$null | Out-Null
        $ErrorActionPreference = $previousPreference
    }
    Pop-Location
}
