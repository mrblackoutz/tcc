param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function New-HexSecret {
    param([ValidateRange(16, 128)][int]$ByteCount = 32)

    $bytes = New-Object byte[] $ByteCount
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }

    return (($bytes | ForEach-Object { $_.ToString('x2') }) -join '')
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$environmentPath = Join-Path $repositoryRoot '.env'

if ((Test-Path -LiteralPath $environmentPath) -and -not $Force) {
    throw 'O arquivo .env local já existe. Use -Force somente se a rotação das credenciais locais for intencional.'
}

# --- Generate secrets ---
$postgresPassword = New-HexSecret
$odooAdminPassword = New-HexSecret
$odooApiKey = New-HexSecret

# --- Write .env ---
$lines = @(
    '# Gerado localmente; nunca versionar ou compartilhar.',
    'POSTGRES_DB=tcc_ap_lab',
    'POSTGRES_USER=tcc_ap_lab',
    ('POSTGRES_PASSWORD=' + $postgresPassword),
    'ODOO_DATABASE=tcc_ap_lab',
    ('ODOO_ADMIN_PASSWORD=' + $odooAdminPassword),
    'ODOO_HTTP_PORT=8069',
    'ODOO_BASE_URL=http://127.0.0.1:8069',
    'ODOO_API_TOKEN_FILE=.runtime/secrets/odoo_api_key'
)

[System.IO.File]::WriteAllLines(
    $environmentPath,
    $lines,
    [System.Text.UTF8Encoding]::new($false)
)

# --- Create .runtime directory tree ---
$runtimeDir = Join-Path $repositoryRoot '.runtime'
$secretsDir = Join-Path $runtimeDir 'secrets'
New-Item -ItemType Directory -Force -Path $secretsDir | Out-Null

# --- Write odoo.conf ---
$odooConfPath = Join-Path $runtimeDir 'odoo.conf'
$odooConf = @(
    '[options]',
    ('admin_passwd = ' + $odooAdminPassword),
    'db_host = db',
    'db_port = 5432',
    ('db_user = tcc_ap_lab'),
    ('db_password = ' + $postgresPassword),
    ('db_name = tcc_ap_lab'),
    'addons_path = /opt/odoo/addons,/mnt/extra-addons',
    'data_dir = /var/lib/odoo',
    'proxy_mode = False',
    'list_db = False',
    'log_level = info',
    'without_demo = all',
    'server_wide_modules = base,web,rpc'
)

[System.IO.File]::WriteAllLines(
    $odooConfPath,
    $odooConf,
    [System.Text.UTF8Encoding]::new($false)
)

# --- Write API key seed ---
$apiKeyPath = Join-Path $secretsDir 'odoo_api_key'
[System.IO.File]::WriteAllText(
    $apiKeyPath,
    $odooApiKey,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host 'Ambiente local criado:' -ForegroundColor Green
Write-Host "  .env                          (credenciais locais)" -ForegroundColor Gray
Write-Host "  .runtime/odoo.conf            (configuração Odoo)" -ForegroundColor Gray
Write-Host "  .runtime/secrets/odoo_api_key (chave API seed)" -ForegroundColor Gray
Write-Host 'Nenhum valor sensível foi exibido.' -ForegroundColor Green
