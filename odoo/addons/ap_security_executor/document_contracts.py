# SPDX-License-Identifier: LGPL-3.0-or-later
"""Bounded untrusted PDF bytes; neither a parser nor an authorization object.

The common ingestion stage remains responsible for strict PDF structure and
text-layer checks. These contracts repeat the shared MIME/byte limit and bind
the exact bytes to the registered document hash without exposing their content.
"""

from dataclasses import dataclass, field
import hashlib
import re


MAXIMUM_DOCUMENT_BYTES = 1_048_576
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ERROR_CODES = frozenset({
    "DOCUMENT_INVALID", "DOCUMENT_EMPTY", "DOCUMENT_TOO_LARGE",
    "DOCUMENT_MIME_INVALID", "DOCUMENT_HASH_MISMATCH",
})


class DocumentContractError(ValueError):
    """Finite diagnostic; never include a filename, hash or document bytes."""

    def __init__(self, code="DOCUMENT_INVALID"):
        self.code = code if type(code) is str and code in _ERROR_CODES else "DOCUMENT_INVALID"
        super().__init__("Invalid source document contract.")


def _values(raw, mimetype):
    if type(raw) is not bytes:
        raise DocumentContractError("DOCUMENT_INVALID")
    if not raw:
        raise DocumentContractError("DOCUMENT_EMPTY")
    if len(raw) > MAXIMUM_DOCUMENT_BYTES:
        raise DocumentContractError("DOCUMENT_TOO_LARGE")
    if type(mimetype) is not str or mimetype != "application/pdf":
        raise DocumentContractError("DOCUMENT_MIME_INVALID")
    if not raw.startswith(b"%PDF-"):
        raise DocumentContractError("DOCUMENT_INVALID")


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """Untrusted immutable bytes supplied by private administrative code."""

    raw: bytes = field(repr=False)
    mimetype: str

@dataclass(frozen=True, slots=True)
class VerifiedSourceDocument:
    """Closed verification result, not authenticated document provenance."""

    document_sha256: str
    byte_count: int
    mimetype: str

    def __post_init__(self):
        if (type(self.document_sha256) is not str or not _HASH.fullmatch(self.document_sha256)
                or type(self.byte_count) is not int or not 1 <= self.byte_count <= MAXIMUM_DOCUMENT_BYTES
                or type(self.mimetype) is not str or self.mimetype != "application/pdf"):
            raise DocumentContractError()


def validate_source_document(document, *, document_sha256):
    """Revalidate exact types/bytes and their expected raw lowercase SHA-256."""
    if type(document) is not SourceDocument:
        raise DocumentContractError()
    try:
        _values(document.raw, document.mimetype)
        if type(document_sha256) is not str or not _HASH.fullmatch(document_sha256):
            raise DocumentContractError()
        if hashlib.sha256(document.raw).hexdigest() != document_sha256:
            raise DocumentContractError("DOCUMENT_HASH_MISMATCH")
        return VerifiedSourceDocument(document_sha256, len(document.raw), document.mimetype)
    except AttributeError:
        raise DocumentContractError() from None
