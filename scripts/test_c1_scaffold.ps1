param([switch]$WithHttpAcl, [switch]$WithDraftKernel, [switch]$WithApproval, [switch]$WithPostKernel)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (@($WithHttpAcl, $WithDraftKernel, $WithApproval, $WithPostKernel).Where({ [bool]$_ }).Count -gt 1) {
    throw 'Select one explicit probe mode'
}

# A fresh, labelled, internal lab: no Compose services, existing database,
# volume, existing API key, image rebuild or external model call is used here.
# HTTP mode generates only expiring in-memory synthetic test keys.
$repositoryRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$runId = [guid]::NewGuid().ToString('N')
$probeTask = if ($WithPostKernel) { 'C1-08' } elseif ($WithApproval) { 'C1-07' } elseif ($WithDraftKernel) { 'C1-06' } elseif ($WithHttpAcl) { 'C1-05' } else { 'C1-04' }
$probeDirectory = $probeTask.ToLowerInvariant()
$probePrefix = if ($WithPostKernel) { 'tcc-c108' } elseif ($WithApproval) { 'tcc-c107' } elseif ($WithDraftKernel) { 'tcc-c106' } elseif ($WithHttpAcl) { 'tcc-c105' } else { 'tcc-c104' }
$ownerLabel = if ($WithPostKernel) { 'tcc.c108.run' } elseif ($WithApproval) { 'tcc.c107.run' } elseif ($WithDraftKernel) { 'tcc.c106.run' } elseif ($WithHttpAcl) { 'tcc.c105.run' } else { 'tcc.c104.run' }
$networkName = $probePrefix + '-' + $runId
$postgresName = $networkName + '-db'
$odooName = $networkName + '-odoo'
$databaseName = $probePrefix.Replace('-', '_') + '_' + $runId.Substring(0, 12)
$databaseUser = $probePrefix.Replace('-', '_')
$probeRoot = Join-Path $repositoryRoot ('.runtime\' + $probeDirectory + '\' + $runId)
$expectedRoot = [System.IO.Path]::GetFullPath((Join-Path $repositoryRoot ('.runtime\' + $probeDirectory))) + [System.IO.Path]::DirectorySeparatorChar
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
    # An engine/permission failure is not proof that a resource is absent.
    $names = Invoke-ProbeDocker -Arguments @('container', 'ls', '--all', '--format', '{{.Names}}') -LogName ($Name + '-cleanup-list.log')
    if ($Name -notin $names) { return }
    $owner = Invoke-ProbeDocker -Arguments @('container', 'inspect', '--format', '{{json .Config.Labels}}', $Name) -LogName ($Name + '-cleanup-owner.log')
    $ownerLabels = ($owner -join '') | ConvertFrom-Json
    $ownerProperty = $ownerLabels.PSObject.Properties[$ownerLabel]
    if ($null -eq $ownerProperty -or $ownerProperty.Value -ne $runId) { throw 'Refusing unowned container cleanup' }
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
        ('POSTGRES_USER=' + $databaseUser), ('POSTGRES_DB=' + $databaseName), ('POSTGRES_PASSWORD=' + $probePassword)
    ), $encoding)
    [System.IO.File]::WriteAllLines($odooConfiguration, [string[]]@(
        '[options]', 'db_host = db', 'db_port = 5432', ('db_user = ' + $databaseUser),
        ('db_password = ' + $probePassword), ('db_name = ' + $databaseName),
        ('admin_passwd = ' + $probePassword), 'data_dir = /var/lib/odoo',
        'addons_path = /opt/odoo/addons,/mnt/extra-addons', 'list_db = False',
        'without_demo = True', 'server_wide_modules = base,web,rpc', 'log_level = test'
    ), $encoding)
    $probePassword = $null
    [Array]::Clear($secretBytes, 0, $secretBytes.Length)

    $networkCreated = $true
    $null = Invoke-ProbeDocker -Arguments @(
        'network', 'create', '--internal', '--label', ($ownerLabel + '=' + $runId), $networkName
    ) -LogName 'network-create.log'
    $postgresCreated = $true
    $null = Invoke-ProbeDocker -Arguments @(
        'run', '--detach', '--pull', 'never', '--name', $postgresName,
        '--label', ($ownerLabel + '=' + $runId), '--network', $networkName, '--network-alias', 'db',
        '--env-file', $postgresEnvironment, '--read-only', '--tmpfs', '/tmp',
        '--tmpfs', '/var/run/postgresql', '--tmpfs', '/var/lib/postgresql', $postgresImage
    ) -LogName 'postgres-start.log'
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $savedPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $null = & docker exec $postgresName pg_isready -U $databaseUser -d $databaseName 2>&1
            $ready = $LASTEXITCODE -eq 0
        }
        finally { $ErrorActionPreference = $savedPreference }
        if ($ready) { break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Isolated PostgreSQL did not become ready' }

    $testTags = '/ap_security_executor,-c1_identity,-c1_acl_http,-c1_draft_kernel,-c1_approval,-c1_post_kernel'
    $testArguments = @('--no-http')
    $httpDockerArguments = @()
    $httpEvidenceRoot = $null
    if ($WithHttpAcl) {
        $testTags = '/ap_security_executor,-c1_draft_kernel,-c1_approval,-c1_post_kernel'
        $testArguments = @('--http-interface', '127.0.0.1')
        $httpEvidenceRoot = Join-Path $probeRoot 'http-evidence'
        $null = New-Item -ItemType Directory -Path $httpEvidenceRoot
        $httpDockerArguments = @(
            '--mount', ('type=bind,source=' + $httpEvidenceRoot + ',target=/mnt/c1-evidence'),
            '--env', 'TCC_C1_PROBE_EVIDENCE_DIR=/mnt/c1-evidence'
        )
    }
    if ($WithDraftKernel) { $testTags = '/ap_security_executor,-c1_acl_http,-c1_approval,-c1_post_kernel' }
    if ($WithApproval) { $testTags = '/ap_security_executor,-c1_acl_http,-c1_post_kernel' }
    if ($WithPostKernel) { $testTags = '/ap_security_executor,-c1_acl_http' }
    Write-Host ($probeTask + ': installing and testing the add-on in a fresh disposable Odoo database.')
    $odooStarted = $true
    $dockerArguments = @(
        'run', '--pull', 'never', '--name', $odooName, '--label', ($ownerLabel + '=' + $runId),
        '--network', $networkName, '--read-only', '--security-opt', 'no-new-privileges:true', '--cap-drop', 'ALL',
        '--tmpfs', '/tmp:mode=1777', '--tmpfs', '/var/lib/odoo:uid=10001,gid=10001,mode=0750',
        '--mount', ('type=bind,source=' + $addonSnapshot + ',target=/mnt/extra-addons/ap_security_executor,readonly'),
        '--mount', ('type=bind,source=' + $odooConfiguration + ',target=/etc/odoo/c104.conf,readonly')
    ) + $httpDockerArguments + @(
        $loadedImageId, 'python', '/opt/odoo/odoo-bin', '-c', '/etc/odoo/c104.conf', '-d', $databaseName,
        '-i', 'ap_security_executor', '--without-demo=True', '--test-enable', '--test-tags', $testTags,
        '--stop-after-init'
    ) + $testArguments
    $odooOutput = Invoke-ProbeDocker -Arguments $dockerArguments -LogName 'odoo-tests.log'
    $testSummaryMatches = [regex]::Matches(($odooOutput -join "`n"), '(\d+) failed, (\d+) error\(s\) of (\d+) tests')
    if ($testSummaryMatches.Count -eq 0) { throw 'No Odoo test summary; installation alone is not a passing test' }
    $summary = $testSummaryMatches[$testSummaryMatches.Count - 1]
    if ($summary.Groups[1].Value -ne '0' -or $summary.Groups[2].Value -ne '0' -or [int]$summary.Groups[3].Value -le 0) {
        throw 'Odoo scaffold tests did not all pass'
    }
    Assert-SameAddonHashes -Before $sourceHashes -After (Get-AddonHashes)
    $result = [ordered]@{
        schema_version = 'c104-probe-evidence/v1'; status = 'TESTS_PASSED_CLEANUP_PENDING'; observed_at = [DateTime]::UtcNow.ToString('o')
        task = $probeTask; scope = 'install-and-preflight-only'; source_commit = $sourceLock.selected_commit
        odoo_config_digest = $environmentLock.components.odoo.localConfigDigest
        odoo_manifest_digest = $environmentLock.components.odoo.imageDigest
        loaded_image_id = $loadedImageId; loaded_image_id_kind = $loadedImageIdKind
        postgres_image = $postgresImage; odoo_test_count = [int]$summary.Groups[3].Value
        addon_tree_sha256 = $sourceHashes; source_tree_unchanged = $true
        isolated_database = $true; existing_lab_touched = $false; financial_effects_enabled = $false
    }
    if ($WithHttpAcl) {
        $httpEvidencePath = Join-Path $httpEvidenceRoot 'c105-http.json'
        if (-not (Test-Path -LiteralPath $httpEvidencePath -PathType Leaf)) { throw 'HTTP test evidence missing' }
        $httpProof = Get-Content -Raw -Encoding UTF8 -LiteralPath $httpEvidencePath | ConvertFrom-Json
        if ($httpProof.schema_version -ne 'c105-http-evidence/v1' -or $httpProof.status -ne 'PASS' -or
            $httpProof.http_request_count -le 0 -or $httpProof.http_test_count -le 0) {
            throw 'HTTP tests did not produce complete passing evidence'
        }
        $result.schema_version = 'c105-probe-evidence/v1'
        $result.scope = 'identity-inventory-and-json2-http-preflight-only'
        $result['http_request_count'] = [int]$httpProof.http_request_count
        $result['http_test_count'] = [int]$httpProof.http_test_count
        $result['http_evidence_sha256'] = (Get-FileHash -LiteralPath $httpEvidencePath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    if ($WithDraftKernel) {
        $result.schema_version = 'c106-probe-evidence/v1'
        $result.scope = 'private-admin-draft-transaction-only'
        $result['public_financial_effects_enabled'] = $false
        $result['private_synthetic_draft_tested'] = $true
        $result['independent_cursor_concurrency_tested'] = $false
        $kernelTests = [regex]::Matches(($odooOutput -join "`n"), 'Starting TestDraftKernel\.(test_[a-z0-9_]+)')
        if ($kernelTests.Count -eq 0) { throw 'No private kernel test actually executed' }
        $result['kernel_test_count'] = @($kernelTests | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique).Count
    }
    if ($WithApproval) {
        $result.schema_version = 'c107-probe-evidence/v1'
        $result.scope = 'private-approval-and-nonce-transaction-only'
        $result['public_financial_effects_enabled'] = $false
        $result['post_effects_enabled'] = $false
        $result['private_synthetic_draft_regression_tested'] = $true
        $result['independent_cursor_concurrency_tested'] = $false
        $approvalTests = [regex]::Matches(($odooOutput -join "`n"), 'Starting TestApprovalKernel\.(test_[a-z0-9_]+)')
        if ($approvalTests.Count -eq 0) { throw 'No approval transaction test actually executed' }
        $result['approval_test_count'] = @($approvalTests | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique).Count
    }
    if ($WithPostKernel) {
        $result.schema_version = 'c108-probe-evidence/v1'
        $result.scope = 'private-approved-post-transaction-only'
        # The public executor is still closed. Only disposable synthetic
        # fixtures exercise native action_post in this administrative probe.
        $result['financial_effects_scope'] = 'public-executor-only'
        $result['private_effects_scope'] = 'disposable-synthetic-fixtures-only'
        $result['public_financial_effects_enabled'] = $false
        $result['private_synthetic_post_tested'] = $true
        $result['post_effects_enabled'] = $true
        $result['independent_cursor_concurrency_tested'] = $false
        $postTests = [regex]::Matches(($odooOutput -join "`n"), 'Starting TestPostKernel\.(test_[a-z0-9_]+)')
        if ($postTests.Count -eq 0) { throw 'No private approved POST transaction test actually executed' }
        $result['post_kernel_test_count'] = @($postTests | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique).Count
    }
    [System.IO.File]::WriteAllText((Join-Path $probeRoot 'evidence.json'), ($result | ConvertTo-Json -Depth 8) + "`n", $encoding)
}
finally {
    if ($odooStarted) { Remove-OwnedContainer -Name $odooName }
    if ($postgresCreated) { Remove-OwnedContainer -Name $postgresName }
    if ($networkCreated) {
        $names = Invoke-ProbeDocker -Arguments @('network', 'ls', '--format', '{{.Name}}') -LogName 'network-cleanup-list.log'
        if ($networkName -in $names) {
            $owner = Invoke-ProbeDocker -Arguments @('network', 'inspect', '--format', '{{json .Labels}}', $networkName) -LogName 'network-cleanup-owner.log'
            $ownerLabels = ($owner -join '') | ConvertFrom-Json
            $ownerProperty = $ownerLabels.PSObject.Properties[$ownerLabel]
            if ($null -eq $ownerProperty -or $ownerProperty.Value -ne $runId) { throw 'Refusing unowned network cleanup' }
            $null = Invoke-ProbeDocker -Arguments @('network', 'rm', $networkName) -LogName 'network-cleanup.log'
        }
    }
    # Confirm absence with successful Docker queries, including after rm.
    # A disconnected engine leaves evidence pending, never cleanup_verified.
    $remainingContainers = Invoke-ProbeDocker -Arguments @('container', 'ls', '--all', '--format', '{{.Names}}') -LogName 'cleanup-final-containers.log'
    $remainingNetworks = Invoke-ProbeDocker -Arguments @('network', 'ls', '--format', '{{.Name}}') -LogName 'cleanup-final-networks.log'
    if ($odooName -in $remainingContainers -or $postgresName -in $remainingContainers -or $networkName -in $remainingNetworks) {
        throw 'Isolated probe resources remain after cleanup'
    }
}
if ($null -ne $result) {
    $result.status = 'PASS'
    $result['cleanup_verified'] = $true
    [System.IO.File]::WriteAllText((Join-Path $probeRoot 'evidence.json'), ($result | ConvertTo-Json -Depth 8) + "`n", $encoding)
    Write-Host ($probeTask + ' isolated Odoo probe: PASS (' + $result.odoo_test_count + ' tests).')
    Write-Host 'Only this probe network, containers, database and filestore were discarded; existing lab preserved.'
    Write-Host ('Ignored local evidence: .runtime/' + $probeDirectory + '/' + $runId + '/evidence.json')
}
