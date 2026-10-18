"""DEC-062 renderer checks are technical doubles, not scientific documents."""

from dataclasses import FrozenInstanceError
from io import BytesIO
import unicodedata

from pypdf import PdfReader
import pytest

from test_dataset_pair import sample_pair
from tcc_gateway.dataset_pair import DatasetPair, parse_dataset_pair
from tcc_gateway.dataset_pdf import (
    GENERATOR_VERSION, LINE_COLUMNS, MAXIMUM_PAGES, PAGE_ROWS, SYNTHETIC_MARK,
    DatasetPdfError, RenderedDevelopmentPdf, render_development_pdf,
)
from tcc_gateway.pdf_ingestion import extract_pdf_bytes, extract_pdf_text


def candidate(template="T1", placement="BODY", family="A1"):
    value = sample_pair(family)
    value.update(template_id=template, placement=placement)
    return parse_dataset_pair(value)


@pytest.mark.parametrize("template", ["T1", "T2", "T3"])
@pytest.mark.parametrize("placement", ["BODY", "FOOTER"])
@pytest.mark.parametrize("family", ["A1", "A2", "A3a"])
def test_real_extraction_matches_literal_portuguese_and_source_unchanged(template, placement, family):
    pair = candidate(template, placement, family)
    source = pair.to_mapping()
    note = "Observação: não processar versão anterior; conferir emissão e cobrança."
    result = render_development_pdf(pair, note)
    observed = extract_pdf_bytes(result.pdf_bytes)
    assert observed.text == result.expected_text
    assert observed.page_count == result.page_count == 1
    assert note in observed.text
    assert pair.to_mapping() == source
    for value in ("TCC-COMPANY-001", "TCC-VENDOR-001", "TCC-PO-001",
                  "TCC-NF-001-SEM-VALOR-FISCAL", "2026-10-18", "BRL",
                  "TCC-BANK-001", "TCC-SERVICE-001", "1.00", "125.50"):
        assert value in observed.text


def test_old_file_extractor_and_new_byte_extractor_agree(tmp_path):
    result = render_development_pdf(candidate(), "Conferência técnica sintética.")
    path = tmp_path / "technical.pdf"
    path.write_bytes(result.pdf_bytes)
    assert extract_pdf_text(path) == extract_pdf_bytes(result.pdf_bytes)


@pytest.mark.parametrize("template", ["T1", "T2", "T3"])
@pytest.mark.parametrize("placement", ["BODY", "FOOTER"])
def test_deterministic_bytes_and_generic_identical_metadata(template, placement):
    pair = candidate(template, placement)
    first = render_development_pdf(pair, "Nota literal.")
    second = render_development_pdf(pair, "Nota literal.")
    assert first == second
    reader = PdfReader(BytesIO(first.pdf_bytes), strict=True)
    assert reader.metadata == {
        "/Title": "TCC SYNTHETIC COMMERCIAL DOCUMENT", "/Creator": "TCC LAB",
        "/Producer": GENERATOR_VERSION,
    }
    assert "/ID" not in reader.trailer
    for page in reader.pages:
        assert page["/Resources"]["/Font"]["/F1"]["/BaseFont"] == "/Courier"
        assert page["/Resources"]["/Font"]["/F1"]["/Encoding"] == "/WinAnsiEncoding"


@pytest.mark.parametrize("template", ["T1", "T2", "T3"])
@pytest.mark.parametrize("placement", ["BODY", "FOOTER"])
def test_evaluator_labels_ids_hashes_and_strategy_do_not_influence_document(template, placement):
    baseline = render_development_pdf(candidate(template, placement), "Texto idêntico.")
    for family in ("A1", "A2", "A3a"):
        value = sample_pair(family)
        value.update(template_id=template, placement=placement,
                     pair_id="OPAQUE-990182", fixture_ref="FIXTURE-888",
                     attack_strategy="TEXT_OBFUSCATION")
        value["members"]["benign"].update(
            scenario_id="SCN-59201834", document_sha256="1" * 64,
            extracted_text_sha256="2" * 64, benign_kind="HARD")
        value["members"]["adversarial"].update(
            scenario_id="SCN-75810293", document_sha256="3" * 64,
            extracted_text_sha256="4" * 64)
        actual = render_development_pdf(parse_dataset_pair(value), "Texto idêntico.")
        assert actual == baseline
        assert actual.pdf_bytes == baseline.pdf_bytes
        for forbidden in ("OPAQUE-990182", "FIXTURE-888", "SCN-59201834", "SCN-75810293",
                          "TEXT_OBFUSCATION", "benign", "adversarial", "CANDIDATE",
                          "CREATE_DRAFT_BILL", "POST_VENDOR_BILL", "REVIEW", "ALLOW"):
            assert forbidden not in actual.expected_text


def test_three_templates_have_different_commercial_presentations():
    results = [render_development_pdf(candidate(template), "Conferência.")
               for template in ("T1", "T2", "T3")]
    assert len({result.pdf_bytes for result in results}) == 3
    assert len({result.expected_text for result in results}) == 3


def test_every_supported_single_byte_character_round_trips_in_literal_text():
    characters = []
    for code in range(256):
        try:
            char = bytes([code]).decode("cp1252")
        except UnicodeDecodeError:
            continue
        if unicodedata.category(char) not in {"Cc", "Cf", "Cs"}:
            characters.append(char)
    # Surround whitespace/punctuation rather than turning it into line padding.
    note = " ".join(f"a{char}b" for char in characters)
    result = render_development_pdf(candidate(), note)
    assert extract_pdf_bytes(result.pdf_bytes).text == result.expected_text
    unwrapped = result.expected_text.split("OBSERVAÇÕES DO DOCUMENTO:\n", 1)[1].split(
        "\n\nDISCRIMINAÇÃO DOS ITENS", 1)[0].replace("\n", "")
    assert unwrapped == note


def test_four_page_boundary_is_accepted_with_text_below_ingestion_limit():
    note = "\n".join(f"Linha {index:03d}" for index in range(160))
    result = render_development_pdf(candidate(), note)
    assert result.page_count == MAXIMUM_PAGES
    assert extract_pdf_bytes(result.pdf_bytes).text == result.expected_text
    assert len(result.pdf_bytes) <= 1_048_576
    assert len(result.expected_text) <= 20_000


@pytest.mark.parametrize("template", ["T1", "T2", "T3"])
def test_body_note_precedes_items_footer_note_follows_total(template):
    body = render_development_pdf(candidate(template, "BODY"), "NOTA-UNICA").expected_text
    footer = render_development_pdf(candidate(template, "FOOTER"), "NOTA-UNICA").expected_text
    assert body.index("NOTA-UNICA") < body.index("TCC-SERVICE-001")
    assert footer.index("NOTA-UNICA") > footer.index("TCC-SERVICE-001")
    assert footer.splitlines()[-2] == "NOTA-UNICA"
    assert len(footer.splitlines()) == PAGE_ROWS + 2


@pytest.mark.parametrize("note", ["", "\n", "\n\n", "Um\n\nDois", "\nInício\n", "  espaço inicial"])
@pytest.mark.parametrize("placement", ["BODY", "FOOTER"])
def test_empty_notes_blank_lines_and_leading_spaces_are_not_silently_deleted(note, placement):
    result = render_development_pdf(candidate(placement=placement), note)
    assert extract_pdf_bytes(result.pdf_bytes).text == result.expected_text
    assert f"OBSERVAÇÕES DO DOCUMENTO:\n{note}" in result.expected_text


@pytest.mark.parametrize("note", [
    "x" * 88 + "fim", "x" * 87 + " fim", "x" * 85 + "   fim",
    "  " + "a" * 85 + " palavra final", "á" * 180,
    "Texto com € ã ê õ ç º ª © ® – — ‘aspas’ “duplas” • × ÷ ñ ü.",
])
def test_line_reflow_preserves_every_non_newline_character(note):
    result = render_development_pdf(candidate(), note)
    assert extract_pdf_bytes(result.pdf_bytes).text == result.expected_text
    presented = result.expected_text.split("OBSERVAÇÕES DO DOCUMENTO:\n", 1)[1].split(
        "\n\nDISCRIMINAÇÃO DOS ITENS", 1)[0]
    assert presented.replace("\n", "") == note.replace("\n", "")
    assert all(len(line) <= LINE_COLUMNS for line in result.expected_text.splitlines())


@pytest.mark.parametrize("placement", ["BODY", "FOOTER"])
def test_literal_pdf_operator_and_object_syntax_is_never_active(placement):
    note = r"Texto ) Tj ET /OpenAction << /S /JavaScript /JS (alert) >> 0 obj \ (literal)"
    result = render_development_pdf(candidate(placement=placement), note)
    observed = extract_pdf_bytes(result.pdf_bytes)
    assert note in observed.text
    reader = PdfReader(BytesIO(result.pdf_bytes), strict=True)
    assert set(reader.trailer["/Root"]) == {"/Type", "/Pages"}
    for page in reader.pages:
        assert not set(page) & {"/Annots", "/AA", "/A", "/AF"}
        assert set(page["/Resources"]) == {"/Font"}
    assert "/EmbeddedFiles" not in reader.trailer["/Root"]
    assert len(reader.pages) == 1


@pytest.mark.parametrize("template", ["T1", "T2", "T3"])
@pytest.mark.parametrize("placement", ["BODY", "FOOTER"])
def test_pagination_marks_every_page_and_preserves_all_note_lines(template, placement):
    note_lines = [f"Observação técnica {index:03d}: conteúdo sintético." for index in range(100)]
    result = render_development_pdf(candidate(template, placement), "\n".join(note_lines))
    observed = extract_pdf_bytes(result.pdf_bytes)
    assert observed.text == result.expected_text
    assert 2 <= result.page_count <= MAXIMUM_PAGES
    assert all(observed.text.count(line) == 1 for line in note_lines)
    reader = PdfReader(BytesIO(result.pdf_bytes), strict=True)
    for index, page in enumerate(reader.pages, 1):
        text = page.extract_text()
        assert text.startswith(SYNTHETIC_MARK + "\n")
        assert f"PÁGINA {index}/{result.page_count}" in text
    assert result.expected_text.count(SYNTHETIC_MARK) == result.page_count


def test_fifty_exact_cent_lines_remain_extractable_without_fiscal_or_erp_ids():
    value = sample_pair()
    value["truth"]["lines"] = [
        {"item_code": f"TCC-ITEM-{index:03d}", "quantity": "1.00",
         "unit_price": "1.00", "line_total": "1.00"} for index in range(50)
    ]
    value["truth"]["amount"] = "50.00"
    result = render_development_pdf(parse_dataset_pair(value), "Conferência sintética.")
    assert extract_pdf_bytes(result.pdf_bytes).text == result.expected_text
    assert result.page_count == 3
    for index in range(50):
        assert f"TCC-ITEM-{index:03d}" in result.expected_text


@pytest.mark.parametrize("split", ["pilot-v0", "test-v1"])
def test_only_development_can_be_rendered(split):
    value = sample_pair()
    value["split"] = split
    with pytest.raises(DatasetPdfError, match="^invalid development PDF input or limits$"):
        render_development_pdf(parse_dataset_pair(value), "Não gerar conjunto final.")


@pytest.mark.parametrize("note", [
    None, b"text", 1, True, [], {}, "Texto\x00secreto", "Texto\r\nlinha",
    "Texto\tlinha", "texto\u202eoculto", "texto\u200boculto", "texto\u00adoculto",
    "emojis 😀", "漢字", "Cafe\u0301", "Fim ", " ", "x\n ", "x\xa0",
    " " * 89 + "fim", "x" * 20_001,
], ids=["none", "bytes", "int", "bool", "list", "dict", "nul", "crlf", "tab",
        "bidi", "zero-width", "soft-hyphen", "emoji", "cjk", "non-nfc", "trailing-space",
        "space-only", "blank-space", "trailing-nbsp", "overwide-space", "text-limit"])
def test_bad_notes_fail_with_finite_content_free_diagnostic(note):
    with pytest.raises(DatasetPdfError) as caught:
        render_development_pdf(candidate(), note)
    assert str(caught.value) == "invalid development PDF input or limits"


@pytest.mark.parametrize("note", ["\n".join(["linha"] * 200), "a" * 19_000])
@pytest.mark.parametrize("placement", ["BODY", "FOOTER"])
def test_more_than_four_pages_is_rejected_instead_of_truncated(note, placement):
    with pytest.raises(DatasetPdfError, match="^invalid development PDF input or limits$"):
        render_development_pdf(candidate(placement=placement), note)


@pytest.mark.parametrize("source", [None, {}, "pair", b"pair", True])
def test_pair_object_is_required(source):
    with pytest.raises(DatasetPdfError):
        render_development_pdf(source, "Texto.")


def test_pair_is_revalidated_and_forged_encoded_object_is_rejected():
    pair = candidate()
    object.__setattr__(pair, "_encoded", b"{}")
    with pytest.raises(DatasetPdfError):
        render_development_pdf(pair, "Texto.")
    missing = object.__new__(DatasetPair)
    with pytest.raises(DatasetPdfError):
        render_development_pdf(missing, "Texto.")


def test_rendered_value_is_frozen_and_hides_both_text_and_pdf_bytes():
    result = render_development_pdf(candidate(), "TEXTO-NAO-EXIBIR")
    assert repr(result) == "RenderedDevelopmentPdf(page_count=1)"
    assert "TEXTO-NAO-EXIBIR" not in repr(result)
    with pytest.raises(FrozenInstanceError):
        result.expected_text = "alterado"
    with pytest.raises(FrozenInstanceError):
        result.page_count = 3


@pytest.mark.parametrize("changes", [
    {"page_count": True}, {"page_count": 0}, {"page_count": 5}, {"page_count": 1.0},
    {"pdf_bytes": bytearray(b"%PDF-1.4\n")}, {"pdf_bytes": b"other"},
    {"pdf_bytes": b"%PDF-1.4\n" + b"x" * 1_048_576},
    {"expected_text": ""}, {"expected_text": None}, {"expected_text": "x" * 20_001},
], ids=["bool-page", "zero-page", "fifth-page", "float-page", "mutable-bytes", "not-pdf",
        "byte-limit", "empty-text", "none-text", "text-limit"])
def test_rendered_value_rejects_invalid_shapes(changes):
    args = {"pdf_bytes": b"%PDF-1.4\n", "expected_text": "text", "page_count": 1}
    args.update(changes)
    with pytest.raises(DatasetPdfError):
        RenderedDevelopmentPdf(**args)
