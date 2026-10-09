# DEC-051: isolated native proof, never the existing laboratory or a scientific run.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repositoryRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$runId = [guid]::NewGuid().ToString('N')
$ownerLabel = 'tcc.runner.run'
$prefix = 'tcc-runner-' + $runId
$networkName = $prefix
$postgresName = $prefix + '-db'
$odooName = $prefix + '-odoo'
$gatewayName = $prefix + '-gateway'
$secretVolume = $prefix + '-secret-tmpfs'
$databaseName = 'tcc_runner_' + $runId.Substring(0, 12)
$databaseUser = 'tcc_runner'
$probeRoot = Join-Path $repositoryRoot ('.runtime\runner-native\' + $runId)
$expectedRoot = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot '.runtime\runner-native')) + [System.IO.Path]::DirectorySeparatorChar
if (-not [System.IO.Path]::GetFullPath($probeRoot).StartsWith($expectedRoot, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid disposable proof path' }
$null = New-Item -ItemType Directory -Path $probeRoot
$encoding = [System.Text.UTF8Encoding]::new($false)
$created = @{ network = $false; postgres = $false; odoo = $false; gateway = $false; volume = $false }
$result = $null

function Invoke-RunnerDocker {
    param([string[]]$Arguments, [string]$LogName)
    $savedPreference = $ErrorActionPreference
    try { $ErrorActionPreference = 'Continue'; $output = @(& docker @Arguments 2>&1); $exitCode = $LASTEXITCODE }
    finally { $ErrorActionPreference = $savedPreference }
    $lines = @($output | ForEach-Object { [string]$_ })
    [System.IO.File]::WriteAllLines((Join-Path $probeRoot $LogName), [string[]]$lines, $encoding)
    if ($exitCode -ne 0) { throw ('Native proof step failed; ignored log: ' + $LogName) }
    return ,$lines
}

function Get-RunnerSourceHashes {
    $hashes = [ordered]@{}
    $paths = @(& git -C $repositoryRoot ls-files --cached --others --exclude-standard -- 'odoo/addons/ap_security_executor' 'gateway/src')
    if ($LASTEXITCODE -ne 0 -or $paths.Count -eq 0) { throw 'Cannot enumerate native proof sources' }
    $paths += @('odoo/probes/c111_transactions.py', 'odoo/probes/runner_native.py', 'odoo/probes/runner_native_fixture.py', 'odoo/probes/runner_native_gateway.py', 'scripts/test_runner_native.ps1')
    foreach ($path in ($paths | Sort-Object -Unique)) {
        $path = $path -replace '\\', '/'
        if ($path.Contains('..') -or [System.IO.Path]::GetExtension($path) -notin @('.py', '.xml', '.json', '.ps1')) { throw 'Unexpected native proof source' }
        $hashes[$path] = (Get-FileHash -LiteralPath (Join-Path $repositoryRoot $path) -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    return $hashes
}

function Assert-RunnerSources {
    param($Before, $After)
    if ($Before.Count -ne $After.Count) { throw 'Native proof source changed' }
    foreach ($path in $Before.Keys) { if (-not $After.Contains($path) -or $Before[$path] -cne $After[$path]) { throw 'Native proof source changed' } }
}

function Remove-RunnerContainer {
    param([string]$Name)
    if ($Name -notin @($postgresName, $odooName, $gatewayName)) { throw 'Refusing unrelated container cleanup' }
    $names = Invoke-RunnerDocker @('container', 'ls', '--all', '--format', '{{.Names}}') ($Name + '-cleanup-list.log')
    if ($Name -notin $names) { return }
    $labels = ((Invoke-RunnerDocker @('container', 'inspect', '--format', '{{json .Config.Labels}}', $Name) ($Name + '-owner.log')) -join '') | ConvertFrom-Json
    $owner = $labels.PSObject.Properties[$ownerLabel]
    if ($null -eq $owner -or $owner.Value -ne $runId) { throw 'Refusing unowned container cleanup' }
    $null = Invoke-RunnerDocker @('container', 'rm', '--force', $Name) ($Name + '-cleanup.log')
}

function Invoke-NativeMode {
    param([string]$Mode)
    $null = Invoke-RunnerDocker (@('exec', $odooName, 'python', '/mnt/runner-probes/runner_native.py', $Mode) + $probeArguments) ($Mode + '.log')
}

try {
    $lock = Get-Content -Raw -LiteralPath (Join-Path $repositoryRoot 'reproducibility/lab-environment.lock.json') | ConvertFrom-Json
    $sourceLock = Get-Content -Raw -LiteralPath (Join-Path $repositoryRoot 'reproducibility/odoo-source.lock.json') | ConvertFrom-Json
    if ($sourceLock.selected_commit -ne $lock.components.odoo.commit -or
        $sourceLock.image.build_source_commit -ne $sourceLock.selected_commit -or
        $sourceLock.image.local_config_digest -ne $lock.components.odoo.localConfigDigest -or
        $sourceLock.image.oci_digest -ne $lock.components.odoo.imageDigest -or
        $sourceLock.image.runtime_platform -ne 'linux/amd64' -or
        $lock.components.odoo.buildPlatform -ne 'linux/amd64') { throw 'Native proof source locks disagree' }
    $imageFacts = (Invoke-RunnerDocker @('image', 'inspect', '--format', '{{.Id}}', $lock.components.odoo.localImageTag) 'odoo-image.log') -join ''
    $odooImage = $imageFacts.Trim()
    if ($odooImage -notin @($lock.components.odoo.localConfigDigest, $lock.components.odoo.imageDigest)) { throw 'Odoo image provenance mismatch' }
    $labels = ((Invoke-RunnerDocker @('image', 'inspect', '--format', '{{json .Config.Labels}}', $odooImage) 'odoo-labels.log') -join '') | ConvertFrom-Json
    if ($labels.'org.opencontainers.image.revision' -ne $sourceLock.selected_commit -or
        $labels.'org.opencontainers.image.source' -ne $sourceLock.repository -or
        $labels.'org.opencontainers.image.base.name' -ne $sourceLock.image.base_image_reference -or
        $labels.'br.edu.fci.tcc.platform' -ne 'linux/amd64') { throw 'Odoo image labels mismatch' }
    # The moving local tag is inconsistent with the historical lock (DEC-051).
    # Use the existing immutable dependency runtime, never silently update it.
    $gatewayImage = ((Invoke-RunnerDocker @('image', 'inspect', '--format', '{{.Id}}', $lock.components.gateway.localConfigDigest) 'gateway-image.log') -join '').Trim()
    if ($gatewayImage -ne $lock.components.gateway.localConfigDigest) { throw 'Gateway dependency image mismatch' }
    foreach ($image in @($odooImage, $gatewayImage)) {
        if (((Invoke-RunnerDocker @('image', 'inspect', '--format', '{{.Os}}/{{.Architecture}}', $image) ($image.Substring(7, 12) + '-platform.log')) -join '').Trim() -ne 'linux/amd64') { throw 'Image platform mismatch' }
    }
    $postgresImage = $lock.components.postgresql.immutableReference
    $null = Invoke-RunnerDocker @('image', 'inspect', '--format', '{{.Id}}', $postgresImage) 'postgres-image.log'
    $marker = ((Invoke-RunnerDocker @('run', '--rm', '--pull', 'never', '--network', 'none', '--entrypoint', 'python', $odooImage, '-c', "print(open('/opt/odoo/.tcc-source-commit').read().strip())") 'source-marker.log') -join '').Trim()
    if ($marker -ne $sourceLock.selected_commit) { throw 'Odoo source marker mismatch' }
    $dependencyCheck = "import importlib.metadata as m; expected={'httpx':'0.28.1','jsonschema':'4.26.0','pypdf':'6.16.2'}; assert all(m.version(k)==v for k,v in expected.items()); print('DEPENDENCIES_PASS')"
    $null = Invoke-RunnerDocker @('run', '--rm', '--pull', 'never', '--network', 'none', '--entrypoint', 'python', $gatewayImage, '-c', $dependencyCheck) 'gateway-dependencies.log'
    $sourceHashes = Get-RunnerSourceHashes
    $snapshot = Join-Path $probeRoot 'snapshot'
    foreach ($path in $sourceHashes.Keys) {
        $destination = Join-Path $snapshot $path
        $null = New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force
        Copy-Item -LiteralPath (Join-Path $repositoryRoot $path) -Destination $destination
        if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -cne $sourceHashes[$path]) { throw 'Source drift during snapshot' }
    }
    Assert-RunnerSources $sourceHashes (Get-RunnerSourceHashes)
    $bundleBytes = [System.Text.Encoding]::UTF8.GetBytes(($sourceHashes | ConvertTo-Json -Compress -Depth 4))
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { $bundleHash = ($sha.ComputeHash($bundleBytes) | ForEach-Object { $_.ToString('x2') }) -join '' } finally { $sha.Dispose() }
    $gitBase = ((& git -C $repositoryRoot rev-parse HEAD) -join '').Trim()
    if ($LASTEXITCODE -ne 0 -or $gitBase -notmatch '^[0-9a-f]{40}$') { throw 'Cannot identify Git base' }
    $artifacts = Join-Path $probeRoot 'artifacts'
    $null = New-Item -ItemType Directory -Path $artifacts
    $postgresEnvironment = Join-Path $probeRoot 'postgres.env'
    $configuration = Join-Path $probeRoot 'odoo.conf'
    $secretBytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($secretBytes) } finally { $generator.Dispose() }
    $probePassword = ($secretBytes | ForEach-Object { $_.ToString('x2') }) -join ''
    [System.IO.File]::WriteAllLines($postgresEnvironment, [string[]]@(('POSTGRES_USER=' + $databaseUser), ('POSTGRES_DB=' + $databaseName), ('POSTGRES_PASSWORD=' + $probePassword)), $encoding)
    [System.IO.File]::WriteAllLines($configuration, [string[]]@(
        '[options]', 'db_host = db', 'db_port = 5432', ('db_user = ' + $databaseUser),
        ('db_password = ' + $probePassword), ('db_name = ' + $databaseName), ('admin_passwd = ' + $probePassword),
        'data_dir = /var/lib/odoo', 'addons_path = /opt/odoo/addons,/mnt/extra-addons',
        'list_db = False', 'without_demo = True', 'server_wide_modules = base,web,rpc', 'log_level = warn'
    ), $encoding)
    $probePassword = $null
    [Array]::Clear($secretBytes, 0, $secretBytes.Length)
    $probeArguments = @('--database', $databaseName, '--git-base', $gitBase, '--source-bundle-sha256', $bundleHash)
    $created.network = $true
    $null = Invoke-RunnerDocker @('network', 'create', '--internal', '--label', ($ownerLabel + '=' + $runId), $networkName) 'network-create.log'
    $created.volume = $true
    $null = Invoke-RunnerDocker @('volume', 'create', '--driver', 'local', '--opt', 'type=tmpfs', '--opt', 'device=tmpfs', '--opt', 'o=size=1048576,uid=10001,gid=10001,mode=0750', '--label', ($ownerLabel + '=' + $runId), $secretVolume) 'secret-volume-create.log'
    $created.postgres = $true
    $null = Invoke-RunnerDocker @('run', '--detach', '--pull', 'never', '--name', $postgresName, '--label', ($ownerLabel + '=' + $runId), '--network', $networkName, '--network-alias', 'db', '--env-file', $postgresEnvironment, '--read-only', '--tmpfs', '/tmp', '--tmpfs', '/var/run/postgresql', '--tmpfs', '/var/lib/postgresql', $postgresImage) 'postgres-start.log'
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $savedPreference = $ErrorActionPreference
        try { $ErrorActionPreference = 'Continue'; $null = & docker exec $postgresName pg_isready -U $databaseUser -d $databaseName 2>&1; $ready = $LASTEXITCODE -eq 0 }
        finally { $ErrorActionPreference = $savedPreference }
        if ($ready) { break }; Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Disposable PostgreSQL readiness failed' }
    $odooBase = @('run', '--pull', 'never', '--name', $odooName, '--label', ($ownerLabel + '=' + $runId), '--network', $networkName,
        '--read-only', '--security-opt', 'no-new-privileges:true', '--cap-drop', 'ALL', '--tmpfs', '/tmp:mode=1777', '--tmpfs', '/var/lib/odoo:uid=10001,gid=10001,mode=0750',
        '--mount', ('type=bind,source=' + (Join-Path $snapshot 'odoo/addons/ap_security_executor') + ',target=/mnt/extra-addons/ap_security_executor,readonly'),
        '--mount', ('type=bind,source=' + (Join-Path $snapshot 'odoo/probes') + ',target=/mnt/runner-probes,readonly'),
        '--mount', ('type=bind,source=' + $artifacts + ',target=/mnt/runner-artifacts'),
        '--mount', ('type=bind,source=' + $configuration + ',target=/etc/odoo/runner.conf,readonly'))
    $created.odoo = $true
    $null = Invoke-RunnerDocker ($odooBase + @($odooImage, 'python', '/opt/odoo/odoo-bin', '-c', '/etc/odoo/runner.conf', '-d', $databaseName, '-i', 'ap_security_executor', '--without-demo=True', '--stop-after-init', '--no-http')) 'install.log'
    Remove-RunnerContainer $odooName
    # Keep the tmpfs mounted for its entire lifetime. No unmount between seed/client.
    $created.gateway = $true
    $gatewayBase = @('run', '--detach', '--pull', 'never', '--name', $gatewayName, '--label', ($ownerLabel + '=' + $runId), '--network', $networkName,
        '--user', '10002:10001', '--read-only', '--security-opt', 'no-new-privileges:true', '--cap-drop', 'ALL', '--tmpfs', '/tmp:mode=1777',
        '--env', 'PYTHONPATH=/mnt/runner-gateway/src', '--env', 'PYTHONDONTWRITEBYTECODE=1',
        '--mount', ('type=bind,source=' + (Join-Path $snapshot 'gateway') + ',target=/mnt/runner-gateway,readonly'),
        '--mount', ('type=bind,source=' + (Join-Path $snapshot 'odoo/probes') + ',target=/mnt/runner-probes,readonly'),
        '--mount', ('type=bind,source=' + $artifacts + ',target=/mnt/runner-artifacts'),
        '--mount', ('type=volume,source=' + $secretVolume + ',target=/run/runner-secrets,readonly'),
        $gatewayImage, 'python', '-c', 'import time; time.sleep(1200)')
    $null = Invoke-RunnerDocker $gatewayBase 'gateway-start.log'
    $null = Invoke-RunnerDocker ($odooBase + @('--mount', ('type=volume,source=' + $secretVolume + ',target=/run/runner-secrets'), $odooImage, 'python', '/mnt/runner-probes/runner_native.py', 'prepare') + $probeArguments) 'prepare.log'
    Remove-RunnerContainer $odooName
    $null = Invoke-RunnerDocker ($odooBase + @('--detach', '--network-alias', 'odoo', $odooImage, 'python', '/opt/odoo/odoo-bin', '-c', '/etc/odoo/runner.conf', '-d', $databaseName, '--http-interface', '0.0.0.0', '--max-cron-threads=0')) 'odoo-server-start.log'
    $ready = $false
    $healthCode = "import urllib.request; assert urllib.request.urlopen('http://odoo:8069/web/login',timeout=2).status==200"
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        $savedPreference = $ErrorActionPreference
        try { $ErrorActionPreference = 'Continue'; $null = & docker exec $gatewayName python -c $healthCode 2>&1; $ready = $LASTEXITCODE -eq 0 }
        finally { $ErrorActionPreference = $savedPreference }
        if ($ready) { break }; Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Disposable Odoo HTTP readiness failed' }
    $null = Invoke-RunnerDocker (@('exec', $gatewayName, 'python', '/mnt/runner-probes/runner_native.py', 'dispatch') + $probeArguments) 'dispatch.log'
    Invoke-NativeMode 'observe'
    Invoke-NativeMode 'c1'
    Assert-RunnerSources $sourceHashes (Get-RunnerSourceHashes)
    $proofs = [ordered]@{}
    $c0CaseNames = @('create_benign', 'create_amount_deviation', 'create_bank_deviation', 'post_without_approval', 'post_target_absent', 'post_target_ambiguous', 'native_post_failure')
    $c1CaseNames = @('registered_create_commit', 'registered_replay_commit', 'registered_outer_rollback', 'registered_fault_after_result_parent_commit')
    foreach ($name in @('dispatch', 'native-observation', 'c1-registered')) {
        $proofPath = Join-Path $artifacts ($name + '.json')
        $proof = Get-Content -Raw -Encoding UTF8 -LiteralPath $proofPath | ConvertFrom-Json
        $expectedNames = if ($name -eq 'c1-registered') { $c1CaseNames } else { $c0CaseNames }
        $expectedSchema = if ($name -eq 'dispatch') { 'runner-native-dispatch/v1' } elseif ($name -eq 'native-observation') { 'runner-native-observation/v1' } else { 'runner-native-registered-create/v1' }
        $actualNames = @($proof.cases | ForEach-Object { $_.name })
        if ($proof.schema_version -ne $expectedSchema -or $proof.status -ne 'PASS' -or
            $proof.test_count -ne $expectedNames.Count -or $actualNames.Count -ne $expectedNames.Count -or
            ($actualNames -join '|') -cne ($expectedNames -join '|') -or $proof.scientific_run -ne $false) { throw 'Native proof evidence incomplete' }
        foreach ($case in $proof.cases) {
            if ($case.status -ne 'PASS' -or @($case.checks.PSObject.Properties).Count -eq 0) { throw 'Native proof case failed' }
            foreach ($check in $case.checks.PSObject.Properties) { if ($check.Value -ne $true) { throw 'Native proof check failed' } }
        }
        if ($name -eq 'dispatch' -and ($proof.provider_mocked -ne $true -or $proof.external_provider_called -ne $false -or $proof.public_c1_executor_opened -ne $false -or $proof.http_request_count -le 0)) { throw 'Invalid dispatch limits' }
        if ($name -eq 'native-observation' -and ($proof.normal_registry -ne $true -or $proof.test_cursor_used -ne $false -or $proof.payment_count -ne 0 -or $proof.c0_approval_nonce_count -ne 0 -or $proof.complete_scientific_snapshot -ne $false)) { throw 'Invalid observer limits' }
        if ($name -eq 'c1-registered' -and ($proof.normal_registry -ne $true -or $proof.test_cursor_used -ne $false -or $proof.gateway_policy_integrated -ne $false -or $proof.public_executor_opened -ne $false)) { throw 'Invalid registered execution limits' }
        $proofs[$name] = (Get-FileHash -LiteralPath $proofPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $result = [ordered]@{
        schema_version = 'runner-native-probe-evidence/v1'; status = 'TESTS_PASSED_CLEANUP_PENDING'
        observed_at = [DateTime]::UtcNow.ToString('o'); decision = 'DEC-051'; git_base = $gitBase
        source_bundle_sha256 = $bundleHash; source_sha256 = $sourceHashes; source_tree_unchanged = $true
        odoo_source_commit = $sourceLock.selected_commit; odoo_manifest_digest = $lock.components.odoo.imageDigest
        odoo_config_digest = $odooImage; gateway_dependency_image_digest = $gatewayImage; postgres_image = $postgresImage
        proof_sha256 = $proofs; c0_test_count = $c0CaseNames.Count; c1_test_count = $c1CaseNames.Count
        native_json2_tested = $true; native_normal_registry_observer = $true; test_cursor_used = $false
        provider_mocked = $true; external_provider_called = $false; existing_lab_touched = $false
        public_c1_executor_opened = $false; scientific_run = $false; complete_scientific_snapshot = $false
        credential_transfer = 'labelled-restricted-docker-tmpfs'; provenance_declared_not_attested = $true
    }
    [System.IO.File]::WriteAllText((Join-Path $probeRoot 'evidence.json'), ($result | ConvertTo-Json -Depth 8) + "`n", $encoding)
}
finally {
    $cleanupErrors = [System.Collections.Generic.List[string]]::new()
    foreach ($entry in @(@{ key = 'odoo'; name = $odooName }, @{ key = 'gateway'; name = $gatewayName }, @{ key = 'postgres'; name = $postgresName })) {
        if (-not $created[$entry.key]) { continue }
        try { Remove-RunnerContainer $entry.name }
        catch { $cleanupErrors.Add($entry.key) }
    }
    foreach ($kind in @('volume', 'network')) {
        if (-not $created[$kind]) { continue }
        $name = if ($kind -eq 'volume') { $secretVolume } else { $networkName }
        try {
            $names = Invoke-RunnerDocker @($kind, 'ls', '--format', '{{.Name}}') ($kind + '-cleanup-list.log')
            if ($name -in $names) {
                $labels = ((Invoke-RunnerDocker @($kind, 'inspect', '--format', '{{json .Labels}}', $name) ($kind + '-cleanup-owner.log')) -join '') | ConvertFrom-Json
                $owner = $labels.PSObject.Properties[$ownerLabel]
                if ($null -eq $owner -or $owner.Value -ne $runId) { throw 'Refusing unowned native proof resource cleanup' }
                $null = Invoke-RunnerDocker @($kind, 'rm', $name) ($kind + '-cleanup.log')
            }
        }
        catch { $cleanupErrors.Add($kind) }
    }
    try {
        $containers = Invoke-RunnerDocker @('container', 'ls', '--all', '--format', '{{.Names}}') 'cleanup-final-containers.log'
        $networks = Invoke-RunnerDocker @('network', 'ls', '--format', '{{.Name}}') 'cleanup-final-networks.log'
        $volumes = Invoke-RunnerDocker @('volume', 'ls', '--format', '{{.Name}}') 'cleanup-final-volumes.log'
        if ($odooName -in $containers -or $gatewayName -in $containers -or $postgresName -in $containers -or $networkName -in $networks -or $secretVolume -in $volumes) { $cleanupErrors.Add('remaining-resources') }
    }
    catch { $cleanupErrors.Add('absence-check') }
    if ($cleanupErrors.Count -gt 0) { throw ('Native proof cleanup incomplete: ' + ($cleanupErrors -join ',') + '; inspect ignored cleanup logs') }
}
if ($null -ne $result) {
    $result.status = 'PASS'; $result['cleanup_verified'] = $true
    [System.IO.File]::WriteAllText((Join-Path $probeRoot 'evidence.json'), ($result | ConvertTo-Json -Depth 8) + "`n", $encoding)
    Write-Host 'Native runner proof: PASS. Only labelled disposable resources were discarded.'
    Write-Host ('.runtime/runner-native/' + $runId + '/evidence.json')
}
