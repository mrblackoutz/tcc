"""DEC-062/064 deterministic, explicitly split PDFs; no execution rights.

The three layouts are candidates, not fiscal documents or reviewed scientific
templates. Notes are literal text. Reflow only inserts line feeds: existing
spaces are carried to the next line, never silently stripped. Input lines with
trailing spaces, or a run of spaces too wide for a physical line, are rejected.
Blank lines are represented by a space glyph, which the common extraction
normalizer turns back into an empty line. No filesystem operations occur here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import unicodedata

from .dataset_pair import DatasetPair, DatasetPairError, parse_dataset_pair


GENERATOR_VERSION = "ap-ipi-development-pdf/v1"
PILOT_GENERATOR_VERSION = "ap-ipi-pilot-pdf/v1"
MAXIMUM_PDF_BYTES = 1_048_576
MAXIMUM_PAGES = 4
MAXIMUM_TEXT_CHARACTERS = 20_000
LINE_COLUMNS = 88
PAGE_ROWS = 49
SYNTHETIC_MARK = "DOCUMENTO SINTÉTICO - SEM VALOR FISCAL"


class DatasetPdfError(ValueError):
    """Finite diagnostic without text, document contents, labels or paths."""


def _fail() -> None:
    raise DatasetPdfError("invalid development PDF input or limits")


@dataclass(frozen=True, slots=True)
class RenderedDevelopmentPdf:
    """Legacy structural name reused by the explicit development/pilot APIs."""

    pdf_bytes: bytes = field(repr=False)
    expected_text: str = field(repr=False)
    page_count: int

    def __post_init__(self) -> None:
        if (type(self.pdf_bytes) is not bytes
                or not self.pdf_bytes.startswith(b"%PDF-1.4\n")
                or len(self.pdf_bytes) > MAXIMUM_PDF_BYTES
                or type(self.expected_text) is not str
                or not self.expected_text
                or len(self.expected_text) > MAXIMUM_TEXT_CHARACTERS
                or type(self.page_count) is not int
                or not 1 <= self.page_count <= MAXIMUM_PAGES):
            _fail()


def _valid_text(text: str) -> None:
    if (type(text) is not str or len(text) > MAXIMUM_TEXT_CHARACTERS
            or unicodedata.normalize("NFC", text) != text
            or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"}
                   for char in text if char != "\n")
            or any(line.rstrip() != line for line in text.split("\n"))):
        _fail()
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        _fail()


def _wrap(text: str) -> list[str]:
    """Add line feeds without removing ordinary spaces or input newlines."""
    _valid_text(text)
    output: list[str] = []
    for original in text.split("\n"):
        remaining = original
        while len(remaining) > LINE_COLUMNS:
            end = LINE_COLUMNS
            # A trailing space would be erased by the ingestion normalizer.
            # Carry the whole space suffix instead of stripping it silently.
            while end and remaining[end - 1].isspace():
                end -= 1
            if not end:
                _fail()
            output.append(remaining[:end])
            remaining = remaining[end:]
        if remaining and remaining.rstrip() != remaining:
            _fail()
        output.append(remaining)
    return output


def _commercial_sections(value: dict) -> tuple[list[str], list[str]]:
    # Deliberate allowlist: evaluator/action/identity fields are never read.
    truth = value["truth"]
    company, vendor = truth["company_ref"], truth["vendor_ref"]
    order, document = truth["purchase_order_ref"], truth["document_ref"]
    date, currency = truth["invoice_date"], truth["currency"]
    bank, amount = truth["approved_bank_ref"], truth["amount"]
    template = value["template_id"]
    if template == "T1":
        before = [
            "DEMONSTRATIVO DE COBRANÇA", "",
            f"Empresa de referência: {company}", f"Fornecedor: {vendor}",
            f"Pedido de compra: {order}", f"Documento: {document}",
            f"Data de emissão: {date}", f"Moeda: {currency}",
            f"Referência bancária: {bank}", "",
        ]
        after = ["DISCRIMINAÇÃO DOS ITENS"]
        for index, line in enumerate(truth["lines"], 1):
            after.extend([
                f"{index:02d} | Item: {line['item_code']}",
                f"Quantidade: {line['quantity']} | Unitário: {line['unit_price']}"
                f" | Total da linha: {line['line_total']}",
            ])
        after.extend(["", f"TOTAL A PAGAR: {currency} {amount}"])
    elif template == "T2":
        before = [
            "RESUMO FINANCEIRO DE FORNECIMENTO", "",
            f"Documento {document}", f"Emissão {date} | Moeda {currency}",
            f"Fornecedor de referência: {vendor}", f"Comprador de referência: {company}",
            f"Pedido vinculado: {order}", f"Conta para conferência: {bank}", "",
        ]
        after = ["COMPOSIÇÃO DO FORNECIMENTO"]
        for index, line in enumerate(truth["lines"], 1):
            after.extend([
                f"Item {index:02d} - {line['item_code']} | Quantidade {line['quantity']}",
                f"Preço unitário {currency} {line['unit_price']}"
                f" | Subtotal {currency} {line['line_total']}",
            ])
        after.extend(["", f"VALOR TOTAL DO DOCUMENTO: {currency} {amount}"])
    else:  # Parser has already checked the closed template enumeration.
        before = [
            "CARTA DE COBRANÇA - AMBIENTE EXPERIMENTAL", "",
            "DADOS DA EMISSÃO", f"Documento: {document}", f"Emissão: {date}",
            f"Referência da empresa: {company}", f"Referência do fornecedor: {vendor}",
            f"Referência do pedido: {order}", f"Moeda declarada: {currency}",
            f"Conta de referência para conferência: {bank}", "",
        ]
        after = ["RELAÇÃO COMERCIAL"]
        for index, line in enumerate(truth["lines"], 1):
            after.extend([
                f"Linha {index:02d}: {line['item_code']} - {line['quantity']} unidades",
                f"Preço por unidade: {line['unit_price']} {currency}"
                f"; valor da linha: {line['line_total']} {currency}",
            ])
        after.extend(["", f"TOTAL DECLARADO: {amount} {currency}"])
    return ([part for line in before for part in _wrap(line)],
            [part for line in after for part in _wrap(line)])


def _pages(value: dict, note: str) -> list[list[str]]:
    before, after = _commercial_sections(value)
    note_lines = ["OBSERVAÇÕES DO DOCUMENTO:", *_wrap(note)]
    if value["placement"] == "BODY":
        lines = [*before, *note_lines, "", *after]
    else:
        commercial = [*before, *after, ""]
        # Keep a short footer block together at the bottom of its page. Long
        # notes flow after the commercial facts, retaining every input line.
        remainder = len(commercial) % PAGE_ROWS
        available = PAGE_ROWS - remainder if remainder else PAGE_ROWS
        if len(note_lines) <= PAGE_ROWS:
            if len(note_lines) > available:
                commercial.extend([""] * available)
                available = PAGE_ROWS
            commercial.extend([""] * (available - len(note_lines)))
        lines = [*commercial, *note_lines]
    pages = [lines[start:start + PAGE_ROWS]
             for start in range(0, len(lines), PAGE_ROWS)]
    if not 1 <= len(pages) <= MAXIMUM_PAGES:
        _fail()
    return pages


def _escape(value: str) -> bytes:
    # Only literal PDF strings are used. Untrusted text cannot create an
    # operator, object, action, link or annotation by closing a string.
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("cp1252")


def _page_lines(lines: list[str], index: int, count: int) -> list[str]:
    return [SYNTHETIC_MARK, *lines,
            f"PÁGINA {index}/{count} - DOCUMENTO EXPERIMENTAL SEM VALOR FISCAL"]


def _pdf(pages: list[list[str]], generator_version: str) -> tuple[bytes, str]:
    count = len(pages)
    # Fixed object numbering; no document IDs, timestamps or local names.
    font_id = 3 + 2 * count
    info_id = font_id + 1
    kids = " ".join(f"{3 + 2 * index} 0 R" for index in range(count))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode("ascii"),
    ]
    all_lines: list[str] = []
    for index, lines in enumerate(pages):
        page_id = 3 + index * 2
        objects.append((
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {page_id + 1} 0 R >>"
        ).encode("ascii"))
        commands = [b"BT", b"/F1 9 Tf", b"48 806 Td", b"14 TL",
                    b"(" + _escape(SYNTHETIC_MARK) + b") Tj", b"0 -28 Td"]
        for row, line in enumerate(lines):
            commands.append(b"(" + _escape(line or " ") + b") Tj")
            if row != len(lines) - 1:
                commands.append(b"T*")
        footer = _page_lines([], index + 1, count)[-1]
        # Absolute text matrix prevents short pages from moving the footer up.
        commands.extend([b"1 0 0 1 48 58 Tm", b"(" + _escape(footer) + b") Tj", b"ET"])
        stream = b"\n".join(commands) + b"\n"
        objects.append(b"<< /Length " + str(len(stream)).encode("ascii")
                       + b" >>\nstream\n" + stream + b"endstream")
        all_lines.extend(_page_lines(lines, index + 1, count))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>")
    objects.append((
        "<< /Title (TCC SYNTHETIC COMMERCIAL DOCUMENT) "
        f"/Creator (TCC LAB) /Producer ({generator_version}) >>"
    ).encode("ascii"))
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, body in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend((
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {info_id} 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode("ascii"))
    return bytes(output), "\n".join(all_lines)


def _render_pdf(
    pair: DatasetPair, note: str, *, split: str, generator_version: str,
) -> RenderedDevelopmentPdf:
    if type(pair) is not DatasetPair:
        _fail()
    try:
        value = parse_dataset_pair(pair.to_mapping()).to_mapping()
    except (DatasetPairError, AttributeError, TypeError, ValueError):
        _fail()
    if value["split"] != split:
        _fail()
    _valid_text(note)
    pages = _pages(value, note)
    pdf_bytes, expected_text = _pdf(pages, generator_version)
    return RenderedDevelopmentPdf(pdf_bytes, expected_text, len(pages))


def render_development_pdf(pair: DatasetPair, note: str) -> RenderedDevelopmentPdf:
    """Render only development, retaining the original bytes and restrictions.

    This function neither chooses a member nor uses evaluator labels to form
    text. The caller verifies actual extraction before accepting or persisting
    the candidate. It does not mutate source hashes or authenticate the note.
    """
    return _render_pdf(pair, note, split="development", generator_version=GENERATOR_VERSION)


def render_pilot_pdf(pair: DatasetPair, note: str) -> RenderedDevelopmentPdf:
    """Render only pilot-v0 using a distinct generic generator provenance.

    The legacy return type is only a container: this is not development data
    re-labelled as pilot. No member identity, evaluator field or approval is
    printed, and rendering does not authorize a scientific run or publication.
    """
    return _render_pdf(pair, note, split="pilot-v0", generator_version=PILOT_GENERATOR_VERSION)
