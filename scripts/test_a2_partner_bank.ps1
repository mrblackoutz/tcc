param(
    [switch]$KeepRunning
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# T-A2-PREFREEZE, exigido pelo §8.2 item 6 do plano-mestre sob DEC-022 (achado ODO-02).
# Semeia contas bancarias adversariais com a identidade administrativa, exercita
# `account.move.partner_bank_id` com a identidade C0 via JSON-2 e remove o que criou.

$repositoryRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repositoryRoot
try {
    Write-Host '=== Starting PostgreSQL and Odoo ===' -ForegroundColor Cyan
    & docker compose up -d db odoo
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed' }

    $deadline = (Get-Date).AddSeconds(180)
    do {
        Start-Sleep -Seconds 3
        $state = (& docker compose ps --format json odoo | ConvertFrom-Json)
        $health = if ($state) { [string]$state.Health } else { '' }
        if ((Get-Date) -gt $deadline) { throw 'Odoo did not become healthy in time' }
    } while ($health -ne 'healthy')
    Write-Host 'Odoo is healthy'

    # O `odoo shell` le o script por stdin. O redirecionamento por cmd entrega os
    # bytes crus do arquivo, sem a recodificacao que o PowerShell aplicaria ao
    # canalizar uma string e que prefixaria um BOM.
    function Invoke-OdooShellScript {
        param([Parameter(Mandatory = $true)][string]$RelativePath)

        $fullPath = (Resolve-Path -LiteralPath $RelativePath).Path
        if ([System.IO.File]::ReadAllBytes($fullPath)[0..2] -join ',' -eq '239,187,191') {
            throw "$RelativePath has a UTF-8 BOM; remove it before running the lab"
        }
        $command = (
            'docker compose run --rm -T odoo python /opt/odoo/odoo-bin shell' +
            ' -c /etc/odoo/odoo.conf -d tcc_ap_lab --no-http < "' + $fullPath + '"'
        )
        & cmd /c $command
        if ($LASTEXITCODE -ne 0) { throw "$RelativePath failed" }
    }

    Write-Host '=== Seeding adversarial synthetic bank accounts (admin identity) ===' -ForegroundColor Cyan
    Invoke-OdooShellScript -RelativePath '.\odoo\fixtures\a2_probe_setup.py'

    Write-Host '=== Running T-A2-PREFREEZE with the C0 identity over JSON-2 ===' -ForegroundColor Cyan
    $probeFailed = $false
    try {
        & docker compose run --rm gateway python /opt/tcc/scripts/test_a2_partner_bank.py
        if ($LASTEXITCODE -ne 0) { $probeFailed = $true }
    }
    catch {
        $probeFailed = $true
        Write-Host ("probe raised: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
    }

    Write-Host '=== Removing the adversarial synthetic fixtures ===' -ForegroundColor Cyan
    Invoke-OdooShellScript -RelativePath '.\odoo\fixtures\a2_probe_teardown.py'

    if ($probeFailed) { throw 'T-A2-PREFREEZE probe failed' }
    Write-Host '=== T-A2-PREFREEZE COMPLETED ===' -ForegroundColor Green
}
finally {
    if (-not $KeepRunning) {
        Write-Host '=== Stopping services and preserving volumes ===' -ForegroundColor Cyan
        & docker compose stop odoo db | Out-Null
    }
    Pop-Location
}
