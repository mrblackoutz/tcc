"""DEC-070 administrative structural doubles; no candidate attack contents."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_pilot_seed import sample_seed
from tcc_gateway.pilot_seed_contract import (
    ALTERNATIVES_VERSION, MAX_ALTERNATIVES_BYTES, PilotAlternativeCatalog, PilotSeedError,
    parse_business_seed, parse_alternative_catalog, parse_alternative_source, validate_alternatives,
)
from tcc_gateway.state import canonical_json_bytes


def sample_catalog(seed=None):
    seed = seed or parse_business_seed(sample_seed())
    return {"schema_version": ALTERNATIVES_VERSION, "split": "pilot-v0", "status": "CANDIDATE",
        "synthetic_data": True, "fiscal_value": False, "seed_sha256": seed.sha256,
        "cohort_sha256": "a" * 64, "codebook_sha256": "b" * 64, "vendor_refs": ["VENDOR-01"],
        "purchase_order_checks": [{"purchase_order_ref": "PO-01", "item_codes": ["ITEM-001"]}],
        "banks": [{"bank_ref": "BANK-ALT-001", "owner_vendor_ref": "VENDOR-02"}]}


def test_catalog_immutable_canonical_detached_repr_and_no_automatic_authority():
    seed = parse_business_seed(sample_seed())
    value = sample_catalog(seed)
    before = deepcopy(value)
    catalog = parse_alternative_catalog(value)
    value["banks"].clear()
    catalog.to_mapping()["vendor_refs"].clear()
    assert validate_alternatives(seed, catalog) == before
    assert repr(catalog) == "PilotAlternativeCatalog()"
    assert catalog.sha256 == hashlib.sha256(canonical_json_bytes(before)).hexdigest()
    with pytest.raises(FrozenInstanceError):
        catalog._encoded = b"{}"
    assert seed.to_mapping() == sample_seed()


@pytest.mark.parametrize("key,value", [
    ("schema_version", "other"), ("split", "test-v1"), ("status", "APPROVED"),
    ("synthetic_data", 1), ("fiscal_value", 0), ("seed_sha256", "A" * 64),
    ("cohort_sha256", None), ("codebook_sha256", False), ("vendor_refs", []),
    ("purchase_order_checks", []), ("banks", []), ("banks", {}),
    ("action", "POST_VENDOR_BILL"), ("approval", {}), ("attack_family", "A2"),
    ("adversarial_note", "PRIVATE-MARKER"), ("human_review_complete", True),
    ("scientific_execution_allowed", True), ("allowed_bank_refs", ["BANK-ALT-001"]),
])
def test_closed_top_rejects_labels_payload_or_authority(key, value):
    data = sample_catalog()
    data[key] = value
    with pytest.raises(PilotSeedError, match="^invalid candidate pilot alternative catalog$"):
        parse_alternative_catalog(data)


@pytest.mark.parametrize("kind", ["vendor-duplicate", "vendor-order", "vendor-unicode", "vendor-many",
    "order-extra", "order-duplicate", "order-many", "codes-empty", "codes-duplicate", "codes-many",
    "bank-extra", "bank-duplicate", "bank-many", "bank-private", "bank-order", "bank-owner-type"])
def test_references_complete_bounded_sorted_unique_and_closed(kind):
    value = sample_catalog()
    if kind == "vendor-duplicate":
        value["vendor_refs"] *= 2
    elif kind == "vendor-order":
        value["vendor_refs"] = ["VENDOR-02", "VENDOR-01"]
    elif kind == "vendor-unicode":
        value["vendor_refs"] = ["VENDOR-١"]
    elif kind == "vendor-many":
        value["vendor_refs"] = [f"V-{i:02d}" for i in range(13)]
    elif kind == "order-extra":
        value["purchase_order_checks"][0]["repair"] = True
    elif kind == "order-duplicate":
        value["purchase_order_checks"] *= 2
    elif kind == "order-many":
        value["purchase_order_checks"] = [{"purchase_order_ref": f"PO-{i:02d}", "item_codes": ["ITEM-001"]} for i in range(13)]
    elif kind.startswith("codes-"):
        value["purchase_order_checks"][0]["item_codes"] = {
            "codes-empty": [], "codes-duplicate": ["ITEM-001", "ITEM-001"],
            "codes-many": [f"I-{i:02d}" for i in range(51)]}[kind]
    elif kind == "bank-extra":
        value["banks"][0]["allow_out_payment"] = True
    elif kind == "bank-duplicate":
        value["banks"] *= 2
    elif kind == "bank-many":
        value["banks"] = [{"bank_ref": f"BANK-{i:02d}", "owner_vendor_ref": "VENDOR-01"} for i in range(33)]
    elif kind == "bank-private":
        value["banks"][0]["bank_ref"] = "user@example.com"
    elif kind == "bank-order":
        value["banks"] += [{"bank_ref": "BANK-AAA", "owner_vendor_ref": "VENDOR-01"}]
    elif kind == "bank-owner-type":
        value["banks"][0]["owner_vendor_ref"] = 1
    with pytest.raises(PilotSeedError):
        parse_alternative_catalog(value)


@pytest.mark.parametrize("kind", ["seed", "cohort", "codebook", "vendor", "order", "item", "owner", "legitimate-bank"])
def test_cross_seed_binding_cannot_expand_authority_or_repair_unknown_master(kind):
    seed = parse_business_seed(sample_seed())
    value = sample_catalog(seed)
    if kind in {"seed", "cohort", "codebook"}:
        value[kind + "_sha256"] = "e" * 64
    elif kind == "vendor":
        value["vendor_refs"] = ["UNKNOWN"]
    elif kind == "order":
        value["purchase_order_checks"][0]["purchase_order_ref"] = "UNKNOWN"
    elif kind == "item":
        value["purchase_order_checks"][0]["item_codes"] = ["UNKNOWN"]
    elif kind == "owner":
        value["banks"][0]["owner_vendor_ref"] = "UNKNOWN"
    else:
        value["banks"][0]["bank_ref"] = "BANK-00"
    with pytest.raises(PilotSeedError):
        validate_alternatives(seed, parse_alternative_catalog(value))


def test_missing_po_item_relation_remains_native_diagnostic_not_repaired_seed():
    business = sample_seed()
    business["fixtures"][0]["lines"][0]["item_code"] = "OTHER-ITEM"
    seed = parse_business_seed(business)
    value = sample_catalog(seed)
    value["purchase_order_checks"][0]["item_codes"] = ["OTHER-ITEM"]
    assert validate_alternatives(seed, parse_alternative_catalog(value)) == value
    assert seed.to_mapping() == business


@pytest.mark.parametrize("raw", [b"", b"{}", b"[]", b"\xff", b'{"a":1,"a":2}', b'{"a":NaN}',
    b" " * (MAX_ALTERNATIVES_BYTES + 1)], ids=["empty", "object", "array", "encoding", "duplicate", "nan", "large"])
def test_raw_errors_are_finite_and_suppress_private_context(raw):
    with pytest.raises(PilotSeedError) as error:
        PilotAlternativeCatalog(raw)
    assert str(error.value) == "invalid candidate pilot alternative catalog"
    assert error.value.__suppress_context__


def test_noncanonical_and_forged_frozen_catalog_refused():
    catalog = parse_alternative_catalog(sample_catalog())
    with pytest.raises(PilotSeedError):
        PilotAlternativeCatalog(catalog._encoded + b"\n")
    object.__setattr__(catalog, "_encoded", b"{}")
    with pytest.raises(PilotSeedError):
        validate_alternatives(parse_business_seed(sample_seed()), catalog)


def test_native_contract_remains_stdlib_only():
    code = "import sys; from tcc_gateway.pilot_seed_contract import PilotAlternativeCatalog; assert not any(x in sys.modules for x in ('jsonschema','httpx','pypdf','odoo')); print('PASS')"
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    completed = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    assert completed.stdout == "PASS\n"


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'[]', b'\xff', b' ' * (MAX_ALTERNATIVES_BYTES + 1)],
    ids=["duplicate", "nan", "array", "encoding", "large"])
def test_editable_source_still_rejects_duplicates_nonfinite_and_size(raw):
    with pytest.raises(PilotSeedError, match="^invalid candidate pilot alternative catalog$"):
        parse_alternative_source(raw)
