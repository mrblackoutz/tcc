$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repositoryRoot

try {
    # ---------------------------------------------------------------
    # 1. Ensure local environment exists
    # ---------------------------------------------------------------
    if (-not (Test-Path -LiteralPath '.env')) {
        Write-Host '=== Generating local environment ===' -ForegroundColor Cyan
        & powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\new_local_env.ps1
        if ($LASTEXITCODE -ne 0) { throw 'new_local_env.ps1 failed' }
    }

    # ---------------------------------------------------------------
    # 2. Ensure image is built
    # ---------------------------------------------------------------
    $imageExists = docker image inspect tcc-odoo:19.0-a4b8772 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host '=== Image not found, building... ===' -ForegroundColor Yellow
        & powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_odoo_image.ps1
        if ($LASTEXITCODE -ne 0) { throw 'build_odoo_image.ps1 failed' }
    }
    else {
        Write-Host '=== Image verified (tcc-odoo:19.0-a4b8772) ===' -ForegroundColor Green
    }

    # ---------------------------------------------------------------
    # 3. Start database service and wait for readiness
    # ---------------------------------------------------------------
    Write-Host '=== Starting PostgreSQL 18 service ===' -ForegroundColor Cyan
    & docker compose up -d db
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up db failed' }

    $maxWait = 60
    $elapsed = 0
    while ($elapsed -lt $maxWait) {
        $health = docker compose ps --format json 2>$null | ConvertFrom-Json | Where-Object { $_.Service -eq 'db' }
        if ($health -and $health.Health -eq 'healthy') {
            Write-Host "  PostgreSQL 18 healthy after ${elapsed}s" -ForegroundColor Green
            break
        }
        Start-Sleep -Seconds 2
        $elapsed += 2
    }
    if ($elapsed -ge $maxWait) { throw "PostgreSQL did not become healthy within ${maxWait}s" }

    # ---------------------------------------------------------------
    # 4. Initialize database with required modules
    # ---------------------------------------------------------------
    Write-Host '=== Initializing database modules (base, l10n_generic_coa, account, purchase) ===' -ForegroundColor Cyan
    & docker compose run --rm -T odoo python /opt/odoo/odoo-bin `
        -c /etc/odoo/odoo.conf `
        -d tcc_ap_lab `
        -i base,l10n_generic_coa,account,purchase `
        --stop-after-init `
        --no-http
    if ($LASTEXITCODE -ne 0) { throw 'Module initialization failed' }
    Write-Host '  Modules initialized successfully' -ForegroundColor Green

    # ---------------------------------------------------------------
    # 5. Start Odoo web server and wait for healthcheck
    # ---------------------------------------------------------------
    Write-Host '=== Starting Odoo 19.0 web service ===' -ForegroundColor Cyan
    & docker compose up -d odoo
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up odoo failed' }

    $maxWait = 120
    $elapsed = 0
    while ($elapsed -lt $maxWait) {
        $health = docker compose ps --format json 2>$null | ConvertFrom-Json | Where-Object { $_.Service -eq 'odoo' }
        if ($health -and $health.Health -eq 'healthy') {
            Write-Host "  Odoo 19.0 healthy after ${elapsed}s" -ForegroundColor Green
            break
        }
        Start-Sleep -Seconds 3
        $elapsed += 3
    }
    if ($elapsed -ge $maxWait) { throw "Odoo did not become healthy within ${maxWait}s" }

    # ---------------------------------------------------------------
    # 6. Verify /web/health HTTP endpoint
    # ---------------------------------------------------------------
    Write-Host '=== Testing /web/health HTTP endpoint ===' -ForegroundColor Cyan
    $healthResponse = Invoke-RestMethod -Uri 'http://127.0.0.1:8069/web/health' -Method Get
    if ($healthResponse.status -ne 'pass') {
        throw "Health check failed: $($healthResponse | ConvertTo-Json)"
    }
    Write-Host '  /web/health: PASS (status=pass)' -ForegroundColor Green

    # ---------------------------------------------------------------
    # 7. Generate API key for admin user inside container
    # ---------------------------------------------------------------
    Write-Host '=== Generating RPC API key for admin ===' -ForegroundColor Cyan
    & docker compose exec -T odoo python -c "
import odoo
from odoo.tools import config
from odoo.modules.registry import Registry
from odoo import api, SUPERUSER_ID
config.parse_config(['-c', '/etc/odoo/odoo.conf', '-d', 'tcc_ap_lab'])
reg = Registry('tcc_ap_lab')
with reg.cursor() as cr:
    env = api.Environment(cr, SUPERUSER_ID, {})
    admin = env.ref('base.user_admin')
    key = env['res.users.apikeys'].with_user(admin)._generate(scope='rpc', name='tcc-smoke-test', expiration_date=None)
    cr.commit()
    with open('/run/tcc-secrets/odoo_api_key', 'w', encoding='utf-8') as f:
        f.write(key)
"
    if ($LASTEXITCODE -ne 0) { throw 'API key generation failed' }
    Write-Host '  API key generated and mounted into secrets' -ForegroundColor Green

    # ---------------------------------------------------------------
    # 8. Test JSON-2 client (search_read, create, read back)
    # ---------------------------------------------------------------
    Write-Host '=== Testing JSON-2 transport with tcc_gateway client ===' -ForegroundColor Cyan
    & python .\scripts\smoke_test_gateway.py
    if ($LASTEXITCODE -ne 0) { throw 'JSON-2 client smoke test failed' }

    Write-Host "`n=== Smoke test PASSED ===" -ForegroundColor Green

    # ---------------------------------------------------------------
    # 9. Tear down and verify deterministic reset
    # ---------------------------------------------------------------
    Write-Host '=== Tearing down (deterministic reset test) ===' -ForegroundColor Cyan
    & docker compose down -v
    if ($LASTEXITCODE -ne 0) { throw 'docker compose down -v failed' }

    # Verify volumes are gone
    $volumes = docker volume ls --format '{{.Name}}' 2>$null | Where-Object { $_ -like 'tcc-odoo-lab*' }
    if ($volumes) {
        throw "Volumes still exist after reset: $($volumes -join ', ')"
    }
    Write-Host '  All volumes removed: PASS' -ForegroundColor Green

    Write-Host "`n=== Full smoke test cycle complete ===" -ForegroundColor Green
    Write-Host 'Services started (PG18 + Odoo 19), DB initialized, /web/health validated, API key generated, JSON-2 CRUD verified, and environment fully reset.'
}
catch {
    Write-Host "=== SMOKE TEST FAILED ===" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red

    # Best-effort cleanup
    try { docker compose down -v 2>$null } catch {}
    throw
}
finally {
    Pop-Location
}
