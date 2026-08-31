[CmdletBinding()]
param(
    [string]$PdfPath
)

$ErrorActionPreference = 'Stop'
$paperDir = $PSScriptRoot
$projectRoot = Split-Path -Parent $paperDir
$validationDir = Join-Path $projectRoot '.runtime\paper-validation'
$textPath = Join-Path $validationDir 'relatorio_tcc_ii.txt'
if ([string]::IsNullOrWhiteSpace($PdfPath)) {
    $PdfPath = Join-Path $paperDir 'relatorio_tcc_ii.pdf'
}

foreach ($command in @('pdfinfo', 'pdftotext')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $command"
    }
}

if (-not (Test-Path -LiteralPath $PdfPath)) {
    throw "PDF not found: $PdfPath"
}

New-Item -ItemType Directory -Force -Path $validationDir | Out-Null

function Remove-Diacritics {
    param([Parameter(Mandatory)][string]$Text)

    $normalized = $Text.Normalize([Text.NormalizationForm]::FormD)
    $builder = [Text.StringBuilder]::new()
    foreach ($character in $normalized.ToCharArray()) {
        if ([Globalization.CharUnicodeInfo]::GetUnicodeCategory($character) -ne [Globalization.UnicodeCategory]::NonSpacingMark) {
            [void]$builder.Append($character)
        }
    }
    return $builder.ToString().Normalize([Text.NormalizationForm]::FormC)
}

$pdfInfo = (& pdfinfo $PdfPath 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0) {
    throw "pdfinfo failed for $PdfPath"
}

if ($pdfInfo -notmatch '(?m)^Pages:\s+(\d+)\s*$') {
    throw 'Could not read PDF page count.'
}
$pageCount = [int]$Matches[1]
if ($pageCount -lt 10 -or $pageCount -gt 20) {
    throw "PDF page count must be between 10 and 20, including references; observed $pageCount."
}

if ($pdfInfo -notmatch '(?m)^Title:\s+(.+?)\s*$') {
    throw 'Could not read PDF title metadata.'
}
$actualTitle = Remove-Diacritics -Text $Matches[1].Trim()
$expectedTitle = 'Desenvolvimento e implementacao de uma arquitetura de protecao na integracao de LLMs em ERPs: estudo de caso com Odoo e Contas a Pagar'
if ($actualTitle -cne $expectedTitle) {
    throw 'PDF title metadata does not match the adopted title.'
}
if ($pdfInfo -match '(?i)Milton|Vestibular|Nome Aluno|aluno\.um') {
    throw 'Inherited or generic template metadata was detected.'
}
if ($pdfInfo -notmatch '(?m)^Encrypted:\s+no\s*$') {
    throw 'The submission PDF must not be encrypted.'
}
if ($pdfInfo -match '(?m)^JavaScript:\s+yes\s*$') {
    throw 'JavaScript is not allowed in the submission PDF.'
}

& pdftotext -enc UTF-8 -layout $PdfPath $textPath
if ($LASTEXITCODE -ne 0) {
    throw 'pdftotext failed.'
}
$pdfText = Get-Content -Raw -Encoding utf8 -LiteralPath $textPath
$pdfTextAscii = Remove-Diacritics -Text $pdfText

$requiredHeadings = @(
    '1. Introducao',
    '2. Referencial Teorico',
    '3. Metodologia',
    '4. Resultados e discussao',
    '5. Conclusao',
    '6. Referencias bibliograficas'
)
foreach ($heading in $requiredHeadings) {
    if ($pdfTextAscii -notmatch [regex]::Escape($heading)) {
        throw "Required heading not found in PDF: $heading"
    }
}

$forbiddenPatterns = @(
    '(?i)Nome Aluno',
    '(?i)INSERT(?:IR)? RESULT',
    '(?i)PLACEHOLDER',
    '\bTODO\b',
    '\bFIXME\b',
    '(?i)aluno\.um',
    '\[REDACTED'
)
foreach ($pattern in $forbiddenPatterns) {
    if ($pdfText -cmatch $pattern) {
        throw "Forbidden template or placeholder marker found in PDF: $pattern"
    }
}

$sourceFiles = Get-ChildItem -LiteralPath $paperDir -Recurse -File | Where-Object {
    $_.Extension -in @('.tex', '.bib', '.md', '.ps1')
}
$sourceText = ($sourceFiles | ForEach-Object { Get-Content -Raw -Encoding utf8 -LiteralPath $_.FullName }) -join "`n"
if ($sourceText -match '(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b') {
    throw 'An email address was detected in versioned paper sources.'
}

function Get-PlainWordCount {
    param([Parameter(Mandatory)][string]$Path)

    $text = Get-Content -Raw -Encoding utf8 -LiteralPath $Path
    $text = $text -replace '(?s)%.*?(\r?\n|$)', ' '
    $text = $text -replace '\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?', ' '
    $text = $text -replace '[{}~]', ' '
    $text = $text -replace '--+', ' '
    return [regex]::Matches($text, "[\p{L}\p{N}]+(?:[-'\u2019][\p{L}\p{N}]+)*").Count
}

$resumoPath = Join-Path $paperDir 'sections\resumo-pt.tex'
$abstractPath = Join-Path $paperDir 'sections\resumo-en.tex'
$resumoWords = Get-PlainWordCount -Path $resumoPath
$abstractWords = Get-PlainWordCount -Path $abstractPath
if ($resumoWords -lt 150 -or $resumoWords -gt 250) {
    throw "Resumo must contain 150 to 250 words; observed $resumoWords."
}
if ($abstractWords -lt 150 -or $abstractWords -gt 250) {
    throw "Abstract must contain 150 to 250 words; observed $abstractWords."
}

$texText = (Get-ChildItem -LiteralPath $paperDir -Recurse -Filter '*.tex' | ForEach-Object {
    Get-Content -Raw -Encoding utf8 -LiteralPath $_.FullName
}) -join "`n"
$citationKeys = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
foreach ($match in [regex]::Matches($texText, '\\cite(?:online)?\{([^}]+)\}')) {
    foreach ($key in $match.Groups[1].Value.Split(',')) {
        $null = $citationKeys.Add($key.Trim())
    }
}

$bibText = Get-Content -Raw -Encoding utf8 -LiteralPath (Join-Path $paperDir 'referencias.bib')
$bibKeys = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
foreach ($match in [regex]::Matches($bibText, '(?m)^@\w+\{([^,]+),')) {
    $null = $bibKeys.Add($match.Groups[1].Value.Trim())
}

$missingReferences = @($citationKeys | Where-Object { -not $bibKeys.Contains($_) })
$uncitedReferences = @($bibKeys | Where-Object { -not $citationKeys.Contains($_) })
if ($missingReferences.Count -gt 0) {
    throw "Citations without bibliography entries: $($missingReferences -join ', ')"
}
if ($uncitedReferences.Count -gt 0) {
    throw "Bibliography entries not cited in the article: $($uncitedReferences -join ', ')"
}

$pdfHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $PdfPath).Hash.ToLowerInvariant()
Write-Output 'Paper validation: PASS'
Write-Output "Pages: $pageCount"
Write-Output "Resumo words: $resumoWords"
Write-Output "Abstract words: $abstractWords"
Write-Output "Citations/references: $($citationKeys.Count)/$($bibKeys.Count)"
Write-Output "PDF SHA-256: $pdfHash"
