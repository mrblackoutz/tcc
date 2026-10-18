from __future__ import annotations

import hashlib
from io import BytesIO

import pytest
from pypdf import PdfWriter

from tcc_gateway.pdf_ingestion import (
    PdfIngestionError, PdfLimits, extract_pdf_bytes, extract_pdf_text,
)
from tcc_gateway.synthetic_pdf import build_text_layer_pdf


def test_byte_and_file_extraction_are_identical_without_changing_m2(tmp_path):
    raw = build_text_layer_pdf("DOCUMENTO SINTETICO\n\nTOTAL: 125.50\nSEM VALOR FISCAL")
    path = tmp_path / "opaque.pdf"
    path.write_bytes(raw)
    extracted = extract_pdf_bytes(raw)
    assert extracted == extract_pdf_text(path)
    assert extracted.document_sha256 == hashlib.sha256(raw).hexdigest()
    assert extracted.text_sha256 == hashlib.sha256(extracted.text.encode("utf-8")).hexdigest()
    assert extracted.text == "DOCUMENTO SINTETICO\nTOTAL: 125.50\nSEM VALOR FISCAL"


@pytest.mark.parametrize("raw", [None, True, 1, "private-placeholder", bytearray(b"pdf"), memoryview(b"pdf")])
def test_byte_entrypoint_never_coerces_or_echoes_input(raw):
    with pytest.raises(PdfIngestionError) as caught:
        extract_pdf_bytes(raw)
    assert str(caught.value) == "PDF input must be bytes"


@pytest.mark.parametrize("raw", [b"", b"not-a-pdf", b"%PDF-1.4\ninvalid"])
def test_byte_entrypoint_rejects_invalid_documents(raw):
    with pytest.raises(PdfIngestionError):
        extract_pdf_bytes(raw)


def test_byte_entrypoint_uses_the_existing_size_and_text_limits():
    raw = build_text_layer_pdf("SYNTHETIC TEXT")
    with pytest.raises(PdfIngestionError, match="byte limit"):
        extract_pdf_bytes(raw, limits=PdfLimits(maximum_bytes=10))
    with pytest.raises(PdfIngestionError, match="character limit"):
        extract_pdf_bytes(raw, limits=PdfLimits(maximum_text_characters=2))


@pytest.mark.parametrize("encrypt", [False, True])
def test_blank_or_encrypted_bytes_remain_rejected(encrypt):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    if encrypt:
        writer.encrypt("synthetic-password", algorithm="RC4-40")
    stream = BytesIO()
    writer.write(stream)
    with pytest.raises(PdfIngestionError, match="encrypted" if encrypt else "text layer"):
        extract_pdf_bytes(stream.getvalue())


def test_byte_entrypoint_retains_page_limit():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    stream = BytesIO()
    writer.write(stream)
    with pytest.raises(PdfIngestionError, match="page count"):
        extract_pdf_bytes(stream.getvalue(), limits=PdfLimits(maximum_pages=1))
