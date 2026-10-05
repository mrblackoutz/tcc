"""Synthetic private document contracts, without Odoo, I/O or financial effects."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, asdict, fields
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest

from tcc_gateway.pdf_ingestion import PdfLimits


ROOT = Path(__file__).resolve().parents[2]
ADDON = ROOT / "odoo/addons/ap_security_executor"
PACKAGE = "_tcc_document_contracts_offline"
_package = ModuleType(PACKAGE)
_package.__path__ = [str(ADDON)]
sys.modules[PACKAGE] = _package
_spec = importlib.util.spec_from_file_location(PACKAGE + ".document_contracts", ADDON / "document_contracts.py")
assert _spec is not None and _spec.loader is not None
document = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = document
_spec.loader.exec_module(document)

RAW = b"%PDF-1.4\nSYNTHETIC DEVELOPMENT DOCUMENT - SEM VALOR FISCAL\n%%EOF\n"
RAW_HASH = hashlib.sha256(RAW).hexdigest()


def _source(raw=RAW, mimetype="application/pdf"):
    return document.SourceDocument(raw=raw, mimetype=mimetype)


def _validate(value, expected=RAW_HASH):
    return document.validate_source_document(value, document_sha256=expected)


def _invalid(value, code, expected=RAW_HASH):
    with pytest.raises(document.DocumentContractError) as caught:
        _validate(value, expected)
    assert str(caught.value) == "Invalid source document contract."
    assert caught.value.code == code
    assert "SEM VALOR FISCAL" not in str(caught.value)
    assert RAW_HASH not in str(caught.value)


def test_envelope_is_closed_frozen_but_validation_occurs_in_the_boundary():
    value = _source()
    assert {field.name for field in fields(value)} == {"raw", "mimetype"}
    assert not hasattr(value, "__dict__")
    assert "SYNTHETIC DEVELOPMENT" not in repr(value)
    assert "raw=" not in repr(value)
    with pytest.raises(FrozenInstanceError):
        value.raw = b"CHANGED"
    with pytest.raises(TypeError):
        document.SourceDocument(raw=RAW, mimetype="application/pdf", filename="external.pdf")
    # Invalid envelopes must reach the transactional wrapper so it can safely
    # register a bounded denial. The constructor is not a validation bypass.
    assert document.SourceDocument(raw=None, mimetype=None).raw is None


def test_verified_metadata_is_exact_closed_and_does_not_contain_bytes():
    verified = _validate(_source())
    assert asdict(verified) == {"document_sha256": RAW_HASH, "byte_count": len(RAW), "mimetype": "application/pdf"}
    assert not hasattr(verified, "__dict__")
    with pytest.raises(FrozenInstanceError):
        verified.byte_count = 1
    with pytest.raises(TypeError):
        document.VerifiedSourceDocument(**asdict(verified), raw=RAW)


def test_size_limit_is_identical_to_common_c0_c1_ingestion():
    assert document.MAXIMUM_DOCUMENT_BYTES == PdfLimits().maximum_bytes == 1_048_576


@pytest.mark.parametrize("raw", [None, True, 1, 1.0, "%PDF-1.4", bytearray(RAW), memoryview(RAW), [], {}, object()])
def test_raw_must_be_exact_immutable_bytes(raw):
    _invalid(_source(raw), "DOCUMENT_INVALID")


class BytesSubclass(bytes):
    pass


class StringSubclass(str):
    pass


def test_bytes_subclasses_are_not_accepted():
    _invalid(_source(BytesSubclass(RAW)), "DOCUMENT_INVALID")


@pytest.mark.parametrize("mime", [None, True, 1, b"application/pdf", "", "text/plain", "APPLICATION/PDF",
    "application/pdf; charset=utf-8", "application/pdf ", " application/pdf", "application/pdf\n", StringSubclass("application/pdf")])
def test_mime_is_exact_and_never_inferred_from_a_name_or_extension(mime):
    _invalid(_source(mimetype=mime), "DOCUMENT_MIME_INVALID")


@pytest.mark.parametrize("raw", [b"\n%PDF-1.4", b"%pdf-1.4", b"%PDF", b"NOT-PDF", b"\xef\xbb\xbf%PDF-1.4", b"\x00%PDF-1.4"])
def test_magic_is_revalidated_without_claiming_full_pdf_parsing(raw):
    _invalid(_source(raw), "DOCUMENT_INVALID")


def test_empty_document_has_finite_diagnostic():
    _invalid(_source(b""), "DOCUMENT_EMPTY")


def test_size_boundary_is_exact_and_large_payload_has_no_error_excerpt():
    raw = b"%PDF-" + b"X" * (document.MAXIMUM_DOCUMENT_BYTES - 5)
    verified = _validate(_source(raw), hashlib.sha256(raw).hexdigest())
    assert verified.byte_count == document.MAXIMUM_DOCUMENT_BYTES
    _invalid(_source(raw + b"X"), "DOCUMENT_TOO_LARGE")


def test_header_only_is_explicitly_not_a_text_structure_or_encryption_check():
    # Strict parsing is deliberately implemented once in common ingestion,
    # not as another experimental C1 treatment.
    raw = b"%PDF-"
    assert _validate(_source(raw), hashlib.sha256(raw).hexdigest()).byte_count == 5


@pytest.mark.parametrize("expected", [None, True, 1, b"a" * 64, "", "a" * 63, "a" * 65, "A" * 64,
    "g" * 64, "sha256:" + "a" * 64, RAW_HASH + "\n", StringSubclass(RAW_HASH)])
def test_expected_hash_has_closed_raw_lowercase_format(expected):
    _invalid(_source(), "DOCUMENT_INVALID", expected)


def test_same_size_modified_bytes_do_not_match_the_original_identity():
    _invalid(_source(RAW.replace(b"DEVELOPMENT", b"ALTERED-DAT")), "DOCUMENT_HASH_MISMATCH")


@pytest.mark.parametrize("value", [None, {}, {"raw": RAW, "mimetype": "application/pdf"}, RAW, object()])
def test_dicts_or_protocol_like_objects_do_not_authorize_document_bytes(value):
    _invalid(value, "DOCUMENT_INVALID")


def test_source_subclasses_are_not_accepted_as_an_exact_contract():
    class Subclass(document.SourceDocument):
        pass
    _invalid(Subclass(RAW, "application/pdf"), "DOCUMENT_INVALID")


@pytest.mark.parametrize("field,value,code", [
    ("raw", None, "DOCUMENT_INVALID"), ("raw", b"", "DOCUMENT_EMPTY"),
    ("raw", b"%PDF-" + b"X" * document.MAXIMUM_DOCUMENT_BYTES, "DOCUMENT_TOO_LARGE"),
    ("raw", b"HEADER-MUTATED", "DOCUMENT_INVALID"), ("mimetype", "text/plain", "DOCUMENT_MIME_INVALID"),
], ids=["raw-none", "raw-empty", "raw-oversize", "raw-magic", "mime-changed"])
def test_defensively_revalidates_frozen_slots_after_non_rpc_corruption(field, value, code):
    source = _source()
    object.__setattr__(source, field, value)
    _invalid(source, code)


@pytest.mark.parametrize("field", ["raw", "mimetype"])
def test_missing_slots_have_only_a_safe_finite_diagnostic(field):
    source = _source()
    object.__delattr__(source, field)
    _invalid(source, "DOCUMENT_INVALID")


@pytest.mark.parametrize("field,value", [
    ("document_sha256", None), ("document_sha256", "a" * 63), ("document_sha256", "A" * 64),
    ("document_sha256", StringSubclass(RAW_HASH)), ("byte_count", None), ("byte_count", True),
    ("byte_count", 0), ("byte_count", -1), ("byte_count", 1.0),
    ("byte_count", document.MAXIMUM_DOCUMENT_BYTES + 1), ("mimetype", "text/plain"),
    ("mimetype", StringSubclass("application/pdf")),
])
def test_verification_results_reject_coercions_or_impossible_values(field, value):
    metadata = {"document_sha256": RAW_HASH, "byte_count": len(RAW), "mimetype": "application/pdf"}
    metadata[field] = value
    with pytest.raises(document.DocumentContractError) as caught:
        document.VerifiedSourceDocument(**metadata)
    assert str(caught.value) == "Invalid source document contract."
    assert caught.value.code == "DOCUMENT_INVALID"


@pytest.mark.parametrize("code", [None, True, "BAD-INPUT-MARKER", StringSubclass("DOCUMENT_EMPTY")])
def test_invalid_diagnostic_codes_cannot_echo_input(code):
    error = document.DocumentContractError(code)
    assert error.code == "DOCUMENT_INVALID"
    assert str(error) == "Invalid source document contract."


def test_attachment_primitive_has_no_importer_commit_or_public_capability():
    source = (ADDON / "attachment_kernel.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not {"commit", "_message_set_main_attachment_id", "_extend_with_attachments", "force_storage"} & attributes
    assert "_file_write" not in attributes
    assert "urlopen" not in attributes
    assert {node.name for node in tree.body if isinstance(node, ast.ClassDef)} == {"AttachmentError"}
    assert '"storage": "db"' in source
    assert '"public": False' in source
    assert '"access_token": False' in source
    assert '"res_field": False' in source
    assert '"url": False' in source
    assert "FOR UPDATE" in source
    assert "_after_attachment_create(attachment)" in source
    assert source.index("if (attachment.store_fname") < source.index("raw = attachment.raw")
