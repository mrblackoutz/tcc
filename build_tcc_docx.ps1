param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,
    [string]$PdfPath = ""
)

$ErrorActionPreference = "Stop"

function Get-Rgb([int]$R, [int]$G, [int]$B) {
    return $R + (256 * $G) + (65536 * $B)
}

function Set-NeutralDocxMetadata(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [Parameter(Mandatory = $true)]
    [string]$NeutralAuthor
) {
    Add-Type -AssemblyName WindowsBase
    $package = [System.IO.Packaging.Package]::Open(
        $Path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
    try {
        $properties = $package.PackageProperties
        $properties.Creator = $NeutralAuthor
        $properties.LastModifiedBy = $NeutralAuthor
        $properties.Title = "Desenvolvimento e implementação de uma arquitetura de proteção na integração de LLMs em ERPs"
        $properties.Subject = "Plano-mestre de pesquisa, implementação e avaliação experimental em Odoo"
        $properties.Keywords = "LLM; prompt injection indireta; Odoo; ERP; Contas a Pagar; segurança"
        $package.Flush()
    }
    finally {
        $package.Close()
    }
}

function Clean-Inline([string]$Text) {
    $value = $Text
    $value = [regex]::Replace($value, '\[([^\]]+)\]\((https?://[^)]+)\)', '$1')
    $value = $value -replace '\*\*', ''
    $value = $value -replace '`', ''
    $value = [regex]::Replace($value, '\*([^*]+)\*', '$1')
    $unchecked = ([char]0x2610).ToString() + ' '
    $checked = ([char]0x2612).ToString() + ' '
    $value = [regex]::Replace($value, '^\[ \]\s*', $unchecked)
    $value = [regex]::Replace($value, '^\[[xX]\]\s*', $checked)
    return $value
}

function Add-Run(
    $Doc,
    $Selection,
    [string]$Text,
    [bool]$Bold = $false,
    [bool]$Italic = $false,
    [bool]$Code = $false,
    [string]$Url = "",
    [string]$BaseFontName = "Aptos",
    [single]$BaseFontSize = 10.5,
    [int]$BaseBold = 0,
    [int]$BaseItalic = 0,
    [int]$BaseColor = 0
) {
    if ([string]::IsNullOrEmpty($Text)) { return }

    # Word carries the formatting of the previous run at a collapsed insertion
    # point. Reset it before every run so inline code/bold/italic cannot leak
    # into the prose that follows.
    $runFontName = if ($Code) { "Consolas" } else { $BaseFontName }
    [single]$runFontSize = if ($Code) { 9.0 } else { $BaseFontSize }
    [int]$runBold = if ($Bold) { -1 } else { $BaseBold }
    [int]$runItalic = if ($Italic) { -1 } else { $BaseItalic }
    [int]$runColor = if ($Code) { Get-Rgb 120 55 20 } else { $BaseColor }

    $Selection.Font.Name = $runFontName
    $Selection.Font.Size = $runFontSize
    $Selection.Font.Bold = $runBold
    $Selection.Font.Italic = $runItalic
    $Selection.Font.Color = $runColor
    $Selection.Range.Shading.BackgroundPatternColor = -16777216 # wdColorAutomatic

    $start = $Selection.Start
    $Selection.TypeText($Text)
    $finish = $Selection.Start
    $range = $Doc.Range($start, $finish)
    $range.Font.Name = $runFontName
    $range.Font.Size = $runFontSize
    $range.Font.Bold = $runBold
    $range.Font.Italic = $runItalic
    $range.Font.Color = $runColor
    $range.Shading.BackgroundPatternColor = -16777216
    if ($Code) {
        $range.Shading.BackgroundPatternColor = Get-Rgb 244 246 248
    }
    if (-not [string]::IsNullOrWhiteSpace($Url)) {
        $null = $Doc.Hyperlinks.Add($range, $Url)
    }
}

function Write-Inline($Doc, $Selection, [string]$Text) {
    $baseFontName = [string]$Selection.Font.Name
    $baseFontSize = [single]$Selection.Font.Size
    $baseBold = [int]$Selection.Font.Bold
    $baseItalic = [int]$Selection.Font.Italic
    $baseColor = [int]$Selection.Font.Color
    $pattern = '\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?://[^)]+)\)|\*([^*]+)\*'
    $matches = [regex]::Matches($Text, $pattern)
    $position = 0
    foreach ($match in $matches) {
        if ($match.Index -gt $position) {
            Add-Run $Doc $Selection $Text.Substring($position, $match.Index - $position) -BaseFontName $baseFontName -BaseFontSize $baseFontSize -BaseBold $baseBold -BaseItalic $baseItalic -BaseColor $baseColor
        }
        if ($match.Groups[1].Success) {
            Add-Run $Doc $Selection $match.Groups[1].Value $true $false $false -BaseFontName $baseFontName -BaseFontSize $baseFontSize -BaseBold $baseBold -BaseItalic $baseItalic -BaseColor $baseColor
        }
        elseif ($match.Groups[2].Success) {
            Add-Run $Doc $Selection $match.Groups[2].Value $false $false $true -BaseFontName $baseFontName -BaseFontSize $baseFontSize -BaseBold $baseBold -BaseItalic $baseItalic -BaseColor $baseColor
        }
        elseif ($match.Groups[3].Success) {
            Add-Run $Doc $Selection $match.Groups[3].Value $false $false $false $match.Groups[4].Value -BaseFontName $baseFontName -BaseFontSize $baseFontSize -BaseBold $baseBold -BaseItalic $baseItalic -BaseColor $baseColor
        }
        elseif ($match.Groups[5].Success) {
            Add-Run $Doc $Selection $match.Groups[5].Value $false $true $false -BaseFontName $baseFontName -BaseFontSize $baseFontSize -BaseBold $baseBold -BaseItalic $baseItalic -BaseColor $baseColor
        }
        $position = $match.Index + $match.Length
    }
    if ($position -lt $Text.Length) {
        Add-Run $Doc $Selection $Text.Substring($position) -BaseFontName $baseFontName -BaseFontSize $baseFontSize -BaseBold $baseBold -BaseItalic $baseItalic -BaseColor $baseColor
    }
}

function Set-ParagraphBase($Selection) {
    $Selection.Style = -1
    $Selection.Font.Name = "Aptos"
    $Selection.Font.Size = 10.5
    $Selection.Font.Bold = 0
    $Selection.Font.Italic = 0
    $Selection.Font.Color = Get-Rgb 35 43 50
    $Selection.Range.Shading.BackgroundPatternColor = -16777216
    $Selection.ParagraphFormat.Alignment = 0
    $Selection.ParagraphFormat.LeftIndent = 0
    $Selection.ParagraphFormat.FirstLineIndent = 0
    $Selection.ParagraphFormat.SpaceBefore = 0
    $Selection.ParagraphFormat.SpaceAfter = 6
    $Selection.ParagraphFormat.KeepWithNext = 0
    $Selection.ParagraphFormat.KeepTogether = 0
    $Selection.ParagraphFormat.PageBreakBefore = 0
}

function Add-StandardParagraph($Doc, $Selection, [string]$Text, [string]$Kind = "normal") {
    Set-ParagraphBase $Selection
    if ($Kind -eq "bullet") {
        $Selection.ParagraphFormat.LeftIndent = 28
        $Selection.ParagraphFormat.FirstLineIndent = -14
        Write-Inline $Doc $Selection (([char]0x2022).ToString() + "  " + (Clean-Inline $Text))
    }
    elseif ($Kind -eq "number") {
        $parts = $Text -split '\|', 2
        $Selection.ParagraphFormat.LeftIndent = 28
        $Selection.ParagraphFormat.FirstLineIndent = -20
        Write-Inline $Doc $Selection ($parts[0] + ".  " + $parts[1])
    }
    elseif ($Kind -eq "quote") {
        $Selection.ParagraphFormat.LeftIndent = 18
        $Selection.ParagraphFormat.RightIndent = 10
        $Selection.ParagraphFormat.SpaceBefore = 5
        $Selection.ParagraphFormat.SpaceAfter = 9
        $start = $Selection.Start
        Write-Inline $Doc $Selection $Text
        $finish = $Selection.Start
        $range = $Doc.Range($start, $finish)
        $range.Font.Italic = -1
        $range.Font.Color = Get-Rgb 37 71 106
        $range.Shading.BackgroundPatternColor = Get-Rgb 233 241 248
    }
    elseif ($Kind -eq "coverquote") {
        $Selection.ParagraphFormat.Alignment = 1
        $Selection.ParagraphFormat.LeftIndent = 30
        $Selection.ParagraphFormat.RightIndent = 30
        $Selection.ParagraphFormat.SpaceBefore = 24
        $Selection.ParagraphFormat.SpaceAfter = 9
        $start = $Selection.Start
        Write-Inline $Doc $Selection $Text
        $finish = $Selection.Start
        $range = $Doc.Range($start, $finish)
        $range.Font.Italic = -1
        $range.Font.Color = Get-Rgb 37 71 106
        $range.Shading.BackgroundPatternColor = Get-Rgb 233 241 248
    }
    else {
        Write-Inline $Doc $Selection $Text
    }
    $Selection.TypeParagraph()
}

function Add-Heading($Doc, $Selection, [int]$Level, [string]$Text, [bool]$PageBreakBefore) {
    $style = switch ($Level) { 1 { -2 } 2 { -3 } default { -4 } }
    $Selection.Style = $style
    $Selection.Font.Name = "Aptos Display"
    $Selection.Font.Bold = -1
    $Selection.Font.Color = Get-Rgb 23 54 93
    $Selection.ParagraphFormat.KeepWithNext = -1
    $Selection.ParagraphFormat.PageBreakBefore = if ($PageBreakBefore) { -1 } else { 0 }
    if ($Level -eq 1) {
        $Selection.Font.Size = 17
        $Selection.ParagraphFormat.SpaceBefore = 0
        $Selection.ParagraphFormat.SpaceAfter = 10
    }
    elseif ($Level -eq 2) {
        $Selection.Font.Size = 13
        $Selection.ParagraphFormat.SpaceBefore = 12
        $Selection.ParagraphFormat.SpaceAfter = 6
    }
    else {
        $Selection.Font.Size = 11
        $Selection.ParagraphFormat.SpaceBefore = 9
        $Selection.ParagraphFormat.SpaceAfter = 4
    }
    Write-Inline $Doc $Selection $Text
    $Selection.TypeParagraph()
    Set-ParagraphBase $Selection
}

function Add-CodeBlock($Doc, $Selection, [string[]]$Lines) {
    $Selection.TypeParagraph()
    $table = $Doc.Tables.Add($Selection.Range, 1, 1)
    $table.Borders.Enable = 0
    $table.AllowAutoFit = -1
    $table.AutoFitBehavior(2)
    $cell = $table.Cell(1, 1)
    $cell.Shading.BackgroundPatternColor = Get-Rgb 244 246 248
    $cell.VerticalAlignment = 0
    $cell.TopPadding = 7
    $cell.BottomPadding = 7
    $cell.LeftPadding = 9
    $cell.RightPadding = 9
    $range = $cell.Range
    $range.End = $range.End - 1
    $range.Text = ($Lines -join "`r")
    $range.Font.Name = "Consolas"
    $range.Font.Size = 8.5
    $range.Font.Color = Get-Rgb 45 55 65
    $range.ParagraphFormat.SpaceAfter = 0
    $range.ParagraphFormat.LineSpacingRule = 0
    $Selection.SetRange($table.Range.End, $table.Range.End)
    $Selection.TypeParagraph()
    Set-ParagraphBase $Selection
}

function Add-MarkdownTable($Doc, $Selection, [string[]]$Rows) {
    $parsed = New-Object System.Collections.Generic.List[object]
    foreach ($line in $Rows) {
        $trimmed = $line.Trim().Trim('|')
        $cells = @($trimmed -split '\|' | ForEach-Object { $_.Trim() })
        $isSeparator = $true
        foreach ($cell in $cells) {
            if ($cell -notmatch '^:?-{3,}:?$') { $isSeparator = $false; break }
        }
        if (-not $isSeparator) { $parsed.Add($cells) }
    }
    if ($parsed.Count -eq 0) { return }
    $columns = ($parsed | ForEach-Object { $_.Count } | Measure-Object -Maximum).Maximum
    $table = $Doc.Tables.Add($Selection.Range, $parsed.Count, $columns)
    $table.Style = -155
    $table.AllowAutoFit = -1
    $table.AutoFitBehavior(2)
    $table.Rows.AllowBreakAcrossPages = if ($parsed.Count -gt 12) { -1 } else { 0 }
    for ($r = 1; $r -le $parsed.Count; $r++) {
        $values = $parsed[$r - 1]
        for ($c = 1; $c -le $columns; $c++) {
            $cell = $table.Cell($r, $c)
            $value = if ($c -le $values.Count) { Clean-Inline $values[$c - 1] } else { "" }
            $range = $cell.Range
            $range.End = $range.End - 1
            $range.Text = $value
            $range.Font.Name = "Aptos"
            $range.Font.Size = 8.3
            $range.Font.Color = Get-Rgb 35 43 50
            $range.ParagraphFormat.SpaceAfter = 2
            $range.ParagraphFormat.SpaceBefore = 2
            $cell.VerticalAlignment = 1
            $cell.TopPadding = 4
            $cell.BottomPadding = 4
            $cell.LeftPadding = 5
            $cell.RightPadding = 5
            if ($r -eq 1) {
                $range.Font.Bold = -1
                $range.Font.Color = Get-Rgb 255 255 255
                $cell.Shading.BackgroundPatternColor = Get-Rgb 31 78 121
            }
            elseif (($r % 2) -eq 1) {
                $cell.Shading.BackgroundPatternColor = Get-Rgb 242 246 250
            }
        }
    }
    $table.Rows.Item(1).HeadingFormat = -1
    $Selection.SetRange($table.Range.End, $table.Range.End)
    $Selection.TypeParagraph()
    Set-ParagraphBase $Selection
}

$source = (Resolve-Path -LiteralPath $InputPath).Path
$target = [System.IO.Path]::GetFullPath($OutputPath)
$pdfTarget = if ([string]::IsNullOrWhiteSpace($PdfPath)) { "" } else { [System.IO.Path]::GetFullPath($PdfPath) }
$lines = Get-Content -LiteralPath $source -Encoding UTF8
$fenceCount = @($lines | Where-Object { $_.Trim().StartsWith('```') }).Count
if (($fenceCount % 2) -ne 0) { throw "Markdown inválido: cerca de código não fechada." }
$pageBreakCount = @($lines | Where-Object { $_.Trim() -eq '<!-- PAGEBREAK -->' }).Count
if ($pageBreakCount -ne 1) { throw "Markdown inválido: esperado exatamente um marcador PAGEBREAK; encontrado $pageBreakCount." }

$word = $null
$doc = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $doc = $word.Documents.Add()

    $neutralAuthor = "Grupo do TCC — Ciência da Computação"
    try { $doc.RemovePersonalInformation = $true } catch {}
    try { $doc.BuiltInDocumentProperties.Item("Title").Value = "Desenvolvimento e implementação de uma arquitetura de proteção na integração de LLMs em ERPs" } catch {}
    try { $doc.BuiltInDocumentProperties.Item("Subject").Value = "Plano-mestre de pesquisa, implementação e avaliação experimental em Odoo" } catch {}
    try { $doc.BuiltInDocumentProperties.Item("Author").Value = $neutralAuthor } catch {}
    try { $doc.BuiltInDocumentProperties.Item("Last Author").Value = $neutralAuthor } catch {}
    try { $doc.BuiltInDocumentProperties.Item("Keywords").Value = "LLM; prompt injection indireta; Odoo; ERP; Contas a Pagar; segurança" } catch {}

    $doc.PageSetup.PaperSize = 7
    $doc.PageSetup.TopMargin = $word.CentimetersToPoints(2.3)
    $doc.PageSetup.BottomMargin = $word.CentimetersToPoints(2.2)
    $doc.PageSetup.LeftMargin = $word.CentimetersToPoints(2.7)
    $doc.PageSetup.RightMargin = $word.CentimetersToPoints(2.2)

    $normal = $doc.Styles.Item(-1)
    $normal.Font.Name = "Aptos"
    $normal.Font.Size = 10.5
    $normal.Font.Color = Get-Rgb 35 43 50
    $normal.ParagraphFormat.SpaceAfter = 6
    $normal.ParagraphFormat.LineSpacingRule = 5
    $normal.ParagraphFormat.LineSpacing = 13.5

    $selection = $word.Selection
    $selection.HomeKey(6) | Out-Null
    $onCover = $true
    $firstTitle = $true
    $firstSubtitle = $true
    $firstBodyHeading = $true
    $inCode = $false
    $codeLines = New-Object System.Collections.Generic.List[string]
    $i = 0

    while ($i -lt $lines.Count) {
        $line = $lines[$i]

        if ($inCode) {
            if ($line.Trim() -eq '```') {
                Add-CodeBlock $doc $selection $codeLines.ToArray()
                $codeLines.Clear()
                $inCode = $false
            } else {
                $codeLines.Add($line)
            }
            $i++
            continue
        }

        if ($line.Trim().StartsWith('```')) {
            $inCode = $true
            $i++
            continue
        }

        if ($line.Trim() -eq '<!-- PAGEBREAK -->') {
            $selection.InsertBreak(2)
            $onCover = $false
            $selection.ParagraphFormat.Alignment = 0
            $selection.Style = -1

            $selection.Style = -63
            $selection.Font.Name = "Aptos Display"
            $selection.Font.Size = 20
            $selection.Font.Bold = -1
            $selection.Font.Color = Get-Rgb 23 54 93
            $selection.TypeText("SUM$([char]0x00C1)RIO")
            $selection.TypeParagraph()
            $selection.Style = -1
            $toc = $doc.TablesOfContents.Add($selection.Range, $true, 1, 3)
            $selection.SetRange($toc.Range.End, $toc.Range.End)
            $selection.TypeParagraph()
            $selection.InsertBreak(7)
            $i++
            continue
        }

        if ($line -match '^\|.*\|$') {
            $tableLines = New-Object System.Collections.Generic.List[string]
            while ($i -lt $lines.Count -and $lines[$i] -match '^\|.*\|$') {
                $tableLines.Add($lines[$i])
                $i++
            }
            Add-MarkdownTable $doc $selection $tableLines.ToArray()
            continue
        }

        if ([string]::IsNullOrWhiteSpace($line)) {
            $i++
            continue
        }

        if ($line -match '^(#{1,3})\s+(.+)$') {
            $level = $Matches[1].Length
            $text = $Matches[2]
            if ($onCover -and $firstTitle -and $level -eq 1) {
                $selection.Style = -63
                $selection.Font.Name = "Aptos Display"
                $selection.Font.Size = 24
                $selection.Font.Bold = -1
                $selection.Font.Color = Get-Rgb 23 54 93
                $selection.ParagraphFormat.Alignment = 1
                $selection.ParagraphFormat.SpaceBefore = 70
                $selection.ParagraphFormat.SpaceAfter = 14
                Write-Inline $doc $selection $text
                $selection.TypeParagraph()
                $firstTitle = $false
            }
            elseif ($onCover -and $firstSubtitle -and $level -eq 2) {
                $selection.Style = -63
                $selection.Font.Name = "Aptos Display"
                $selection.Font.Size = 14
                $selection.Font.Bold = 0
                $selection.Font.Color = Get-Rgb 76 95 115
                $selection.ParagraphFormat.Alignment = 1
                $selection.ParagraphFormat.SpaceAfter = 28
                Write-Inline $doc $selection $text
                $selection.TypeParagraph()
                $firstSubtitle = $false
            }
            else {
                $break = ($level -eq 1 -and -not $firstBodyHeading)
                Add-Heading $doc $selection $level $text $break
                if ($level -eq 1) { $firstBodyHeading = $false }
            }
            $i++
            continue
        }

        if ($line -match '^>\s?(.*)$') {
            if ($onCover) {
                Add-StandardParagraph $doc $selection $Matches[1] "coverquote"
            }
            else {
                Add-StandardParagraph $doc $selection $Matches[1] "quote"
            }
            $i++
            continue
        }

        if ($line -match '^\s*[-*]\s+(.+)$') {
            Add-StandardParagraph $doc $selection $Matches[1] "bullet"
            $i++
            continue
        }

        if ($line -match '^\s*(\d+)\.\s+(.+)$') {
            Add-StandardParagraph $doc $selection ($Matches[1] + '|' + $Matches[2]) "number"
            $i++
            continue
        }

        if ($onCover) {
            Set-ParagraphBase $selection
            $selection.ParagraphFormat.Alignment = 1
            $selection.ParagraphFormat.SpaceAfter = 5
            Write-Inline $doc $selection $line
            $selection.TypeParagraph()
        }
        else {
            Add-StandardParagraph $doc $selection $line "normal"
        }
        $i++
    }

    if ($inCode -and $codeLines.Count -gt 0) {
        Add-CodeBlock $doc $selection $codeLines.ToArray()
    }

    foreach ($section in $doc.Sections) {
        if ($section.Index -eq 1) {
            $section.Headers.Item(1).Range.Text = ""
            $section.Footers.Item(1).Range.Text = ""
            continue
        }
        $section.Headers.Item(1).LinkToPrevious = $false
        $header = $section.Headers.Item(1).Range
        $header.Text = "TCC  |  Plano-mestre de pesquisa e avaliação experimental"
        $header.Font.Name = "Aptos"
        $header.Font.Size = 8
        $header.Font.Color = Get-Rgb 76 95 115
        $header.ParagraphFormat.Alignment = 0
        $header.Borders.Item(-3).LineStyle = 1
        $header.Borders.Item(-3).Color = Get-Rgb 190 205 220

        $section.Footers.Item(1).LinkToPrevious = $false
        $footer = $section.Footers.Item(1).Range
        $footer.Text = ""
        $footer.ParagraphFormat.Alignment = 2
        $footer.Font.Name = "Aptos"
        $footer.Font.Size = 8
        $footer.Font.Color = Get-Rgb 76 95 115
        $null = $footer.Fields.Add($footer, -1, "PAGE")
        $section.Footers.Item(1).PageNumbers.RestartNumberingAtSection = $true
        $section.Footers.Item(1).PageNumbers.StartingNumber = 1
    }

    foreach ($tocItem in $doc.TablesOfContents) { $tocItem.Update() }
    $doc.Fields.Update() | Out-Null
    $doc.Repaginate()

    $outputDirectory = Split-Path -Parent $target
    if (-not (Test-Path -LiteralPath $outputDirectory)) { New-Item -ItemType Directory -Path $outputDirectory | Out-Null }
    try { $doc.RemovePersonalInformation = $true } catch {}
    try { $doc.RemoveDocumentInformation(4) } catch {}
    try { $doc.BuiltInDocumentProperties.Item("Author").Value = $neutralAuthor } catch {}
    try { $doc.BuiltInDocumentProperties.Item("Last Author").Value = $neutralAuthor } catch {}
    $doc.SaveAs2($target, 16)
    if (-not [string]::IsNullOrWhiteSpace($pdfTarget)) {
        $pdfDirectory = Split-Path -Parent $pdfTarget
        if (-not (Test-Path -LiteralPath $pdfDirectory)) { New-Item -ItemType Directory -Path $pdfDirectory | Out-Null }
        $doc.ExportAsFixedFormat($pdfTarget, 17)
    }

    $pages = $doc.ComputeStatistics(2)
    $paragraphs = $doc.Paragraphs.Count
    $tables = $doc.Tables.Count

    # Word may silently ignore or later overwrite built-in metadata. Close it
    # first, then update the OPC package directly and never resave in Word.
    $doc.Close($false)
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($doc)
    $doc = $null
    $word.Quit()
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($word)
    $word = $null
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()

    Set-NeutralDocxMetadata -Path $target -NeutralAuthor $neutralAuthor
    Write-Output ("DOCX={0}`nPDF={1}`nPages={2}`nParagraphs={3}`nTables={4}" -f $target, $pdfTarget, $pages, $paragraphs, $tables)
}
catch {
    Write-Error ("DOCX build failed: {0}`n{1}" -f $_.Exception.Message, $_.ScriptStackTrace)
    throw
}
finally {
    if ($doc -ne $null) { $doc.Close($false) }
    if ($word -ne $null) { $word.Quit() }
    if ($doc -ne $null) { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($doc) }
    if ($word -ne $null) { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
