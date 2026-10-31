[CmdletBinding()]
param(
    [switch]$SkipValidation
)

$ErrorActionPreference = 'Stop'
$paperDir = $PSScriptRoot
$projectRoot = Split-Path -Parent $paperDir
$runtimeDir = Join-Path $projectRoot '.runtime\paper-build'
$outputPdf = Join-Path $paperDir 'relatorio_tcc_ii.pdf'

foreach ($command in @('pdflatex', 'bibtex')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $command"
    }
}

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

$oldTexInputs = $env:TEXINPUTS
$oldBibInputs = $env:BIBINPUTS
$env:TEXINPUTS = "$paperDir;$oldTexInputs"
$env:BIBINPUTS = "$paperDir;$oldBibInputs"

function Invoke-Checked {
    param(
        [Parameter(Mandatory)]
        [scriptblock]$Command,
        [Parameter(Mandatory)]
        [string]$Description
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

try {
    Push-Location $paperDir
    try {
        Invoke-Checked -Description 'First pdfLaTeX pass' -Command {
            & pdflatex --disable-installer -no-shell-escape -interaction=nonstopmode -halt-on-error -file-line-error -recorder "-output-directory=$runtimeDir" main.tex
        }
    }
    finally {
        Pop-Location
    }

    Push-Location $runtimeDir
    try {
        Invoke-Checked -Description 'BibTeX pass' -Command {
            & bibtex --disable-installer main
        }
    }
    finally {
        Pop-Location
    }

    for ($pass = 2; $pass -le 3; $pass++) {
        Push-Location $paperDir
        try {
            Invoke-Checked -Description "pdfLaTeX pass $pass" -Command {
                & pdflatex --disable-installer -no-shell-escape -interaction=nonstopmode -halt-on-error -file-line-error -recorder "-output-directory=$runtimeDir" main.tex
            }
        }
        finally {
            Pop-Location
        }
    }

    $logPath = Join-Path $runtimeDir 'main.log'
    $logText = Get-Content -Raw -LiteralPath $logPath
    if ($logText -match 'Citation .+ undefined' -or $logText -match 'There were undefined references') {
        throw 'The final LaTeX log contains undefined citations or references.'
    }

    $builtPdf = Join-Path $runtimeDir 'main.pdf'
    if (-not (Test-Path -LiteralPath $builtPdf)) {
        throw "Expected PDF was not produced: $builtPdf"
    }
}
finally {
    $env:TEXINPUTS = $oldTexInputs
    $env:BIBINPUTS = $oldBibInputs
}

# The versioned PDF is replaced only after the new build passes validation.
if ($SkipValidation) {
    $pdfHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $builtPdf).Hash.ToLowerInvariant()
    Write-Output "Paper build: NOT VALIDATED; $outputPdf was left unchanged"
    Write-Output "PDF: $builtPdf"
    Write-Output "SHA-256: $pdfHash"
    exit 0
}

& (Join-Path $paperDir 'validate_paper.ps1') -PdfPath $builtPdf
if ($LASTEXITCODE -ne 0) {
    throw "Paper validation failed with exit code $LASTEXITCODE; $outputPdf was left unchanged."
}

Copy-Item -LiteralPath $builtPdf -Destination $outputPdf -Force
$pdfHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $outputPdf).Hash.ToLowerInvariant()
Write-Output "Paper build: PASS"
Write-Output "PDF: $outputPdf"
Write-Output "SHA-256: $pdfHash"
