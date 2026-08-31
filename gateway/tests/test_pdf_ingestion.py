from __future__ import annotations

import hashlib

import pytest
from pypdf import PdfWriter

from tcc_gateway.pdf_ingestion import PdfIngestionError, PdfLimits, extract_pdf_text
from tcc_gateway.synthetic_pdf import (
    DOCUMENT_HEADER,
    build_text_layer_pdf,
    m2_document_fields,
    render_m2_document_text,
    write_m2_synthetic_pdf,
)


def _fixture() -> dict[str, object]:
    return {
        "synthetic_data": True,
        "fiscal_value": False,
        "vendor_ref": "TCC-M1-VENDOR",
        "purchase_order_ref": "TCC-M1-PO-001",
        "invoice_date": "2026-08-31",
        "currency_name": "USD",
        "bank_account": "TCC-SYNTHETIC-BANK-0001",
        "product_code": "TCC-M1-SERVICE",
        "amount": "125.50",
    }


def test_synthetic_pdf_is_deterministic_and_has_real_text_layer(tmp_path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"

    expected_fields = write_m2_synthetic_pdf(first, _fixture())
    write_m2_synthetic_pdf(second, _fixture())
    extracted = extract_pdf_text(first)

    assert first.read_bytes() == second.read_bytes()
    assert extracted.document_sha256 == hashlib.sha256(first.read_bytes()).hexdigest()
    assert extracted.page_count == 1
    assert extracted.byte_count < 10_000
    assert extracted.text.splitlines()[0] == DOCUMENT_HEADER
    assert "DOCUMENT_REF: TCC-M2-NF-001-SEM-VALOR-FISCAL" in extracted.text
    assert expected_fields["TOTAL"] == "125.50"


def test_rendered_text_and_pdf_are_independent_of_mapping_order() -> None:
    fields = m2_document_fields(_fixture())
    reversed_fields = dict(reversed(list(fields.items())))

    first_text = render_m2_document_text(fields)
    second_text = render_m2_document_text(reversed_fields)

    assert first_text == second_text
    assert build_text_layer_pdf(first_text) == build_text_layer_pdf(second_text)


def test_rejects_encrypted_pdf(tmp_path) -> None:
    path = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("synthetic-password", algorithm="RC4-40")
    with path.open("wb") as output:
        writer.write(output)

    with pytest.raises(PdfIngestionError, match="encrypted"):
        extract_pdf_text(path)


def test_rejects_pdf_without_text_layer(tmp_path) -> None:
    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with path.open("wb") as output:
        writer.write(output)

    with pytest.raises(PdfIngestionError, match="text layer"):
        extract_pdf_text(path)


def test_rejects_invalid_structure_without_leaking_path(tmp_path) -> None:
    marker = "SENSITIVE-PATH-MARKER"
    path = tmp_path / f"{marker}.pdf"
    path.write_bytes(b"%PDF-1.4\nnot-a-valid-pdf")

    with pytest.raises(PdfIngestionError) as captured:
        extract_pdf_text(path)

    assert marker not in str(captured.value)


def test_rejects_document_over_byte_limit(tmp_path) -> None:
    path = tmp_path / "oversized.pdf"
    path.write_bytes(build_text_layer_pdf("BENIGN"))

    with pytest.raises(PdfIngestionError, match="byte limit"):
        extract_pdf_text(path, limits=PdfLimits(maximum_bytes=10))


def test_rejects_page_count_over_limit(tmp_path) -> None:
    path = tmp_path / "two-pages.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    with path.open("wb") as output:
        writer.write(output)

    with pytest.raises(PdfIngestionError, match="page count"):
        extract_pdf_text(path, limits=PdfLimits(maximum_pages=1))
