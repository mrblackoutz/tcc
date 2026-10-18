"""Ingestao limitada e saneada de PDFs com camada de texto."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class PdfIngestionError(ValueError):
    """Indica PDF ausente, inseguro, fora dos limites ou sem texto."""


@dataclass(frozen=True, slots=True)
class PdfLimits:
    maximum_bytes: int = 1_048_576
    maximum_pages: int = 4
    maximum_text_characters: int = 20_000

    def __post_init__(self) -> None:
        if min(
            self.maximum_bytes,
            self.maximum_pages,
            self.maximum_text_characters,
        ) <= 0:
            raise ValueError("PDF limits must be positive")


@dataclass(frozen=True, slots=True)
class ExtractedPdf:
    text: str
    document_sha256: str
    text_sha256: str
    page_count: int
    byte_count: int


def _normalise_text(raw_text: str) -> str:
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in text:
        raise PdfIngestionError("PDF text contains forbidden control characters")
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def extract_pdf_text(
    path: Path,
    *,
    limits: PdfLimits | None = None,
) -> ExtractedPdf:
    """Extrai texto sem OCR e sem incluir caminho ou conteudo nos erros."""

    active_limits = limits or PdfLimits()
    try:
        raw_bytes = path.read_bytes()
    except OSError:
        raise PdfIngestionError("unable to read the PDF document") from None

    return extract_pdf_bytes(raw_bytes, limits=active_limits)


def extract_pdf_bytes(
    raw_bytes: bytes,
    *,
    limits: PdfLimits | None = None,
) -> ExtractedPdf:
    """Extrai com a mesma normalização do caminho, sem I/O ou novos filtros.

    Permite conferir PDFs novos antes de persistir um par de desenvolvimento.
    O conteúdo continua não confiável; esta função não certifica sua autoria.
    """

    active_limits = limits or PdfLimits()
    if type(raw_bytes) is not bytes:
        raise PdfIngestionError("PDF input must be bytes")
    if not raw_bytes or len(raw_bytes) > active_limits.maximum_bytes:
        raise PdfIngestionError("PDF document is empty or exceeds the byte limit")
    if not raw_bytes.startswith(b"%PDF-"):
        raise PdfIngestionError("document is not a PDF")

    try:
        reader = PdfReader(BytesIO(raw_bytes), strict=True)
        if reader.is_encrypted:
            raise PdfIngestionError("encrypted PDFs are not accepted")
        page_count = len(reader.pages)
        if not 1 <= page_count <= active_limits.maximum_pages:
            raise PdfIngestionError("PDF page count is outside the accepted limit")
        extracted_pages = [page.extract_text() or "" for page in reader.pages]
    except PdfIngestionError:
        raise
    except (PdfReadError, OSError, TypeError, ValueError, IndexError):
        raise PdfIngestionError("PDF structure or text layer is invalid") from None

    text = _normalise_text("\n".join(extracted_pages))
    if not text.strip():
        raise PdfIngestionError("PDF does not contain an extractable text layer")
    if len(text) > active_limits.maximum_text_characters:
        raise PdfIngestionError("PDF text exceeds the character limit")

    return ExtractedPdf(
        text=text,
        document_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        page_count=page_count,
        byte_count=len(raw_bytes),
    )
