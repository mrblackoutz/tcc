param([switch]$WithHttpAcl, [switch]$WithDraftKernel, [switch]$WithApproval, [switch]$WithPostKernel, [switch]$WithAudit, [switch]$WithBypass, [switch]$WithTransactions, [switch]$WithWorkflow)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (@($WithHttpAcl, $WithDraftKernel, $WithApproval, $WithPostKernel, $WithAudit, $WithBypass, $WithTransactions, $WithWorkflow).Where({ [bool]$_ }).Count -gt 1) {
    throw 'Select one explicit probe mode'
}

# A fresh, labelled, internal lab: no Compose services, existing database,
# volume, existing API key, image rebuild or external model call is used here.
# HTTP mode generates only expiring in-memory synthetic test keys.
$repositoryRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$runId = [guid]::NewGuid().ToString('N')
$probeTask = if ($WithWorkflow) { 'RUN-02-workflow' } elseif ($WithTransactions) { 'C1-11' } elseif ($WithBypass) { 'C1-10' } elseif ($WithAudit) { 'C1-09' } elseif ($WithPostKernel) { 'C1-08' } elseif ($WithApproval) { 'C1-07' } elseif ($WithDraftKernel) { 'C1-06' } elseif ($WithHttpAcl) { 'C1-05' } else { 'C1-04' }
$probeDirectory = $probeTask.ToLowerInvariant()
$probePrefix = if ($WithWorkflow) { 'tcc-workflow' } elseif ($WithTransactions) { 'tcc-c111' } elseif ($WithBypass) { 'tcc-c110' } elseif ($WithAudit) { 'tcc-c109' } elseif ($WithPostKernel) { 'tcc-c108' } elseif ($WithApproval) { 'tcc-c107' } elseif ($WithDraftKernel) { 'tcc-c106' } elseif ($WithHttpAcl) { 'tcc-c105' } else { 'tcc-c104' }
$ownerLabel = if ($WithWorkflow) { 'tcc.workflow.run' } elseif ($WithTransactions) { 'tcc.c111.run' } elseif ($WithBypass) { 'tcc.c110.run' } elseif ($WithAudit) { 'tcc.c109.run' } elseif ($WithPostKernel) { 'tcc.c108.run' } elseif ($WithApproval) { 'tcc.c107.run' } elseif ($WithDraftKernel) { 'tcc.c106.run' } elseif ($WithHttpAcl) { 'tcc.c105.run' } else { 'tcc.c104.run' }
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

    $testTags = '/ap_security_executor,-c1_identity,-c1_acl_http,-c1_draft_kernel,-c1_approval,-c1_post_kernel,-c1_audit,-c1_attachment,-c1_bypass_http,-c1_workflow'
    $testArguments = @('--no-http')
    $httpDockerArguments = @()
    $httpEvidenceRoot = $null
    if ($WithHttpAcl -or $WithBypass) {
        $testTags = '/ap_security_executor,-c1_draft_kernel,-c1_approval,-c1_post_kernel,-c1_audit,-c1_attachment,-c1_bypass_http,-c1_workflow'
        $testArguments = @('--http-interface', '127.0.0.1')
        $httpEvidenceRoot = Join-Path $probeRoot 'http-evidence'
        $null = New-Item -ItemType Directory -Path $httpEvidenceRoot
        $httpDockerArguments = @(
            '--mount', ('type=bind,source=' + $httpEvidenceRoot + ',target=/mnt/c1-evidence'),
            '--env', 'TCC_C1_PROBE_EVIDENCE_DIR=/mnt/c1-evidence'
        )
    }
    if ($WithDraftKernel) { $testTags = '/ap_security_executor,-c1_acl_http,-c1_approval,-c1_post_kernel,-c1_audit,-c1_attachment,-c1_bypass_http,-c1_workflow' }
    if ($WithApproval) { $testTags = '/ap_security_executor,-c1_acl_http,-c1_post_kernel,-c1_audit,-c1_attachment,-c1_bypass_http,-c1_workflow' }
    if ($WithPostKernel) { $testTags = '/ap_security_executor,-c1_acl_http,-c1_audit,-c1_attachment,-c1_bypass_http,-c1_workflow' }
    if ($WithAudit) { $testTags = '/ap_security_executor,-c1_acl_http,-c1_bypass_http,-c1_workflow' }
    if ($WithBypass) { $testTags = '/ap_security_executor,-c1_draft_kernel,-c1_approval,-c1_post_kernel,-c1_audit,-c1_attachment,-c1_workflow' }
    if ($WithWorkflow) { $testTags = '/ap_security_executor,-c1_acl_http,-c1_bypass_http' }
    if ($WithWorkflow) {
        $workflowEvidenceRoot = Join-Path $probeRoot 'workflow-evidence'
        $workflowSnapshot = Join-Path $probeRoot 'probe-snapshot'
        $null = New-Item -ItemType Directory -Path $workflowEvidenceRoot, $workflowSnapshot
        $workflowProbeHashes = @{}
        foreach ($workflowSource in @('odoo/probes/c111_transactions.py', 'odoo/probes/workflow_transactions.py')) {
            $workflowSourcePath = Join-Path $repositoryRoot $workflowSource
            $workflowHash = (Get-FileHash -LiteralPath $workflowSourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
            $workflowProbeHashes[$workflowSource] = $workflowHash
            $workflowCopy = Join-Path $workflowSnapshot ([System.IO.Path]::GetFileName($workflowSource))
            Copy-Item -LiteralPath $workflowSourcePath -Destination $workflowCopy
            if ((Get-FileHash -LiteralPath $workflowCopy -Algorithm SHA256).Hash.ToLowerInvariant() -cne $workflowHash) {
                throw 'Workflow probe source changed during snapshot'
            }
        }
    }
    if ($WithTransactions) {
        $httpEvidenceRoot = Join-Path $probeRoot 'transaction-evidence'
        $null = New-Item -ItemType Directory -Path $httpEvidenceRoot
        $transactionProbePath = Join-Path $repositoryRoot 'odoo/probes/c111_transactions.py'
        $transactionProbeHash = (Get-FileHash -LiteralPath $transactionProbePath -Algorithm SHA256).Hash.ToLowerInvariant()
        $transactionSnapshot = Join-Path $probeRoot 'probe-snapshot'
        $null = New-Item -ItemType Directory -Path $transactionSnapshot
        $transactionSnapshotPath = Join-Path $transactionSnapshot 'c111_transactions.py'
        Copy-Item -LiteralPath $transactionProbePath -Destination $transactionSnapshotPath
        if ((Get-FileHash -LiteralPath $transactionSnapshotPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $transactionProbeHash) {
            throw 'Transaction probe source changed during snapshot'
        }
    }
    Write-Host ($probeTask + ': installing and testing the add-on in a fresh disposable Odoo database.')
    $odooStarted = $true
    $dockerBaseArguments = @(
        'run', '--pull', 'never', '--name', $odooName, '--label', ($ownerLabel + '=' + $runId),
        '--network', $networkName, '--read-only', '--security-opt', 'no-new-privileges:true', '--cap-drop', 'ALL',
        '--tmpfs', '/tmp:mode=1777', '--tmpfs', '/var/lib/odoo:uid=10001,gid=10001,mode=0750',
        '--mount', ('type=bind,source=' + $addonSnapshot + ',target=/mnt/extra-addons/ap_security_executor,readonly'),
        '--mount', ('type=bind,source=' + $odooConfiguration + ',target=/etc/odoo/c104.conf,readonly')
    )
    $odooInitializationArguments = @(
        $loadedImageId, 'python', '/opt/odoo/odoo-bin', '-c', '/etc/odoo/c104.conf', '-d', $databaseName,
        '-i', 'ap_security_executor', '--without-demo=True',
        '--stop-after-init'
    ) + $testArguments
    if (-not $WithTransactions) { $odooInitializationArguments += @('--test-enable', '--test-tags', $testTags) }
    $dockerArguments = $dockerBaseArguments + $httpDockerArguments + $odooInitializationArguments
    $odooOutput = Invoke-ProbeDocker -Arguments $dockerArguments -LogName 'odoo-tests.log'
    $odooTestCount = 0
    if (-not $WithTransactions) {
        $testSummaryMatches = [regex]::Matches(($odooOutput -join "`n"), '(\d+) failed, (\d+) error\(s\) of (\d+) tests')
        if ($testSummaryMatches.Count -eq 0) { throw 'No Odoo test summary; installation alone is not a passing test' }
        $summary = $testSummaryMatches[$testSummaryMatches.Count - 1]
        if ($summary.Groups[1].Value -ne '0' -or $summary.Groups[2].Value -ne '0' -or [int]$summary.Groups[3].Value -le 0) {
            throw 'Odoo scaffold tests did not all pass'
        }
        $odooTestCount = [int]$summary.Groups[3].Value
    }
    else {
        # Installation is not a test. Use a new ordinary Python process,
        # with no Odoo test mode or shared TransactionCase cursor.
        Remove-OwnedContainer -Name $odooName
        $transactionArguments = $dockerBaseArguments + @(
            '--mount', ('type=bind,source=' + $transactionSnapshot + ',target=/mnt/c1-probe,readonly'),
            '--mount', ('type=bind,source=' + $httpEvidenceRoot + ',target=/mnt/c1-evidence'),
            $loadedImageId, 'python', '/mnt/c1-probe/c111_transactions.py',
            '--config', '/etc/odoo/c104.conf', '--database', $databaseName,
            '--evidence', '/mnt/c1-evidence/c111-transactions.json'
        )
        $null = Invoke-ProbeDocker -Arguments $transactionArguments -LogName 'transaction-tests.log'
        if ((Get-FileHash -LiteralPath $transactionProbePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $transactionProbeHash) {
            throw 'Transaction probe source tree changed during execution'
        }
    }
    if ($WithWorkflow) {
        # Keep ORM tests and real lifecycle evidence separate. A fresh normal
        # registry/process proves external commit/rollback, never TestCursor.
        Remove-OwnedContainer -Name $odooName
        $workflowArguments = $dockerBaseArguments + @(
            '--mount', ('type=bind,source=' + $workflowSnapshot + ',target=/mnt/c1-probe,readonly'),
            '--mount', ('type=bind,source=' + $workflowEvidenceRoot + ',target=/mnt/c1-evidence'),
            $loadedImageId, 'python', '/mnt/c1-probe/workflow_transactions.py',
            '--config', '/etc/odoo/c104.conf', '--database', $databaseName,
            '--evidence', '/mnt/c1-evidence/workflow-transactions.json'
        )
        $null = Invoke-ProbeDocker -Arguments $workflowArguments -LogName 'workflow-transactions.log'
        foreach ($workflowSource in $workflowProbeHashes.Keys) {
            if ((Get-FileHash -LiteralPath (Join-Path $repositoryRoot $workflowSource) -Algorithm SHA256).Hash.ToLowerInvariant() -cne $workflowProbeHashes[$workflowSource]) {
                throw 'Workflow probe source tree changed during execution'
            }
        }
    }
    Assert-SameAddonHashes -Before $sourceHashes -After (Get-AddonHashes)
    $result = [ordered]@{
        schema_version = 'c104-probe-evidence/v1'; status = 'TESTS_PASSED_CLEANUP_PENDING'; observed_at = [DateTime]::UtcNow.ToString('o')
        task = $probeTask; scope = 'install-and-preflight-only'; source_commit = $sourceLock.selected_commit
        odoo_config_digest = $environmentLock.components.odoo.localConfigDigest
        odoo_manifest_digest = $environmentLock.components.odoo.imageDigest
        loaded_image_id = $loadedImageId; loaded_image_id_kind = $loadedImageIdKind
        postgres_image = $postgresImage; odoo_test_count = $odooTestCount
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
    if ($WithBypass) {
        $httpEvidencePath = Join-Path $httpEvidenceRoot 'c110-http.json'
        if (-not (Test-Path -LiteralPath $httpEvidencePath -PathType Leaf)) { throw 'Bypass HTTP evidence missing' }
        $httpProof = Get-Content -Raw -Encoding UTF8 -LiteralPath $httpEvidencePath | ConvertFrom-Json
        $bypassMatches = [regex]::Matches(($odooOutput -join "`n"), 'Starting TestExecutorBypassHttp\.(test_[a-z0-9_]+)')
        $bypassNames = @($bypassMatches | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
        if ($httpProof.schema_version -ne 'c110-http-evidence/v1' -or $httpProof.status -ne 'PASS' -or
            $httpProof.http_request_count -le 0 -or $httpProof.http_test_count -le 0 -or
            $bypassNames.Count -ne [int]$httpProof.http_test_count) {
            throw 'Bypass HTTP cases did not actually execute or produce passing evidence'
        }
        $checks = @($httpProof.critical_state_checks)
        $checkedNames = @($checks | ForEach-Object { $_.case } | Sort-Object -Unique)
        if ($checks.Count -ne [int]$httpProof.http_test_count -or $checkedNames.Count -ne $checks.Count -or
            ($checkedNames -join '|') -cne ($bypassNames -join '|') -or
            $httpProof.public_financial_effects_enabled -ne $false -or $httpProof.integrated_executor_tested -ne $false) {
            throw 'Bypass state checks incomplete or scope mismatch'
        }
        foreach ($check in $checks) {
            if ($check.before_sha256 -notmatch '^sha256:[0-9a-f]{64}$' -or $check.before_sha256 -cne $check.after_sha256) {
                throw 'Bypass critical-state mutation or invalid projection'
            }
        }
        $result.schema_version = 'c110-probe-evidence/v1'
        $result.scope = 'native-json2-bypass-closed-public-executor-only'
        $result['http_request_count'] = [int]$httpProof.http_request_count
        $result['http_test_count'] = [int]$httpProof.http_test_count
        $result['http_evidence_sha256'] = (Get-FileHash -LiteralPath $httpEvidencePath -Algorithm SHA256).Hash.ToLowerInvariant()
        $result['public_financial_effects_enabled'] = $false
        $result['integrated_executor_tested'] = $false
        $result['financial_effects_scope'] = 'public-executor-only'
        $result['private_effects_scope'] = 'administrative-synthetic-fixture-seeding-only'
    }
    if ($WithTransactions) {
        $transactionEvidencePath = Join-Path $httpEvidenceRoot 'c111-transactions.json'
        if (-not (Test-Path -LiteralPath $transactionEvidencePath -PathType Leaf)) { throw 'Transaction evidence missing' }
        $transactionProof = Get-Content -Raw -Encoding UTF8 -LiteralPath $transactionEvidencePath | ConvertFrom-Json
        $cases = @($transactionProof.cases)
        $caseNames = @($cases | ForEach-Object { $_.case } | Sort-Object -Unique)
        $expectedCaseNames = @(
            'create_commit_replay', 'create_outer_rollback', 'create_outer_savepoint_rollback',
            'post_outer_rollback', 'post_outer_savepoint_rollback',
            'create_fault_after_move', 'create_fault_after_attachment', 'create_fault_after_audit',
            'post_fault_after_native_post', 'post_fault_after_nonce_consumption', 'post_fault_after_audit',
            'post_commit_native_rank_replay', 'altered_command_after_approval',
            'stored_beneficiary_drift_after_approval', 'create_idempotency_changed_body',
            'post_idempotency_changed_body', 'duplicate_reference_distinct_document',
            'concurrent_create_identical_command', 'concurrent_post_identical_command',
            'concurrent_distinct_documents_remaining_quantity', 'concurrent_global_nonce_primitive',
            'concurrent_cross_po_same_vendor_reference'
        ) | Sort-Object
        if ($transactionProof.schema_version -ne 'c111-transactions-evidence/v1' -or $transactionProof.status -ne 'PASS' -or
            $transactionProof.test_count -ne 22 -or $transactionProof.case_count -ne 22 -or
            $transactionProof.passed_case_count -ne 22 -or $cases.Count -ne 22 -or
            ($caseNames -join '|') -cne ($expectedCaseNames -join '|') -or
            $caseNames.Count -ne $cases.Count -or $transactionProof.registry_test_mode -ne $false -or
            $transactionProof.normal_registry -ne $true -or $transactionProof.test_cursor_used -ne $false -or
            $transactionProof.mocked_sql_commit -ne $false -or $transactionProof.native_postcommit_executed -ne $true -or
            $transactionProof.observed_blocking_pair_count -ne 5 -or
            $transactionProof.independent_connection_pair_count -ne 5 -or $transactionProof.concurrent_retry_count -lt 5 -or
            $transactionProof.public_financial_effects_enabled -ne $false -or
            $transactionProof.independent_cursor_concurrency_tested -ne $true -or
            $transactionProof.backend_independence_verified -ne $true -or
            $transactionProof.blocking_overlap_verified -ne $true -or
            $transactionProof.native_supplier_rank_commit_lifecycle_tested -ne $true) {
            throw 'Real transaction/concurrency/lifecycle evidence incomplete'
        }
        foreach ($case in $cases) {
            if ($case.status -ne 'PASS' -or $case.case_id -cne $case.case) { throw 'Transaction case failed or identity mismatch' }
        }
        $result.schema_version = 'c111-probe-evidence/v1'
        $result.scope = 'private-audited-independent-transactions-and-commit-lifecycle-only'
        $result['transaction_test_count'] = [int]$transactionProof.test_count
        $result['transaction_evidence_sha256'] = (Get-FileHash -LiteralPath $transactionEvidencePath -Algorithm SHA256).Hash.ToLowerInvariant()
        $result['transaction_probe_source_sha256'] = $transactionProbeHash
        $result['public_financial_effects_enabled'] = $false
        $result['financial_effects_scope'] = 'public-executor-only'
        $result['private_effects_scope'] = 'disposable-synthetic-fixtures-only'
        $result['private_synthetic_draft_post_audited'] = $true
        $result['registry_test_mode'] = $false
        $result['independent_cursor_concurrency_tested'] = $true
        $result['native_supplier_rank_commit_lifecycle_tested'] = $true
    }
    if ($WithWorkflow) {
        $workflowNames = @([regex]::Matches(($odooOutput -join "`n"), 'Starting TestWorkflowRegistration\.(test_[a-z0-9_]+)') |
            ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
        $workflowTestSource = Join-Path $addonSnapshot 'tests/test_workflow_registry.py'
        $expectedWorkflowNames = @([regex]::Matches((Get-Content -Raw -LiteralPath $workflowTestSource -Encoding UTF8), '(?m)^    def (test_[a-z0-9_]+)\(') |
            ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
        if ($workflowNames.Count -eq 0 -or ($workflowNames -join '|') -cne ($expectedWorkflowNames -join '|')) {
            throw 'Workflow ORM cases did not all actually execute'
        }
        $workflowEvidencePath = Join-Path $workflowEvidenceRoot 'workflow-transactions.json'
        $workflowProof = Get-Content -LiteralPath $workflowEvidencePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $expectedWorkflowNativeCases = @('register_commit_and_fresh_cursor_resolve', 'registration_outer_rollback',
            'registration_savepoint_rollback_then_commit', 'fault_after_actual_insert', 'conflicting_replay_no_rebinding') | Sort-Object
        $workflowCases = @($workflowProof.cases)
        $workflowCaseNames = @($workflowCases | ForEach-Object { $_.case } | Sort-Object -Unique)
        if ($workflowProof.schema_version -ne 'workflow-transactions-evidence/v1' -or $workflowProof.status -ne 'PASS' -or
            $workflowCases.Count -ne 5 -or $workflowProof.test_count -ne 5 -or
            ($workflowCaseNames -join '|') -cne ($expectedWorkflowNativeCases -join '|') -or
            $workflowProof.normal_registry -ne $true -or $workflowProof.test_cursor_used -ne $false -or
            $workflowProof.mocked_sql_commit -ne $false -or $workflowProof.public_financial_effects_enabled -ne $false) {
            throw 'Workflow real transaction proof incomplete or scope mismatch'
        }
        foreach ($workflowCase in $workflowCases) {
            if ($workflowCase.status -ne 'PASS') { throw 'Workflow transaction case failed' }
        }
        $result.schema_version = 'workflow-registration-probe-evidence/v1'
        $result.scope = 'private-draft-workflow-registration-only'
        $result['workflow_test_count'] = $workflowNames.Count
        $result['workflow_transaction_test_count'] = [int]$workflowProof.test_count
        $result['workflow_transaction_evidence_sha256'] = (Get-FileHash -LiteralPath $workflowEvidencePath -Algorithm SHA256).Hash.ToLowerInvariant()
        $result['workflow_probe_source_sha256'] = $workflowProbeHashes
        $result['registration_normal_registry_lifecycle_tested'] = $true
        $result['registration_public'] = $false
        $result['public_financial_effects_enabled'] = $false
        $result['financial_effects_scope'] = 'public-executor-only'
        $result['private_effects_scope'] = 'disposable-synthetic-registry-and-wrapper-tests-only'
        $result['workflow_registration_integrated_into_runner'] = $false
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
    if ($WithAudit) {
        $result.schema_version = 'c109-probe-evidence/v2'
        $result.scope = 'private-transactional-document-audit-only'
        # Audited administrative wrappers and native POST are exercised only
        # against disposable fixtures; this does not open the public executor.
        $result['financial_effects_scope'] = 'public-executor-only'
        $result['private_effects_scope'] = 'disposable-synthetic-fixtures-only'
        $result['public_financial_effects_enabled'] = $false
        $result['private_synthetic_draft_post_audited'] = $true
        $result['native_post_tested'] = $true
        $result['post_effects_enabled'] = $true
        $result['audited_entry_public'] = $false
        $result['independent_cursor_concurrency_tested'] = $false
        $auditTests = [regex]::Matches(($odooOutput -join "`n"), 'Starting TestAuditKernel\.(test_[a-z0-9_]+)')
        $auditTestNames = @($auditTests | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
        if ($auditTestNames.Count -eq 0) { throw 'No private transactional audit test actually executed' }
        $result['audit_kernel_test_count'] = $auditTestNames.Count
        $attachmentTests = [regex]::Matches(($odooOutput -join "`n"), 'Starting TestAttachmentKernel\.(test_[a-z0-9_]+)')
        $attachmentTestNames = @($attachmentTests | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
        if ($attachmentTestNames.Count -eq 0) { throw 'No private transactional document attachment test actually executed' }
        $result['attachment_kernel_test_count'] = $attachmentTestNames.Count
        $result['private_synthetic_document_attachment_tested'] = $true
        $result['attachment_storage'] = 'db'
        $result['document_mime_size_sha256_verified'] = $true
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
    $passedTests = if ($WithTransactions) { $result.transaction_test_count } else { $result.odoo_test_count }
    $testKind = if ($WithTransactions) { 'independent transaction cases' } else { 'Odoo tests' }
    Write-Host ($probeTask + ' isolated Odoo probe: PASS (' + $passedTests + ' ' + $testKind + ').')
    Write-Host 'Only this probe network, containers, database and filestore were discarded; existing lab preserved.'
    Write-Host ('Ignored local evidence: .runtime/' + $probeDirectory + '/' + $runId + '/evidence.json')
}
