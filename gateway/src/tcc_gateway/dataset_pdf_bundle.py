"""DEC-062: verified development pairs, never a scientific dataset release.

Generation creates a fresh candidate with real document/text hashes. Optional
local persistence reuses the private path barriers of ``run_record_store``;
this deliberate coupling is covered by regression tests. Source notes remain
local so reopening can reproduce each PDF, not merely trust relabelled hashes.
No hash authenticates authorship, human review, privacy or external retention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
from typing import Any

from . import run_record_store as _fs
from .dataset_pair import MAX_PAIR_BYTES, DatasetPair, parse_dataset_pair
from .dataset_pdf import GENERATOR_VERSION, render_development_pdf
from .pdf_ingestion import PdfLimits, extract_pdf_bytes
from .state import canonical_json_bytes


MANIFEST_VERSION = "ap-ipi-development-generation/v1"
PAIR_NAME = "pair.json"
MANIFEST_NAME = "generation.json"
MAX_MANIFEST_BYTES = 4096
MAX_TEXT_BYTES = 80_000
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MEMBERS = ("benign", "adversarial")
_ERROR = "invalid development PDF pair operation"
_FAILURES = (OSError, ValueError, TypeError, AttributeError, KeyError,
             OverflowError, RecursionError)
_MANIFEST_FIELDS = {"schema_version", "generator_version", "pair_sha256",
                    "pair_bytes", "documents"}
_DOCUMENT_FIELDS = {"scenario_id", "document_sha256", "document_bytes",
                    "extracted_text_sha256", "extracted_text_bytes",
                    "note_sha256", "note_bytes", "page_count"}


class DatasetPdfBundleError(ValueError):
    """Finite failure without source notes, received paths or raw documents."""


@dataclass(frozen=True, slots=True)
class GeneratedDevelopmentDocument:
    """Local source and presentation; only public functions certify binding."""

    note: str = field(repr=False)
    pdf_bytes: bytes = field(repr=False)
    extracted_text: str = field(repr=False)
    page_count: int = field(repr=False)


@dataclass(frozen=True, slots=True)
class GeneratedDevelopmentPair:
    """Two documents in evaluator member order, not labelled model inputs."""

    pair: DatasetPair = field(repr=False)
    documents: tuple[GeneratedDevelopmentDocument, GeneratedDevelopmentDocument] = field(repr=False)


@dataclass(frozen=True, slots=True)
class DevelopmentPairWriteReceipt:
    pair_sha256: str
    manifest_sha256: str


def _fail() -> None:
    raise DatasetPdfBundleError(_ERROR)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        _fail()
    return value


def _pair(value: DatasetPair) -> DatasetPair:
    if type(value) is not DatasetPair:
        _fail()
    checked = parse_dataset_pair(value.to_mapping())
    if checked.to_mapping()["split"] != "development":
        _fail()
    return checked


def _render(pair: DatasetPair, note: str) -> GeneratedDevelopmentDocument:
    rendered = render_development_pdf(pair, note)
    extracted = extract_pdf_bytes(rendered.pdf_bytes)
    if (type(rendered.pdf_bytes) is not bytes
            or type(rendered.expected_text) is not str
            or type(rendered.page_count) is not int
            or rendered.expected_text != extracted.text
            or rendered.page_count != extracted.page_count):
        _fail()
    return GeneratedDevelopmentDocument(note, rendered.pdf_bytes,
                                         extracted.text, extracted.page_count)


def _checked(value: GeneratedDevelopmentPair) -> GeneratedDevelopmentPair:
    """Revalidate even frozen instances constructed or modified by a caller."""
    if type(value) is not GeneratedDevelopmentPair:
        _fail()
    pair = _pair(value.pair)
    if type(value.documents) is not tuple or len(value.documents) != 2:
        _fail()
    mapping = pair.to_mapping()
    checked_documents = []
    for member, document in zip(_MEMBERS, value.documents, strict=True):
        if (type(document) is not GeneratedDevelopmentDocument
                or type(document.note) is not str
                or type(document.pdf_bytes) is not bytes
                or type(document.extracted_text) is not str
                or type(document.page_count) is not int):
            _fail()
        checked = _render(pair, document.note)
        if checked != document:
            _fail()
        expected = mapping["members"][member]
        if (_sha256(document.pdf_bytes) != expected["document_sha256"]
                or _sha256(document.extracted_text.encode("utf-8"))
                != expected["extracted_text_sha256"]):
            _fail()
        checked_documents.append(checked)
    return GeneratedDevelopmentPair(pair, tuple(checked_documents))


def generate_development_pair(
    pair: DatasetPair, *, benign_note: str, adversarial_note: str,
) -> GeneratedDevelopmentPair:
    """Generate a new candidate, leaving incoming hashes and source untouched.

    Notes are literal caller input. Labels, attack family and expected action
    never select note text, a model output, approval or a policy decision.
    """
    try:
        checked_pair = _pair(pair)
        documents = (_render(checked_pair, benign_note),
                     _render(checked_pair, adversarial_note))
        mapping = checked_pair.to_mapping()
        for member, document in zip(_MEMBERS, documents, strict=True):
            mapping["members"][member]["document_sha256"] = _sha256(document.pdf_bytes)
            mapping["members"][member]["extracted_text_sha256"] = _sha256(
                document.extracted_text.encode("utf-8"))
        # This also refuses identical documents/texts, including equivalent
        # visible notes after deterministic line wrapping or normalisation.
        result = GeneratedDevelopmentPair(parse_dataset_pair(mapping), documents)
        return _checked(result)
    except _FAILURES:
        raise DatasetPdfBundleError(_ERROR) from None


def _manifest(value: GeneratedDevelopmentPair) -> tuple[bytes, dict[str, bytes]]:
    pair_raw = canonical_json_bytes(value.pair.to_mapping())
    documents = []
    blobs = {PAIR_NAME: pair_raw}
    for member, document in zip(_MEMBERS, value.documents, strict=True):
        expected = value.pair.to_mapping()["members"][member]
        text = document.extracted_text.encode("utf-8")
        note = document.note.encode("utf-8")
        note_sha256 = _sha256(note)
        for name, raw in (
                (expected["document_sha256"] + ".pdf", document.pdf_bytes),
                (expected["extracted_text_sha256"] + ".txt", text),
                (note_sha256 + ".txt", note)):
            if not raw:
                continue
            if name in blobs and blobs[name] != raw:
                _fail()
            blobs[name] = raw
        documents.append({
            "scenario_id": expected["scenario_id"],
            "document_sha256": expected["document_sha256"],
            "document_bytes": len(document.pdf_bytes),
            "extracted_text_sha256": expected["extracted_text_sha256"],
            "extracted_text_bytes": len(text),
            "note_sha256": note_sha256, "note_bytes": len(note),
            "page_count": document.page_count,
        })
    return canonical_json_bytes({
        "schema_version": MANIFEST_VERSION, "generator_version": GENERATOR_VERSION,
        "pair_sha256": _sha256(pair_raw), "pair_bytes": len(pair_raw),
        "documents": documents,
    }), blobs


def _entry_names(directory: Path) -> set[str]:
    result: set[str] = set()
    for entry in directory.iterdir():
        result.add(entry.name)
        if len(result) > 8:
            _fail()
    return result


def _files(directory: Path, expected: set[str]) -> None:
    if _entry_names(directory) != expected:
        _fail()
    for name in expected:
        _fs._regular_file((directory / name).lstat())


def _count(value: Any, limit: int, *, empty: bool = False) -> int:
    if type(value) is not int or not (0 if empty else 1) <= value <= limit:
        _fail()
    return value


def _read_blob(directory: Path, digest: str, extension: str, count: int, limit: int) -> bytes:
    digest = _digest(digest)
    if count == 0:
        if extension != ".txt" or digest != _sha256(b""):
            _fail()
        return b""
    raw = _fs._read_bounded(directory / (digest + extension), limit)
    if len(raw) != count or _sha256(raw) != digest:
        _fail()
    return raw


def write_development_pair(root: Path, generated: GeneratedDevelopmentPair) -> DevelopmentPairWriteReceipt:
    """Write once, retaining any interrupted directory and never repairing it.

    Each exclusive blob is flushed/fsynced before the final generation
    manifest. This is local consistency, not guaranteed power-loss durability,
    encrypted custody or an externally immutable backup.
    """
    try:
        checked = _checked(generated)
        root, root_identity = _fs._root(root)
        manifest, blobs = _manifest(checked)
        pair_sha256 = _sha256(blobs[PAIR_NAME])
        directory = root / pair_sha256
        _fs._verify_directory(root, root_identity)
        directory.mkdir(mode=0o700, exist_ok=False)
        directory_identity = _fs._identity(_fs._directory_chain(directory))
        _fs._verify_directory(root, root_identity)
        for name in sorted(blobs):
            _fs._write_exclusive(directory / name, blobs[name])
            _fs._verify_directory(directory, directory_identity)
            _fs._verify_directory(root, root_identity)
        _fs._write_exclusive(directory / MANIFEST_NAME, manifest)
        _fs._verify_directory(directory, directory_identity)
        _fs._verify_directory(root, root_identity)
        _files(directory, set(blobs) | {MANIFEST_NAME})
        if read_development_pair(root, pair_sha256) != checked:
            _fail()
        return DevelopmentPairWriteReceipt(pair_sha256, _sha256(manifest))
    except _FAILURES:
        raise DatasetPdfBundleError(_ERROR) from None


def read_development_pair(root: Path, pair_sha256: str) -> GeneratedDevelopmentPair:
    """Reopen only a complete bundle with exact source-render-extraction binding."""
    try:
        root, root_identity = _fs._root(root)
        pair_sha256 = _digest(pair_sha256)
        directory = root / pair_sha256
        directory_identity = _fs._identity(_fs._directory_chain(directory))
        manifest_raw = _fs._read_bounded(directory / MANIFEST_NAME, MAX_MANIFEST_BYTES)
        manifest = _fs._json(manifest_raw)
        if (set(manifest) != _MANIFEST_FIELDS
                or manifest["schema_version"] != MANIFEST_VERSION
                or manifest["generator_version"] != GENERATOR_VERSION
                or manifest["pair_sha256"] != pair_sha256
                or type(manifest["documents"]) is not list
                or len(manifest["documents"]) != 2):
            _fail()
        pair_bytes = _count(manifest["pair_bytes"], MAX_PAIR_BYTES)
        pair_raw = _fs._read_bounded(directory / PAIR_NAME, MAX_PAIR_BYTES)
        if len(pair_raw) != pair_bytes or _sha256(pair_raw) != pair_sha256:
            _fail()
        pair = _pair(parse_dataset_pair(_fs._json(pair_raw)))
        documents = []
        for member, entry in zip(_MEMBERS, manifest["documents"], strict=True):
            if type(entry) is not dict or set(entry) != _DOCUMENT_FIELDS:
                _fail()
            expected = pair.to_mapping()["members"][member]
            if any(entry[key] != expected[key] for key in (
                    "scenario_id", "document_sha256", "extracted_text_sha256")):
                _fail()
            pdf_count = _count(entry["document_bytes"], PdfLimits().maximum_bytes)
            text_count = _count(entry["extracted_text_bytes"], MAX_TEXT_BYTES)
            note_count = _count(entry["note_bytes"], MAX_TEXT_BYTES, empty=True)
            page_count = _count(entry["page_count"], PdfLimits().maximum_pages)
            pdf = _read_blob(directory, entry["document_sha256"], ".pdf", pdf_count,
                             PdfLimits().maximum_bytes)
            text = _read_blob(directory, entry["extracted_text_sha256"], ".txt",
                              text_count, MAX_TEXT_BYTES).decode("utf-8")
            note = _read_blob(directory, entry["note_sha256"], ".txt",
                              note_count, MAX_TEXT_BYTES).decode("utf-8")
            documents.append(GeneratedDevelopmentDocument(note, pdf, text, page_count))
        checked = _checked(GeneratedDevelopmentPair(pair, tuple(documents)))
        rebuilt, blobs = _manifest(checked)
        if rebuilt != manifest_raw:
            _fail()
        _files(directory, set(blobs) | {MANIFEST_NAME})
        _fs._verify_directory(directory, directory_identity)
        _fs._verify_directory(root, root_identity)
        return checked
    except _FAILURES:
        raise DatasetPdfBundleError(_ERROR) from None
