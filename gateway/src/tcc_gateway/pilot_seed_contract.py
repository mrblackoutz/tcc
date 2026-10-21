"""DEC-067 administrative business seed, stdlib-only for the pinned Odoo.

No model action, label, attack text or approval belongs to this contract.
Integrity/provenance fields do not authenticate authorship or human review.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Context, Decimal, localcontext
import hashlib
import json
import re

from .state import canonical_json_bytes


SEED_VERSION = "ap-ipi-pilot-business-seed/v1"
MAX_SEED_BYTES = 128 * 1024
_ERROR = "invalid candidate pilot business seed"
_REF = r"[A-Z0-9][A-Z0-9._ /-]{0,95}"
_HASH = r"[0-9a-f]{64}"
_TOP = {"schema_version", "split", "status", "synthetic_data", "fiscal_value",
        "cohort_sha256", "codebook_sha256", "dataset_version", "fixtures"}
_FIXTURE = {"fixture_ref", "pair_sha256", "company_ref", "vendor_ref", "purchase_order_ref",
            "invoice_date", "currency", "amount", "approved_bank_ref", "quantity_scale", "lines"}


class PilotSeedError(ValueError):
    """Finite failure; never expose records, paths, source data or credentials."""


def _require(value):
    if not value:
        raise PilotSeedError(_ERROR)


def _text(value, pattern):
    _require(type(value) is str and re.fullmatch(pattern, value) is not None
             and value.strip() == value)


def _closed(value, keys):
    _require(type(value) is dict and set(value) == keys)


def _validate(value):
    _closed(value, _TOP)
    _require(value["schema_version"] == SEED_VERSION and value["split"] == "pilot-v0"
             and value["status"] == "CANDIDATE" and value["synthetic_data"] is True
             and value["fiscal_value"] is False)
    for name in ("cohort_sha256", "codebook_sha256"):
        _text(value[name], _HASH)
    _text(value["dataset_version"], r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}")
    rows = value["fixtures"]
    _require(type(rows) is list and len(rows) == 12)
    banks = {}
    for row in rows:
        _closed(row, _FIXTURE)
        for name in ("fixture_ref", "company_ref", "vendor_ref", "purchase_order_ref", "approved_bank_ref"):
            _text(row[name], _REF)
        _text(row["pair_sha256"], _HASH)
        _text(row["invoice_date"], r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
        _require(date.fromisoformat(row["invoice_date"]).isoformat() == row["invoice_date"])
        _require(row["currency"] == "BRL" and type(row["quantity_scale"]) is int
                 and row["quantity_scale"] in (2, 3, 4))
        _text(row["amount"], r"(?:0|[1-9][0-9]{0,11})\.[0-9]{2}")
        _require(type(row["lines"]) is list and 1 <= len(row["lines"]) <= 50)
        with localcontext(Context(prec=64)):
            total = Decimal(0)
            for line in row["lines"]:
                _closed(line, {"item_code", "quantity", "unit_price", "line_total"})
                _text(line["item_code"], _REF)
                _text(line["quantity"], r"[1-9][0-9]{0,5}\.[0-9]{" + str(row["quantity_scale"]) + "}")
                for name in ("unit_price", "line_total"):
                    _text(line[name], r"(?:0|[1-9][0-9]{0,11})\.[0-9]{2}")
                q, p, subtotal = (Decimal(line[name]) for name in ("quantity", "unit_price", "line_total"))
                _require(q > 0 and p > 0 and q * p == subtotal)
                total += subtotal
            _require(total > 0 and total == Decimal(row["amount"]))
        codes = [line["item_code"] for line in row["lines"]]
        _require(codes == sorted(set(codes)))
        bank, owner = row["approved_bank_ref"], row["vendor_ref"]
        _require(bank not in banks or banks[bank] == owner)
        banks[bank] = owner
    for name in ("fixture_ref", "pair_sha256", "purchase_order_ref"):
        _require(len({row[name] for row in rows}) == 12)
    _require(len({row["company_ref"] for row in rows}) == 1)
    _require([row["fixture_ref"] for row in rows] == sorted(row["fixture_ref"] for row in rows))
    encoded = canonical_json_bytes(value)
    _require(0 < len(encoded) <= MAX_SEED_BYTES)
    return encoded


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _constant(_value):
    raise PilotSeedError(_ERROR)


def _decode(raw):
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_SEED_BYTES)
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    _require(_validate(value) == raw)
    return value


@dataclass(frozen=True, slots=True)
class PilotBusinessSeed:
    _encoded: bytes = field(repr=False)

    def __post_init__(self):
        self.to_mapping()

    def to_mapping(self):
        try:
            return _decode(self._encoded)
        except Exception:
            raise PilotSeedError(_ERROR) from None

    @property
    def sha256(self):
        self.to_mapping()
        return hashlib.sha256(self._encoded).hexdigest()


def parse_business_seed(value):
    try:
        return PilotBusinessSeed(_validate(value))
    except Exception:
        raise PilotSeedError(_ERROR) from None


# DEC-070: administrative input only, deliberately separate from legitimate
# business facts. No parser reads document notes or changes a C1 allowlist.
ALTERNATIVES_VERSION = "ap-ipi-pilot-alternative-catalog/v1"
MAX_ALTERNATIVES_BYTES = 32 * 1024
_CATALOG_ERROR = "invalid candidate pilot alternative catalog"


def _validate_catalog(value):
    _closed(value, {"schema_version", "split", "status", "synthetic_data", "fiscal_value",
                    "seed_sha256", "cohort_sha256", "codebook_sha256", "vendor_refs",
                    "purchase_order_checks", "banks"})
    _require(value["schema_version"] == ALTERNATIVES_VERSION and value["split"] == "pilot-v0"
             and value["status"] == "CANDIDATE" and value["synthetic_data"] is True
             and value["fiscal_value"] is False)
    for name in ("seed_sha256", "cohort_sha256", "codebook_sha256"):
        _text(value[name], _HASH)
    refs = value["vendor_refs"]
    _require(type(refs) is list and 1 <= len(refs) <= 12)
    for ref in refs:
        _text(ref, _REF)
    _require(refs == sorted(set(refs)))
    checks = value["purchase_order_checks"]
    _require(type(checks) is list and 1 <= len(checks) <= 12)
    for check in checks:
        _closed(check, {"purchase_order_ref", "item_codes"})
        _text(check["purchase_order_ref"], _REF)
        codes = check["item_codes"]
        _require(type(codes) is list and 1 <= len(codes) <= 50)
        for code in codes:
            _text(code, _REF)
        _require(codes == sorted(set(codes)))
    po_refs = [row["purchase_order_ref"] for row in checks]
    _require(po_refs == sorted(set(po_refs)))
    banks = value["banks"]
    _require(type(banks) is list and 1 <= len(banks) <= 32)
    for bank in banks:
        _closed(bank, {"bank_ref", "owner_vendor_ref"})
        for ref in bank.values():
            _text(ref, _REF)
    bank_refs = [row["bank_ref"] for row in banks]
    _require(bank_refs == sorted(set(bank_refs)))
    raw = canonical_json_bytes(value)
    _require(0 < len(raw) <= MAX_ALTERNATIVES_BYTES)
    return raw


@dataclass(frozen=True, slots=True)
class PilotAlternativeCatalog:
    _encoded: bytes = field(repr=False)

    def __post_init__(self):
        self.to_mapping()

    def to_mapping(self):
        try:
            _require(type(self._encoded) is bytes and 0 < len(self._encoded) <= MAX_ALTERNATIVES_BYTES)
            value = json.loads(self._encoded.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
            _require(_validate_catalog(value) == self._encoded)
            return value
        except Exception:
            raise PilotSeedError(_CATALOG_ERROR) from None

    @property
    def sha256(self):
        self.to_mapping()
        return hashlib.sha256(self._encoded).hexdigest()


def parse_alternative_catalog(value):
    try:
        return PilotAlternativeCatalog(_validate_catalog(value))
    except Exception:
        raise PilotSeedError(_CATALOG_ERROR) from None


def parse_alternative_source(raw):
    """Import explicit human-editable JSON once; stored catalogs stay canonical."""
    try:
        _require(type(raw) is bytes and 0 < len(raw) <= MAX_ALTERNATIVES_BYTES)
        return parse_alternative_catalog(json.loads(raw.decode("utf-8"),
            object_pairs_hook=_pairs, parse_constant=_constant))
    except Exception:
        raise PilotSeedError(_CATALOG_ERROR) from None


def validate_alternatives(seed, catalog):
    """Bind explicit administration to known facts, never to model output.

    An absent PO/item relation is intentionally NOT repaired or treated as a
    valid resolution. The native diagnostic must measure it independently.
    """
    try:
        _require(type(seed) is PilotBusinessSeed and type(catalog) is PilotAlternativeCatalog)
        business, value = seed.to_mapping(), catalog.to_mapping()
        _require(value["seed_sha256"] == seed.sha256
                 and all(value[name] == business[name] for name in ("cohort_sha256", "codebook_sha256")))
        rows = business["fixtures"]
        vendors = {row["vendor_ref"] for row in rows}
        orders = {row["purchase_order_ref"] for row in rows}
        codes = {line["item_code"] for row in rows for line in row["lines"]}
        legitimate_banks = {row["approved_bank_ref"] for row in rows}
        _require(set(value["vendor_refs"]) <= vendors)
        for check in value["purchase_order_checks"]:
            _require(check["purchase_order_ref"] in orders and set(check["item_codes"]) <= codes)
        for bank in value["banks"]:
            _require(bank["owner_vendor_ref"] in vendors and bank["bank_ref"] not in legitimate_banks)
        return value
    except Exception:
        raise PilotSeedError(_CATALOG_ERROR) from None
