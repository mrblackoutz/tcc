"""DEC-068 local preparation input, stdlib-only; never POST authority."""

import base64
from dataclasses import dataclass, field
from datetime import date
import hashlib
import json

from .pilot_seed_contract import PilotSeedError, _closed, _constant, _pairs, _require, _text
from .state import canonical_json_bytes


ORIGIN_VERSION = "ap-ipi-pilot-a3a-origin-input/v1"
MAX_ORIGIN_BYTES = 2 * 1024 * 1024
MAX_PDF_BYTES = 128 * 1024
_TOP = {"schema_version", "status", "split", "synthetic_data", "fiscal_value",
        "seed_sha256", "cohort_sha256", "codebook_sha256", "fixtures"}
_ROW = {"fixture_ref", "pair_sha256", "document_ref", "invoice_date_min", "invoice_date_max",
        "document", "other_document"}
_DOC = {"scenario_id", "document_sha256", "extracted_text_sha256", "pdf_base64"}


def document_bytes(value):
    """Decode exact bytes; no PDF text is evaluated as an instruction."""
    _closed(value, _DOC)
    _text(value["scenario_id"], r"[A-Z0-9][A-Z0-9._-]{0,63}")
    for name in ("document_sha256", "extracted_text_sha256"):
        _text(value[name], r"[0-9a-f]{64}")
    encoded = value["pdf_base64"]
    _require(type(encoded) is str and 0 < len(encoded) <= ((MAX_PDF_BYTES + 2) // 3) * 4)
    raw = base64.b64decode(encoded, validate=True)
    _require(0 < len(raw) <= MAX_PDF_BYTES and raw.startswith(b"%PDF-")
             and base64.b64encode(raw).decode("ascii") == encoded
             and hashlib.sha256(raw).hexdigest() == value["document_sha256"])
    return raw


def _validate(value):
    _closed(value, _TOP)
    _require(value["schema_version"] == ORIGIN_VERSION and value["status"] == "CANDIDATE"
             and value["split"] == "pilot-v0" and value["synthetic_data"] is True
             and value["fiscal_value"] is False)
    for name in ("seed_sha256", "cohort_sha256", "codebook_sha256"):
        _text(value[name], r"[0-9a-f]{64}")
    rows = value["fixtures"]
    _require(type(rows) is list and len(rows) == 4)
    documents = []
    for row in rows:
        _closed(row, _ROW)
        for name in ("fixture_ref", "document_ref"):
            _text(row[name], r"[A-Z0-9][A-Z0-9._ /-]{0,95}")
        _text(row["pair_sha256"], r"[0-9a-f]{64}")
        for name in ("invoice_date_min", "invoice_date_max"):
            _text(row[name], r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
            _require(date.fromisoformat(row[name]).isoformat() == row[name])
        _require(row["invoice_date_min"] <= row["invoice_date_max"])
        for name in ("document", "other_document"):
            document_bytes(row[name])
            documents.append(row[name])
    for name in ("fixture_ref", "pair_sha256", "document_ref"):
        _require(len({row[name] for row in rows}) == 4)
    _require([row["fixture_ref"] for row in rows] == sorted(row["fixture_ref"] for row in rows))
    for name in ("scenario_id", "document_sha256", "extracted_text_sha256"):
        _require(len({item[name] for item in documents}) == 8)
    encoded = canonical_json_bytes(value)
    _require(0 < len(encoded) <= MAX_ORIGIN_BYTES)
    return encoded


@dataclass(frozen=True, slots=True)
class PilotA3aOriginInput:
    _encoded: bytes = field(repr=False)

    def __post_init__(self):
        self.to_mapping()

    def to_mapping(self):
        try:
            _require(type(self._encoded) is bytes and 0 < len(self._encoded) <= MAX_ORIGIN_BYTES)
            value = json.loads(self._encoded.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
            _require(_validate(value) == self._encoded)
            return value
        except Exception:
            raise PilotSeedError("invalid candidate A3a origin preparation") from None

    @property
    def sha256(self):
        self.to_mapping()
        return hashlib.sha256(self._encoded).hexdigest()


def parse_origin_input(value):
    try:
        return PilotA3aOriginInput(_validate(value))
    except Exception:
        raise PilotSeedError("invalid candidate A3a origin preparation") from None
