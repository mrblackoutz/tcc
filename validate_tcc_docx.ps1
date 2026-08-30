param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [string]$SourcePath = "",
    [string]$PdfPath = "",
    [ValidateSet("draft", "submission")]
    [string]$Mode = "draft"
)

$ErrorActionPreference = "Stop"
$validationErrors = New-Object System.Collections.Generic.List[string]
$validationWarnings = New-Object System.Collections.Generic.List[string]

function Add-ValidationError([string]$Message) {
    $validationErrors.Add($Message)
}

function Add-ValidationWarning([string]$Message) {
    $validationWarnings.Add($Message)
}

function ConvertTo-SafeXml([string]$Content) {
    $settings = New-Object System.Xml.XmlReaderSettings
    $settings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
    $settings.XmlResolver = $null
    $stringReader = New-Object System.IO.StringReader($Content)
    $xmlReader = [System.Xml.XmlReader]::Create($stringReader, $settings)
    try {
        $xmlDocument = New-Object System.Xml.XmlDocument
        $xmlDocument.XmlResolver = $null
        $xmlDocument.Load($xmlReader)
        return $xmlDocument
    }
    finally {
        $xmlReader.Dispose()
        $stringReader.Dispose()
    }
}

$fullPath = (Resolve-Path -LiteralPath $Path).Path
$docxInfo = Get-Item -LiteralPath $fullPath
if ($docxInfo.Length -lt 50000) { Add-ValidationError "DOCX anormalmente pequeno: $($docxInfo.Length) bytes." }

$expectedMetadataAuthor = 'Grupo do TCC — Ciência da Computação'
$expectedMetadataTitle = 'Desenvolvimento e implementação de uma arquitetura de proteção na integração de LLMs em ERPs'
$expectedMetadataSubject = 'Plano-mestre de pesquisa, implementação e avaliação experimental em Odoo'
$expectedMetadataKeywords = 'LLM; prompt injection indireta; Odoo; ERP; Contas a Pagar; segurança'
$allowedWordMetadataAuthors = @('', 'Author', $expectedMetadataAuthor)
$coreCreator = ''
$coreLastModifiedBy = ''
$coreTitle = ''
$coreSubject = ''
$coreKeywords = ''
$externalRelationships = 0
$externalHyperlinkTargets = New-Object System.Collections.Generic.List[string]
$packageEntries = @()

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($fullPath)
try {
    $packageEntries = @($archive.Entries | ForEach-Object { $_.FullName })
    $entryNames = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    [long]$totalUncompressedBytes = 0
    foreach ($entry in $archive.Entries) {
        $entryName = [string]$entry.FullName
        $totalUncompressedBytes += $entry.Length
        if (-not $entryNames.Add($entryName)) { Add-ValidationError "Pacote DOCX contém nome de parte duplicado." }
        if ($entryName.StartsWith('/') -or $entryName.Contains('\') -or @($entryName.Split('/') | Where-Object { $_ -eq '..' }).Count -gt 0) {
            Add-ValidationError "Pacote DOCX contém caminho de parte anômalo."
        }
        if ($entry.Length -gt 10MB) { Add-ValidationError "Pacote DOCX contém parte descomprimida acima de 10 MiB." }
        if ($entry.CompressedLength -gt 0 -and $entry.Length -gt 1MB -and ($entry.Length / $entry.CompressedLength) -gt 200) {
            Add-ValidationError "Pacote DOCX contém razão de compressão anômala."
        }
    }
    if ($totalUncompressedBytes -gt 100MB) { Add-ValidationError "Pacote DOCX excede 100 MiB descomprimidos." }

    $contentTypesEntry = $archive.GetEntry('[Content_Types].xml')
    if ($null -eq $contentTypesEntry) {
        Add-ValidationError "Pacote DOCX não contém [Content_Types].xml."
    }
    else {
        $contentTypesReader = [System.IO.StreamReader]::new($contentTypesEntry.Open())
        try { $contentTypesText = $contentTypesReader.ReadToEnd() } finally { $contentTypesReader.Dispose() }
        $contentTypesXml = ConvertTo-SafeXml $contentTypesText
        $contentTypeNamespaces = New-Object System.Xml.XmlNamespaceManager($contentTypesXml.NameTable)
        $contentTypeNamespaces.AddNamespace('ct', 'http://schemas.openxmlformats.org/package/2006/content-types')
        $mainOverride = $contentTypesXml.SelectSingleNode("//ct:Override[@PartName='/word/document.xml']", $contentTypeNamespaces)
        $expectedMainContentType = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'
        if ($null -eq $mainOverride -or [string]$mainOverride.ContentType -cne $expectedMainContentType) {
            Add-ValidationError "Pacote não declara o main part DOCX macro-free esperado."
        }
        foreach ($typeNode in $contentTypesXml.SelectNodes('//*[@ContentType]')) {
            if ([string]$typeNode.ContentType -match '(?i)(macroEnabled|vba|activeX|oleObject)') {
                Add-ValidationError "Pacote DOCX declara tipo de conteúdo ativo ou incorporado."
            }
        }
    }

    $coreEntry = $archive.GetEntry('docProps/core.xml')
    if ($null -eq $coreEntry) {
        Add-ValidationError "Pacote DOCX não contém docProps/core.xml."
    }
    else {
        $coreReader = [System.IO.StreamReader]::new($coreEntry.Open())
        try { $coreXmlText = $coreReader.ReadToEnd() } finally { $coreReader.Dispose() }
        $coreXml = ConvertTo-SafeXml $coreXmlText
        $coreNamespaces = New-Object System.Xml.XmlNamespaceManager($coreXml.NameTable)
        $coreNamespaces.AddNamespace('dc', 'http://purl.org/dc/elements/1.1/')
        $coreNamespaces.AddNamespace('cp', 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties')
        $creatorNode = $coreXml.SelectSingleNode('//dc:creator', $coreNamespaces)
        $lastModifiedByNode = $coreXml.SelectSingleNode('//cp:lastModifiedBy', $coreNamespaces)
        $titleNode = $coreXml.SelectSingleNode('//dc:title', $coreNamespaces)
        $subjectNode = $coreXml.SelectSingleNode('//dc:subject', $coreNamespaces)
        $keywordsNode = $coreXml.SelectSingleNode('//cp:keywords', $coreNamespaces)
        if ($null -ne $creatorNode) { $coreCreator = [string]$creatorNode.InnerText }
        if ($null -ne $lastModifiedByNode) { $coreLastModifiedBy = [string]$lastModifiedByNode.InnerText }
        if ($null -ne $titleNode) { $coreTitle = [string]$titleNode.InnerText }
        if ($null -ne $subjectNode) { $coreSubject = [string]$subjectNode.InnerText }
        if ($null -ne $keywordsNode) { $coreKeywords = [string]$keywordsNode.InnerText }
    }

    if ($coreCreator -cne $expectedMetadataAuthor) {
        Add-ValidationError "Metadado DOCX creator não corresponde ao autor institucional."
    }
    if ($coreLastModifiedBy -cne $expectedMetadataAuthor) {
        Add-ValidationError "Metadado DOCX lastModifiedBy não corresponde ao autor institucional."
    }
    if ($coreTitle -cne $expectedMetadataTitle) { Add-ValidationError "Metadado DOCX title está ausente ou incorreto." }
    if ($coreSubject -cne $expectedMetadataSubject) { Add-ValidationError "Metadado DOCX subject está ausente ou incorreto." }
    if ($coreKeywords -cne $expectedMetadataKeywords) { Add-ValidationError "Metadado DOCX keywords está ausente ou incorreto." }

    $forbiddenPackagePatterns = @(
        '(?i)vbaProject|vbaData|macroEnabled',
        '(?i)(^|/)(activeX|embeddings)(/|$)',
        '(?i)(oleObject|controlProps?|attachedTemplate|aFChunk|externalLink)',
        '(?i)^word/comments[^/]*\.xml$',
        '(?i)^word/people\.xml$',
        '(?i)^customXml/'
    )
    foreach ($entryName in $packageEntries) {
        foreach ($pattern in $forbiddenPackagePatterns) {
            if ($entryName -match $pattern) {
                Add-ValidationError "Pacote DOCX contém parte proibida: $entryName"
            }
        }
    }

    foreach ($entry in $archive.Entries) {
        if ($entry.FullName -match '^word/.*\.xml$') {
            $xmlReader = [System.IO.StreamReader]::new($entry.Open())
            try { $xmlText = $xmlReader.ReadToEnd() } finally { $xmlReader.Dispose() }
            $trackedChangePattern = '<w:(?:ins|del|moveFrom|moveTo|trackRevisions|pPrChange|rPrChange|tblPrChange|tcPrChange|sectPrChange|customXmlInsRangeStart|customXmlDelRangeStart|cellIns|cellDel|cellMerge)\b'
            if ($xmlText -match $trackedChangePattern) {
                Add-ValidationError "Pacote DOCX contém alterações controladas em $($entry.FullName)."
            }
            if ($xmlText -match '<w:(?:commentRangeStart|commentRangeEnd|commentReference)\b') {
                Add-ValidationError "Pacote DOCX contém marcação de comentário em $($entry.FullName)."
            }
            foreach ($fieldMatch in [regex]::Matches($xmlText, '<w:instrText[^>]*>(.*?)</w:instrText>', 'Singleline')) {
                $fieldInstruction = [System.Net.WebUtility]::HtmlDecode($fieldMatch.Groups[1].Value).Trim()
                $fieldName = @($fieldInstruction -split '\s+')[0].ToUpperInvariant()
                if ($fieldName -notin @('PAGE', 'PAGEREF', 'TOC')) {
                    Add-ValidationError "Pacote DOCX contém campo não permitido em $($entry.FullName)."
                }
            }
        }
        elseif ($entry.FullName.EndsWith('.rels', [System.StringComparison]::OrdinalIgnoreCase)) {
            $relsReader = [System.IO.StreamReader]::new($entry.Open())
            try { $relsText = $relsReader.ReadToEnd() } finally { $relsReader.Dispose() }
            $relsXml = ConvertTo-SafeXml $relsText
            foreach ($relationship in @($relsXml.Relationships.Relationship)) {
                if ([string]$relationship.TargetMode -eq 'External') {
                    $externalRelationships++
                    $relationshipType = [string]$relationship.Type
                    $target = [string]$relationship.Target
                    $allowedHyperlinkTypes = @(
                        'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink',
                        'http://purl.oclc.org/ooxml/officeDocument/relationships/hyperlink'
                    )
                    if ($relationshipType -notin $allowedHyperlinkTypes) {
                        Add-ValidationError "Pacote DOCX contém relacionamento externo inesperado em $($entry.FullName)."
                    }
                    else {
                        $uri = $null
                        if (-not [System.Uri]::TryCreate($target, [System.UriKind]::Absolute, [ref]$uri) -or
                            $uri.Scheme -cne 'https' -or
                            -not [string]::IsNullOrEmpty($uri.UserInfo) -or
                            -not [string]::IsNullOrEmpty($uri.Query) -or
                            -not [string]::IsNullOrEmpty($uri.Fragment)) {
                            Add-ValidationError "Pacote DOCX contém hyperlink externo fora da política em $($entry.FullName)."
                        }
                        else {
                            $externalHyperlinkTargets.Add($target)
                        }
                    }
                }
            }
        }
    }
}
finally {
    $archive.Dispose()
}

if (-not [string]::IsNullOrWhiteSpace($SourcePath)) {
    $fullSourcePath = (Resolve-Path -LiteralPath $SourcePath).Path
    $sourceInfo = Get-Item -LiteralPath $fullSourcePath
    if ($docxInfo.LastWriteTimeUtc -lt $sourceInfo.LastWriteTimeUtc) {
        Add-ValidationError "DOCX está mais antigo que a fonte Markdown."
    }

    $sourceLines = Get-Content -LiteralPath $fullSourcePath -Encoding UTF8
    $sourceUrls = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    foreach ($urlMatch in [regex]::Matches(($sourceLines -join "`n"), 'https://[^\s)>]+')) {
        [void]$sourceUrls.Add($urlMatch.Value)
    }
    foreach ($externalTarget in $externalHyperlinkTargets) {
        if (-not $sourceUrls.Contains($externalTarget)) {
            Add-ValidationError "DOCX contém hyperlink HTTPS que não está presente na fonte Markdown."
        }
    }
    $fenceCount = @($sourceLines | Where-Object { $_.Trim().StartsWith('```') }).Count
    if (($fenceCount % 2) -ne 0) { Add-ValidationError "Fonte Markdown possui cerca de código não fechada." }

    $pageBreakCount = @($sourceLines | Where-Object { $_.Trim() -eq '<!-- PAGEBREAK -->' }).Count
    if ($pageBreakCount -ne 1) { Add-ValidationError "Fonte deve conter exatamente um PAGEBREAK; encontrado $pageBreakCount." }

    $expectedColumns = $null
    $tableStartLine = 0
    for ($lineIndex = 0; $lineIndex -lt $sourceLines.Count; $lineIndex++) {
        $sourceLine = $sourceLines[$lineIndex]
        if ($sourceLine -match '^\|.*\|$') {
            $columnCount = $sourceLine.Trim().Trim('|').Split('|').Count
            if ($null -eq $expectedColumns) {
                $expectedColumns = $columnCount
                $tableStartLine = $lineIndex + 1
            }
            elseif ($columnCount -ne $expectedColumns) {
                Add-ValidationError "Tabela iniciada na linha $tableStartLine tem $columnCount colunas na linha $($lineIndex + 1); esperado $expectedColumns."
            }
        }
        else {
            $expectedColumns = $null
            $tableStartLine = 0
        }
    }
}

if (-not [string]::IsNullOrWhiteSpace($PdfPath)) {
    $fullPdfPath = (Resolve-Path -LiteralPath $PdfPath).Path
    $pdfInfo = Get-Item -LiteralPath $fullPdfPath
    if ($pdfInfo.Length -lt 50000) { Add-ValidationError "PDF anormalmente pequeno: $($pdfInfo.Length) bytes." }
    if ($null -ne $sourceInfo -and $pdfInfo.LastWriteTimeUtc -lt $sourceInfo.LastWriteTimeUtc) {
        Add-ValidationError "PDF está mais antigo que a fonte Markdown."
    }
    $pdfStream = [System.IO.File]::OpenRead($fullPdfPath)
    try {
        $signatureBytes = New-Object byte[] 5
        $null = $pdfStream.Read($signatureBytes, 0, 5)
        $signature = [System.Text.Encoding]::ASCII.GetString($signatureBytes)
        if ($signature -ne '%PDF-') { Add-ValidationError "Assinatura PDF inválida: $signature" }
    }
    finally {
        $pdfStream.Dispose()
    }
}

$word = $null
$doc = $null
$statistics = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3
    $word.Options.UpdateLinksAtOpen = $false
    $doc = $word.Documents.Open($fullPath, $false, $true)
    $doc.Repaginate()

    $author = ""
    $lastAuthor = ""
    try { $author = [string]$doc.BuiltInDocumentProperties.Item("Author").Value } catch {}
    try { $lastAuthor = [string]$doc.BuiltInDocumentProperties.Item("Last Author").Value } catch {}
    $contentText = [string]$doc.Content.Text
    $placeholderMatches = [regex]::Matches($contentText, '\[(preencher|data|nome|nomes|número)\]', 'IgnoreCase')

    $statistics = [PSCustomObject]@{
        Pages = $doc.ComputeStatistics(2)
        Words = $doc.ComputeStatistics(0)
        Paragraphs = $doc.Paragraphs.Count
        Tables = $doc.Tables.Count
        Sections = $doc.Sections.Count
        TablesOfContents = $doc.TablesOfContents.Count
        Hyperlinks = $doc.Hyperlinks.Count
        Characters = $doc.ComputeStatistics(3)
        Placeholders = $placeholderMatches.Count
        CoreMetadataApproved = (($coreCreator -ceq $expectedMetadataAuthor) -and ($coreLastModifiedBy -ceq $expectedMetadataAuthor) -and ($coreTitle -ceq $expectedMetadataTitle) -and ($coreSubject -ceq $expectedMetadataSubject) -and ($coreKeywords -ceq $expectedMetadataKeywords))
        ExternalRelationships = $externalRelationships
        Comments = $doc.Comments.Count
        Revisions = $doc.Revisions.Count
        Mode = $Mode
    }

    if ($statistics.TablesOfContents -ne 1) { Add-ValidationError "Esperado um sumário; encontrado $($statistics.TablesOfContents)." }
    if ($statistics.Hyperlinks -lt 20) { Add-ValidationError "Poucos hyperlinks: $($statistics.Hyperlinks); esperado ao menos 20." }
    if ($statistics.Words -lt 10000) { Add-ValidationError "Documento abaixo do volume esperado: $($statistics.Words) palavras." }
    if ($statistics.Tables -lt 40) { Add-ValidationError "Documento abaixo do número esperado de tabelas: $($statistics.Tables)." }
    if ($statistics.Sections -lt 2) { Add-ValidationError "Documento deve possuir capa/sumário e corpo em seções distintas." }
    if ($contentText.Contains('**')) { Add-ValidationError "Resíduo Markdown '**' encontrado no DOCX." }
    if ($contentText.Contains('```')) { Add-ValidationError "Cerca de código Markdown encontrada no DOCX." }
    if ($contentText.Contains('<!-- PAGEBREAK -->')) { Add-ValidationError "Marcador PAGEBREAK vazou para o DOCX." }
    if ($allowedWordMetadataAuthors -notcontains $author) { Add-ValidationError "Metadado Word Author não é institucional ou genérico." }
    if ($allowedWordMetadataAuthors -notcontains $lastAuthor) { Add-ValidationError "Metadado Word Last Author não é institucional ou genérico." }
    if ($doc.Comments.Count -ne 0) { Add-ValidationError "DOCX contém $($doc.Comments.Count) comentário(s)." }
    if ($doc.Revisions.Count -ne 0) { Add-ValidationError "DOCX contém $($doc.Revisions.Count) alteração(ões) controlada(s)." }
    if ($doc.TrackRevisions) { Add-ValidationError "DOCX está com controle de alterações ativo." }

    if ($placeholderMatches.Count -gt 0) {
        if ($Mode -eq "submission") {
            Add-ValidationError "Modo submission reprova $($placeholderMatches.Count) placeholders."
        }
        else {
            Add-ValidationWarning "Rascunho contém $($placeholderMatches.Count) placeholders controlados."
        }
    }
}
finally {
    if ($doc -ne $null) { $doc.Close($false) }
    if ($word -ne $null) { $word.Quit() }
    if ($doc -ne $null) { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($doc) }
    if ($word -ne $null) { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

$statistics | Format-List
foreach ($warning in $validationWarnings) { Write-Warning $warning }
if ($validationErrors.Count -gt 0) {
    foreach ($validationError in $validationErrors) { Write-Error $validationError }
    throw "Validação falhou com $($validationErrors.Count) erro(s)."
}

Write-Output "Validation: PASS"
