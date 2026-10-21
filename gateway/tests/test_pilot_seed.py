"""DEC-067 structural doubles only; never authored pilot payloads."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tcc_gateway.pilot_seed_contract import (
    MAX_SEED_BYTES, SEED_VERSION, PilotBusinessSeed, PilotSeedError, parse_business_seed,
)
from tcc_gateway.state import canonical_json_bytes


def sample_seed():
    return {"schema_version": SEED_VERSION, "split": "pilot-v0", "status": "CANDIDATE",
        "synthetic_data": True, "fiscal_value": False, "cohort_sha256": "a" * 64,
        "codebook_sha256": "b" * 64, "dataset_version": "structural-double-v0", "fixtures": [
            {"fixture_ref": f"FIX-{index:02d}", "pair_sha256": hashlib.sha256(str(index).encode()).hexdigest(),
             "company_ref": "COMPANY-001", "vendor_ref": f"VENDOR-{index:02d}",
             "purchase_order_ref": f"PO-{index:02d}", "invoice_date": "2026-09-30",
             "currency": "BRL", "amount": "125.50", "approved_bank_ref": f"BANK-{index:02d}",
             "quantity_scale": 2, "lines": [{"item_code": "ITEM-001", "quantity": "1.00",
                                             "unit_price": "125.50", "line_total": "125.50"}]}
            for index in range(12)]}


def test_canonical_immutable_detached_seed_no_action_or_payload():
    value = sample_seed()
    seed = parse_business_seed(value)
    original = deepcopy(value)
    value["fixtures"][0]["amount"] = "9.00"
    seed.to_mapping()["fixtures"].clear()
    assert seed.to_mapping() == original
    assert seed.sha256 == hashlib.sha256(canonical_json_bytes(original)).hexdigest()
    assert repr(seed) == "PilotBusinessSeed()"
    with pytest.raises(FrozenInstanceError):
        seed._encoded = b"{}"


@pytest.mark.parametrize("key,value", [
    ("schema_version", "other"), ("split", "test-v1"), ("status", "APPROVED"),
    ("synthetic_data", 1), ("fiscal_value", 0), ("cohort_sha256", "F" * 64),
    ("codebook_sha256", None), ("dataset_version", "x\nSECRET"),
    ("human_review_complete", True), ("scientific_execution_allowed", True),
    ("action", "POST_VENDOR_BILL"), ("model_output", {}),
])
def test_top_closed_and_pending_contract(key, value):
    seed = sample_seed()
    seed[key] = value
    with pytest.raises(PilotSeedError):
        parse_business_seed(seed)


@pytest.mark.parametrize("key,value", [
    ("fixture_ref", " x"), ("pair_sha256", False), ("company_ref", "x\u200b"),
    ("vendor_ref", "user@example.com"), ("purchase_order_ref", "PO\nX"),
    ("invoice_date", "2026-02-30"), ("invoice_date", "2026-9-1"),
    ("currency", "USD"), ("amount", "125.500"), ("amount", "125.49"),
    ("approved_bank_ref", ""), ("quantity_scale", True), ("quantity_scale", 5),
    ("expected_action", "POST_VENDOR_BILL"), ("attack_family", "A2"),
    ("approval", {}), ("payload", "PRIVATE-MARKER"), ("target_move_id", 42),
])
def test_row_closed_and_no_labels_authority_or_raw_values(key, value):
    seed = sample_seed()
    seed["fixtures"][0][key] = value
    with pytest.raises(PilotSeedError) as error:
        parse_business_seed(seed)
    assert str(error.value) == "invalid candidate pilot business seed"
    assert error.value.__suppress_context__


@pytest.mark.parametrize("key,value", [
    ("item_code", "x"), ("quantity", "0.00"), ("quantity", "1.0"),
    ("quantity", 1.0), ("quantity", "9999999999999.00"),
    ("unit_price", "-1.00"), ("unit_price", "0.00"), ("unit_price", "NaN"),
    ("quantity", "١.00"), ("unit_price", "125.٥٠"), ("quantity", "1000000.00"),
    ("line_total", "125.49"), ("description", "PRIVATE"),
])
def test_line_arithmetic_and_closed_fields(key, value):
    seed = sample_seed()
    seed["fixtures"][0]["lines"][0][key] = value
    with pytest.raises(PilotSeedError):
        parse_business_seed(seed)


@pytest.mark.parametrize("mutation", ["few", "many", "reordered", "duplicate-ref", "duplicate-pair",
    "duplicate-po", "two-companies", "bank-owner-conflict", "duplicate-item", "empty-lines", "too-many-lines"])
def test_global_conflicts_or_incomplete_seed_rejected(mutation):
    value = sample_seed()
    rows = value["fixtures"]
    if mutation == "few":
        rows.pop()
    elif mutation == "many":
        rows.append(deepcopy(rows[0]))
    elif mutation == "reordered":
        rows.reverse()
    elif mutation.startswith("duplicate-") and mutation != "duplicate-item":
        key = {"duplicate-ref": "fixture_ref", "duplicate-pair": "pair_sha256", "duplicate-po": "purchase_order_ref"}[mutation]
        rows[1][key] = rows[0][key]
    elif mutation == "two-companies":
        rows[0]["company_ref"] = "OTHER-COMPANY"
    elif mutation == "bank-owner-conflict":
        rows[1]["approved_bank_ref"] = rows[0]["approved_bank_ref"]
    elif mutation == "empty-lines":
        rows[0]["lines"] = []
    else:
        rows[0]["lines"] *= 51 if mutation == "too-many-lines" else 2
    with pytest.raises(PilotSeedError):
        parse_business_seed(value)


@pytest.mark.parametrize("raw", [b"", b"{}", b"[]", b"\xff", b'{"x":NaN}',
    b'{"x":1,"x":2}', b" " * (MAX_SEED_BYTES + 1)],
    ids=["empty", "object", "array", "encoding", "nan", "duplicate", "oversized"])
def test_invalid_raw_fails_without_details(raw):
    with pytest.raises(PilotSeedError, match="invalid candidate pilot business seed"):
        PilotBusinessSeed(raw)


def test_whitespace_reencoding_and_forged_frozen_object_fail():
    seed = parse_business_seed(sample_seed())
    with pytest.raises(PilotSeedError):
        PilotBusinessSeed(seed._encoded + b"\n")
    object.__setattr__(seed, "_encoded", b"{}")
    with pytest.raises(PilotSeedError):
        seed.to_mapping()


def test_subcent_truth_not_rounded_and_high_precision_is_supported():
    value = sample_seed()
    row = value["fixtures"][0]
    row["quantity_scale"] = 4
    row["lines"][0].update(quantity="1.0001", unit_price="100.00", line_total="100.01")
    row["amount"] = "100.01"
    assert parse_business_seed(value).to_mapping() == value
    row["lines"][0]["unit_price"] = "99.99"
    with pytest.raises(PilotSeedError):
        parse_business_seed(value)


def test_contract_import_is_stdlib_only_in_fresh_process():
    code = "import sys; from tcc_gateway import pilot_seed_contract; assert not any(x in sys.modules for x in ('jsonschema','httpx','pypdf','odoo')); print('PASS')"
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    completed = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    assert completed.stdout == "PASS\n"


def test_compile_verified_cohort_does_not_copy_labels_or_notes():
    from test_pilot_dataset import sample_recipes
    from tcc_gateway.pilot_dataset import parse_pilot_recipes, prepare_pilot_cohort
    from tcc_gateway.pilot_seed import prepare_business_seed
    recipes = sample_recipes()
    for index, recipe in enumerate(recipes["pairs"]):
        recipe["pair"]["truth"]["purchase_order_ref"] = f"PO-{index:02d}"
    cohort = prepare_pilot_cohort(parse_pilot_recipes(recipes), "f" * 64)
    before = cohort.to_manifest()
    value = prepare_business_seed(cohort).to_mapping()
    assert len(value["fixtures"]) == 12 and cohort.to_manifest() == before
    assert value["cohort_sha256"] == hashlib.sha256(canonical_json_bytes(before)).hexdigest()
    encoded = canonical_json_bytes(value).decode()
    for forbidden in ("attack_family", "expected_action", "expected_disposition", "approval", "benign_note",
                      "adversarial_note", "scenario_id", "target_move_id", "Nota estrutural"):
        assert forbidden not in encoded
    assert before["human_review_complete"] is False and before["scientific_execution_allowed"] is False


def test_shared_product_correction_changes_only_affected_pair_documents_and_not_financial_facts():
    """DEC-071: two orders may buy the same product at different prices.

    Structural doubles only: no actual recipe, payload, identity or scientific
    model output is embedded here. Existing strict generators/loaders suffice.
    """
    from test_pilot_dataset import sample_recipes
    from tcc_gateway.pilot_dataset import parse_pilot_recipes, prepare_pilot_cohort
    from tcc_gateway.pilot_seed import prepare_business_seed

    source = sample_recipes()
    for index, recipe in enumerate(source["pairs"]):
        truth = recipe["pair"]["truth"]
        truth["purchase_order_ref"] = f"PO-{index:02d}"
        truth["lines"][0]["item_code"] = f"ITEM-{index:02d}"
    source["pairs"][0]["pair"]["attack_target"] = "purchase_order_ref"
    source["pairs"][0]["pair"]["truth"]["forbidden_delta_codes"] = ["PURCHASE_ORDER_REF_UNCHANGED"]
    alternate = source["pairs"][8]["pair"]["truth"]
    alternate["lines"][0].update(unit_price="200.00", line_total="200.00")
    alternate["amount"] = "200.00"
    original = deepcopy(source)
    previous = prepare_pilot_cohort(parse_pilot_recipes(source), "f" * 64)
    old_seed = prepare_business_seed(previous).to_mapping()
    corrected = deepcopy(source)
    corrected["dataset_version"] = "double-v1"
    for recipe in corrected["pairs"]:
        recipe["pair"]["dataset_version"] = "double-v1"
    corrected["pairs"][0]["pair"]["truth"]["lines"][0]["item_code"] = alternate["lines"][0]["item_code"]
    revised = prepare_pilot_cohort(parse_pilot_recipes(corrected), "f" * 64)
    seed = prepare_business_seed(revised).to_mapping()
    assert source == original and previous.to_manifest()["dataset_version"] == "double-v0"
    changed = []
    for index, (old, new) in enumerate(zip(previous.pairs, revised.pairs, strict=True)):
        for first, second in zip(old.documents, new.documents, strict=True):
            assert first.note == second.note and first.page_count == second.page_count
            assert (first.extracted_text != second.extracted_text) == (index == 0)
            if first.pdf_bytes != second.pdf_bytes:
                changed.append(index)
    assert changed == [0, 0]
    for index, (old, new) in enumerate(zip(old_seed["fixtures"], seed["fixtures"], strict=True)):
        new = deepcopy(new)
        assert new.pop("pair_sha256") != old["pair_sha256"]  # versioned metadata of all pairs
        old = {key: value for key, value in old.items() if key != "pair_sha256"}
        if index == 0:
            assert new["lines"][0]["item_code"] == "ITEM-08"
            new["lines"][0]["item_code"] = "ITEM-00"
        assert new == old
    refs = [line["item_code"] for row in seed["fixtures"] for line in row["lines"]]
    assert len(refs) == 12 and len(set(refs)) == 11 and refs.count("ITEM-08") == 2
    assert revised.to_manifest()["counts"]["families"] == {"A1": 4, "A2": 4, "A3a": 4}
    assert revised.to_manifest()["human_review_complete"] is False
    assert revised.to_manifest()["scientific_execution_allowed"] is False
