param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# A fresh, labelled, internal lab: no Compose services, existing database,
# volume, API key, image rebuild or external model call is used here.
$repositoryRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$runId = [guid]::NewGuid().ToString('N')
$networkName = 'tcc-c104-' + $runId
$postgresName = $networkName + '-db'
$odooName = $networkName + '-odoo'
$databaseName = 'tcc_c104_' + $runId.Substring(0, 12)
$probeRoot = Join-Path $repositoryRoot ('.runtime\c1-04\' + $runId)
$expectedRoot = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot '.runtime\c1-04')) + [System.IO.Path]::DirectorySeparatorChar
if (-not [System.IO.Path]::GetFullPath($probeRoot).StartsWith($expectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Invalid isolated probe path'
}
$null = New-Item -ItemType Directory -Path $probeRoot
$encoding = [System.Text.UTF8Encoding]::new($false)
$postgresCreated = $false
$networkCreated = $false
$odooStarted = $false
$result = $null

function Get-AddonHashes {
    $hashes = @{}
    $paths = @(& git -C $repositoryRoot ls-files --cached --others --exclude-standard -- 'odoo/addons/ap_security_executor')
    if ($LASTEXITCODE -ne 0 -or $paths.Count -eq 0) { throw 'Cannot enumerate add-on sources' }
    foreach ($path in $paths) {
        $path = $path -replace '\\', '/'
        if (-not $path.StartsWith('odoo/addons/ap_security_executor/') -or $path.Contains('..') -or
            [System.IO.Path]::GetExtension($path) -notin @('.py', '.xml')) {
            throw 'Unexpected file in add-on source snapshot'
        }
        $hashes[$path] = (Get-FileHash -LiteralPath (Join-Path $repositoryRoot $path) -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    return $hashes
}

function Assert-SameAddonHashes {
    param([hashtable]$Before, [hashtable]$After)
    if ($Before.Count -ne $After.Count) { throw 'Add-on source tree changed during probe' }
    foreach ($path in $Before.Keys) {
        if (-not $After.ContainsKey($path) -or $Before[$path] -ne $After[$path]) {
            throw 'Add-on source tree changed during probe'
        }
    }
}

function Invoke-ProbeDocker {
    param([string[]]$Arguments, [string]$LogName)
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = @(& docker @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $savedPreference }
    $lines = @($output | ForEach-Object { [string]$_ })
    [System.IO.File]::WriteAllLines((Join-Path $probeRoot $LogName), [string[]]$lines, $encoding)
    if ($exitCode -ne 0) {
        throw ('Isolated probe step failed; inspect ignored log ' + $LogName)
    }
    return ,$lines
}

function Remove-OwnedContainer {
    param([string]$Name)
    if ($Name -notin @($postgresName, $odooName)) { throw 'Refusing unrelated container cleanup' }
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $owner = @(& docker container inspect --format '{{json .Config.Labels}}' $Name 2>$null)
        $inspectExit = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $savedPreference }
    if ($inspectExit -ne 0) { return }
    $ownerLabels = ($owner -join '') | ConvertFrom-Json
    if ($ownerLabels.'tcc.c104.run' -ne $runId) { throw 'Refusing unowned container cleanup' }
    $null = Invoke-ProbeDocker -Arguments @('container', 'rm', '--force', $Name) -LogName ($Name + '-cleanup.log')
}

try {
    $environmentLock = Get-Content -LiteralPath (Join-Path $repositoryRoot 'reproducibility/lab-environment.lock.json') -Raw | ConvertFrom-Json
    $sourceLock = Get-Content -LiteralPath (Join-Path $repositoryRoot 'reproducibility/odoo-source.lock.json') -Raw | ConvertFrom-Json
    if ($sourceLock.selected_commit -ne $environmentLock.components.odoo.commit -or
        $sourceLock.image.build_source_commit -ne $sourceLock.selected_commit -or
        $sourceLock.image.oci_digest -ne $environmentLock.components.odoo.imageDigest -or
        $sourceLock.image.local_config_digest -ne $environmentLock.components.odoo.localConfigDigest -or
        $sourceLock.image.runtime_platform -ne 'linux/amd64' -or
        $environmentLock.components.odoo.buildPlatform -ne 'linux/amd64') {
        throw 'Odoo source and environment locks disagree'
    }
    $odooImage = $environmentLock.components.odoo.localImageTag
    $postgresImage = $environmentLock.components.postgresql.immutableReference
    $imageFacts = Invoke-ProbeDocker -Arguments @(
        'image', 'inspect', '--format', '{{.Id}}', $odooImage
    ) -LogName 'image-check.log'
    $imageLabelOutput = Invoke-ProbeDocker -Arguments @(
        'image', 'inspect', '--format', '{{json .Config.Labels}}', $odooImage
    ) -LogName 'image-label-check.log'
    $imageLabels = ($imageLabelOutput -join '') | ConvertFrom-Json
    $loadedImageId = ($imageFacts -join '').Trim()
    if ($loadedImageId -eq $environmentLock.components.odoo.localConfigDigest) {
        $loadedImageIdKind = 'config_digest'
    }
    elseif ($loadedImageId -eq $environmentLock.components.odoo.imageDigest) {
        $loadedImageIdKind = 'manifest_digest'
    }
    else { throw 'Odoo image does not match the fixed provenance' }
    if ($imageLabels.'org.opencontainers.image.revision' -ne $sourceLock.selected_commit -or
        $imageLabels.'org.opencontainers.image.source' -ne $sourceLock.repository -or
        $imageLabels.'org.opencontainers.image.base.name' -ne $sourceLock.image.base_image_reference -or
        $imageLabels.'br.edu.fci.tcc.platform' -ne 'linux/amd64') {
        throw 'Odoo image does not match the fixed provenance'
    }
    $platformFacts = Invoke-ProbeDocker -Arguments @(
        'image', 'inspect', '--format', '{{.Os}}/{{.Architecture}}', $loadedImageId
    ) -LogName 'platform-check.log'
    if (($platformFacts -join '').Trim() -ne 'linux/amd64') { throw 'Odoo runtime platform mismatch' }
    $null = Invoke-ProbeDocker -Arguments @('image', 'inspect', '--format', '{{.Id}}', $postgresImage) -LogName 'postgres-image-check.log'
    $sourceFacts = Invoke-ProbeDocker -Arguments @(
        'run', '--rm', '--pull', 'never', '--network', 'none', '--entrypoint', 'python', $loadedImageId,
        '-c', "print(open('/opt/odoo/.tcc-source-commit').read().strip())"
    ) -LogName 'source-check.log'
    if (($sourceFacts -join '').Trim() -ne $sourceLock.selected_commit) { throw 'Odoo source marker mismatch' }

    # Bind an immutable per-probe source copy, not the live working tree.
    $sourceHashes = Get-AddonHashes
    $addonSnapshot = Join-Path $probeRoot 'addon-snapshot'
    $null = New-Item -ItemType Directory -Path $addonSnapshot
    foreach ($path in $sourceHashes.Keys) {
        $relative = $path.Substring('odoo/addons/ap_security_executor/'.Length)
        $destination = Join-Path $addonSnapshot $relative
        $null = New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force
        Copy-Item -LiteralPath (Join-Path $repositoryRoot $path) -Destination $destination
        if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sourceHashes[$path]) {
            throw 'Add-on source changed while creating snapshot'
        }
    }
    Assert-SameAddonHashes -Before $sourceHashes -After (Get-AddonHashes)

    $secretBytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($secretBytes) } finally { $generator.Dispose() }
    $probePassword = ($secretBytes | ForEach-Object { $_.ToString('x2') }) -join ''
    $postgresEnvironment = Join-Path $probeRoot 'postgres.env'
    $odooConfiguration = Join-Path $probeRoot 'odoo.conf'
    [System.IO.File]::WriteAllLines($postgresEnvironment, [string[]]@(
        'POSTGRES_USER=tcc_c104', ('POSTGRES_DB=' + $databaseName), ('POSTGRES_PASSWORD=' + $probePassword)
    ), $encoding)
    [System.IO.File]::WriteAllLines($odooConfiguration, [string[]]@(
        '[options]', 'db_host = db', 'db_port = 5432', 'db_user = tcc_c104',
        ('db_password = ' + $probePassword), ('db_name = ' + $databaseName),
        ('admin_passwd = ' + $probePassword), 'data_dir = /var/lib/odoo',
        'addons_path = /opt/odoo/addons,/mnt/extra-addons', 'list_db = False',
        'without_demo = True', 'server_wide_modules = base,web,rpc', 'log_level = test'
    ), $encoding)
    $probePassword = $null
    [Array]::Clear($secretBytes, 0, $secretBytes.Length)

    $networkCreated = $true
    $null = Invoke-ProbeDocker -Arguments @(
        'network', 'create', '--internal', '--label', ('tcc.c104.run=' + $runId), $networkName
    ) -LogName 'network-create.log'
    $postgresCreated = $true
    $null = Invoke-ProbeDocker -Arguments @(
        'run', '--detach', '--pull', 'never', '--name', $postgresName,
        '--label', ('tcc.c104.run=' + $runId), '--network', $networkName, '--network-alias', 'db',
        '--env-file', $postgresEnvironment, '--read-only', '--tmpfs', '/tmp',
        '--tmpfs', '/var/run/postgresql', '--tmpfs', '/var/lib/postgresql', $postgresImage
    ) -LogName 'postgres-start.log'
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $savedPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $null = & docker exec $postgresName pg_isready -U tcc_c104 -d $databaseName 2>&1
            $ready = $LASTEXITCODE -eq 0
        }
        finally { $ErrorActionPreference = $savedPreference }
        if ($ready) { break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Isolated PostgreSQL did not become ready' }

    Write-Host 'C1-04: installing and testing the add-on in a fresh disposable Odoo database.'
    $odooStarted = $true
    $odooOutput = Invoke-ProbeDocker -Arguments @(
        'run', '--pull', 'never', '--name', $odooName, '--label', ('tcc.c104.run=' + $runId),
        '--network', $networkName, '--read-only', '--security-opt', 'no-new-privileges:true', '--cap-drop', 'ALL',
        '--tmpfs', '/tmp:mode=1777', '--tmpfs', '/var/lib/odoo:uid=10001,gid=10001,mode=0750',
        '--mount', ('type=bind,source=' + $addonSnapshot + ',target=/mnt/extra-addons/ap_security_executor,readonly'),
        '--mount', ('type=bind,source=' + $odooConfiguration + ',target=/etc/odoo/c104.conf,readonly'),
        $loadedImageId, 'python', '/opt/odoo/odoo-bin', '-c', '/etc/odoo/c104.conf', '-d', $databaseName,
        '-i', 'ap_security_executor', '--without-demo=True', '--test-enable', '--test-tags', '/ap_security_executor',
        '--stop-after-init', '--no-http'
    ) -LogName 'odoo-tests.log'
    $testSummaryMatches = [regex]::Matches(($odooOutput -join "`n"), '(\d+) failed, (\d+) error\(s\) of (\d+) tests')
    if ($testSummaryMatches.Count -eq 0) { throw 'No Odoo test summary; installation alone is not a passing test' }
    $summary = $testSummaryMatches[$testSummaryMatches.Count - 1]
    if ($summary.Groups[1].Value -ne '0' -or $summary.Groups[2].Value -ne '0' -or [int]$summary.Groups[3].Value -le 0) {
        throw 'Odoo scaffold tests did not all pass'
    }
    Assert-SameAddonHashes -Before $sourceHashes -After (Get-AddonHashes)
    $result = [ordered]@{
        schema_version = 'c104-probe-evidence/v1'; status = 'TESTS_PASSED_CLEANUP_PENDING'; observed_at = [DateTime]::UtcNow.ToString('o')
        scope = 'install-and-preflight-only'; source_commit = $sourceLock.selected_commit
        odoo_config_digest = $environmentLock.components.odoo.localConfigDigest
        odoo_manifest_digest = $environmentLock.components.odoo.imageDigest
        loaded_image_id = $loadedImageId; loaded_image_id_kind = $loadedImageIdKind
        postgres_image = $postgresImage; odoo_test_count = [int]$summary.Groups[3].Value
        addon_tree_sha256 = $sourceHashes; source_tree_unchanged = $true
        isolated_database = $true; existing_lab_touched = $false; financial_effects_enabled = $false
    }
    [System.IO.File]::WriteAllText((Join-Path $probeRoot 'evidence.json'), ($result | ConvertTo-Json -Depth 8) + "`n", $encoding)
}
finally {
    if ($odooStarted) { Remove-OwnedContainer -Name $odooName }
    if ($postgresCreated) { Remove-OwnedContainer -Name $postgresName }
    if ($networkCreated) {
        $savedPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $owner = @(& docker network inspect --format '{{json .Labels}}' $networkName 2>$null)
            $inspectExit = $LASTEXITCODE
        }
        finally { $ErrorActionPreference = $savedPreference }
        if ($inspectExit -eq 0) {
            $ownerLabels = ($owner -join '') | ConvertFrom-Json
            if ($ownerLabels.'tcc.c104.run' -ne $runId) { throw 'Refusing unowned network cleanup' }
            $null = Invoke-ProbeDocker -Arguments @('network', 'rm', $networkName) -LogName 'network-cleanup.log'
        }
    }
}
if ($null -ne $result) {
    $result.status = 'PASS'
    $result['cleanup_verified'] = $true
    [System.IO.File]::WriteAllText((Join-Path $probeRoot 'evidence.json'), ($result | ConvertTo-Json -Depth 8) + "`n", $encoding)
    Write-Host ('C1-04 isolated Odoo probe: PASS (' + $result.odoo_test_count + ' tests).')
    Write-Host 'Only this probe network, containers, database and filestore were discarded; existing lab preserved.'
    Write-Host ('Ignored local evidence: .runtime/c1-04/' + $runId + '/evidence.json')
}
