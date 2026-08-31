param(
    [switch]$StagedOnly
)

$ErrorActionPreference = 'Stop'

$repoRoot = (& git rev-parse --show-toplevel 2>$null).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repoRoot)) {
    throw 'Execute este script dentro de um repositório Git.'
}

Push-Location $repoRoot
try {
    $paths = if ($StagedOnly) {
        @(& git diff --cached --name-only --diff-filter=ACMR)
    }
    else {
        @(& git ls-files --cached --others --exclude-standard)
    }

    $paths = @($paths | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Sort-Object -Unique)
    $issues = New-Object System.Collections.Generic.List[object]

    $blockedPathRules = @(
        [pscustomobject]@{ Name = 'environment file'; Pattern = '(^|/)\.env($|\.)'; Allow = '(^|/)\.env\.example$' },
        [pscustomobject]@{ Name = 'private key or keystore'; Pattern = '(?i)\.(pem|key|p12|pfx|jks|keystore|kdbx)$'; Allow = '$a' },
        [pscustomobject]@{ Name = 'local credential configuration'; Pattern = '(?i)(^|/)(odoo\.conf|\.pgpass|pgpass\.conf|\.npmrc|\.pypirc|\.netrc)$'; Allow = '$a' },
        [pscustomobject]@{ Name = 'credential path'; Pattern = '(?i)(^|/)(secrets?|credentials?)(/|\.|$)'; Allow = '$a' },
        [pscustomobject]@{ Name = 'database or dump'; Pattern = '(?i)\.(dump|backup|sql|sqlite|sqlite3)$'; Allow = '$a' },
        [pscustomobject]@{ Name = 'local runtime state'; Pattern = '(?i)^\.runtime(/|$)'; Allow = '$a' },
        [pscustomobject]@{ Name = 'private/raw data'; Pattern = '(?i)^(data/private|dataset/private|documents/private|sources/private|experiments/raw|experiments/runs|analysis/private|logs|outbox)(/|$)'; Allow = '$a' },
        [pscustomobject]@{ Name = 'local Odoo snapshot'; Pattern = '(?i)^odoo-19\.0(/|$)'; Allow = '$a' },
        [pscustomobject]@{ Name = 'local institutional/TCC I source package'; Pattern = '(?i)^relatorio_tcc_I_fci_pacote(/|$)'; Allow = '$a' }
    )

    foreach ($path in $paths) {
        $normalized = $path -replace '\\', '/'
        foreach ($rule in $blockedPathRules) {
            if ($normalized -match $rule.Pattern -and $normalized -notmatch $rule.Allow) {
                $issues.Add([pscustomobject]@{ Path = $path; Line = '-'; Rule = $rule.Name })
            }
        }
    }

    $textExtensions = @('.md', '.txt', '.ps1', '.psm1', '.py', '.toml', '.yaml', '.yml', '.json', '.jsonl', '.xml', '.ini', '.cfg', '.conf', '.sh', '.env', '.js', '.ts')
    $secretRules = @(
        [pscustomobject]@{ Name = 'private-key header'; Pattern = '-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----' },
        [pscustomobject]@{ Name = 'AWS access key'; Pattern = '\bAKIA[0-9A-Z]{16}\b' },
        [pscustomobject]@{ Name = 'GitHub token'; Pattern = '\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b' },
        [pscustomobject]@{ Name = 'GitHub fine-grained token'; Pattern = '\bgithub_pat_[A-Za-z0-9_]{20,}\b' },
        [pscustomobject]@{ Name = 'provider-style API key'; Pattern = '\bsk-[A-Za-z0-9_-]{20,}\b' },
        [pscustomobject]@{ Name = 'Google-style API key'; Pattern = '\bAIza[0-9A-Za-z_-]{35}\b' },
        [pscustomobject]@{ Name = 'Bearer credential'; Pattern = '(?i)\bBearer\s+[A-Za-z0-9._~+/-]{20,}={0,2}\b' },
        [pscustomobject]@{ Name = 'JWT-like token'; Pattern = '\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b' },
        [pscustomobject]@{ Name = 'database URI with password'; Pattern = '(?i)\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?)://[^/\s:@]+:[^@\s/]+@' },
        [pscustomobject]@{ Name = 'Odoo master password assignment'; Pattern = '(?i)\badmin_passwd\b\s*[:=]\s*["'']?[^\s"'']{8,}' },
        [pscustomobject]@{ Name = 'credential assignment'; Pattern = '(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|passwd)\b\s*[:=]\s*["'']?[A-Za-z0-9/+_.=-]{12,}' },
        [pscustomobject]@{ Name = 'email address'; Pattern = '(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b' },
        [pscustomobject]@{ Name = 'Brazilian CPF-like identifier'; Pattern = '\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b' },
        [pscustomobject]@{ Name = 'academic identifier'; Pattern = '(?i)\b(?:RA|TIA|matr[ií]cula)\s*[:#-]?\s*\d{6,12}\b' }
    )
    $placeholderPattern = '(?i)(example|placeholder|redacted|change[_-]?me|dummy|synthetic|fictitious|<[^>]+>|\$\{[^}]+\})'

    foreach ($path in $paths) {
        $extension = [System.IO.Path]::GetExtension($path).ToLowerInvariant()
        if ($textExtensions -notcontains $extension -and [System.IO.Path]::GetFileName($path) -notin @('.gitignore', 'AGENTS.md')) {
            continue
        }

        $content = if ($StagedOnly) {
            @(& git show --no-textconv (':' + ($path -replace '\\', '/')) 2>$null)
        }
        elseif (Test-Path -LiteralPath $path -PathType Leaf) {
            @(Get-Content -Encoding utf8 -LiteralPath $path)
        }
        else {
            @()
        }
        # An `if` expression can unwrap a one-line result to a scalar string;
        # normalize it so indexing always addresses lines, never characters.
        $content = @($content)

        for ($lineIndex = 0; $lineIndex -lt $content.Count; $lineIndex++) {
            $line = [string]$content[$lineIndex]
            foreach ($rule in $secretRules) {
                $matches = [regex]::Matches($line, $rule.Pattern)
                foreach ($match in $matches) {
                    if ($match.Value -match $placeholderPattern) { continue }
                    $issues.Add([pscustomobject]@{ Path = $path; Line = $lineIndex + 1; Rule = $rule.Name })
                }
            }
        }
    }

    if ($issues.Count -gt 0) {
        Write-Host 'Repository safety check: FAIL' -ForegroundColor Red
        $issues | Sort-Object Path, Line, Rule -Unique | Format-Table -AutoSize
        Write-Host 'Os valores suspeitos não são exibidos. Remova-os do índice/arquivo e rotacione qualquer credencial real.' -ForegroundColor Yellow
        exit 1
    }

    $scope = if ($StagedOnly) { 'staged files' } else { 'tracked and visible untracked files' }
    Write-Host ("Repository safety check: PASS ({0}; {1} files)" -f $scope, $paths.Count) -ForegroundColor Green
}
finally {
    Pop-Location
}
