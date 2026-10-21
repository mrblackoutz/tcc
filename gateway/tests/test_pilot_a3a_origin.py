"""DEC-068 structural doubles, never the authored local cohort."""

import base64
from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tcc_gateway import pilot_a3a_origin as compiler
from tcc_gateway import pilot_a3a_origin_contract as contract
from tcc_gateway.pilot_dataset import parse_pilot_recipes, prepare_pilot_cohort
from tcc_gateway.pilot_seed import prepare_business_seed
from tcc_gateway.pilot_seed_contract import PilotSeedError
from tcc_gateway.state import canonical_json_bytes


def sample_input():
    rows = []
    for index in range(4):
        docs = []
        for offset in range(2):
            raw = f"%PDF-1.4\nSTRUCTURAL-DOUBLE-{index}-{offset}\n%%EOF".encode()
            docs.append({"scenario_id": f"SCN-{index}-{offset}",
                "document_sha256": hashlib.sha256(raw).hexdigest(),
                "extracted_text_sha256": hashlib.sha256(b"TEXT" + raw).hexdigest(),
                "pdf_base64": base64.b64encode(raw).decode()})
        rows.append({"fixture_ref": f"FIX-{index}", "pair_sha256": str(index) * 64,
            "document_ref": f"DOC-{index}", "invoice_date_min": "2026-10-01", "invoice_date_max": "2026-10-31",
            "document": docs[0], "other_document": docs[1]})
    return {"schema_version": contract.ORIGIN_VERSION, "status": "CANDIDATE", "split": "pilot-v0",
        "synthetic_data": True, "fiscal_value": False, "seed_sha256": "a" * 64,
        "cohort_sha256": "b" * 64, "codebook_sha256": "c" * 64, "fixtures": rows}


def structural_cohort(codebook="f" * 64):
    from test_pilot_dataset import sample_recipes
    value = sample_recipes()
    for index, row in enumerate(value["pairs"]):
        row["pair"]["truth"]["purchase_order_ref"] = f"PO-{index:02d}"
    return prepare_pilot_cohort(parse_pilot_recipes(value), codebook)


def test_closed_roundtrip_safe_repr_defensive_copy_and_digest():
    value = sample_input()
    package = contract.parse_origin_input(value)
    original = deepcopy(value)
    value["fixtures"][0]["document_ref"] = "CHANGED"
    detached = package.to_mapping()
    detached["fixtures"].clear()
    assert package.to_mapping() == original
    assert package.sha256 == hashlib.sha256(canonical_json_bytes(original)).hexdigest()
    assert "pdf_base64" not in repr(package) and "DOC-" not in repr(package)
    with pytest.raises(FrozenInstanceError):
        package._encoded = b"{}"


@pytest.mark.parametrize("key,value", [("status", "READY"), ("split", "test-v1"), ("synthetic_data", 1),
    ("fiscal_value", 0), ("schema_version", "new/v2"), ("seed_sha256", "A" * 64),
    ("cohort_sha256", None), ("codebook_sha256", "bad")])
def test_non_candidate_and_invalid_binding_rejected(key, value):
    candidate = sample_input()
    candidate[key] = value
    with pytest.raises(PilotSeedError):
        contract.parse_origin_input(candidate)


@pytest.mark.parametrize("level", ["top", "fixture", "document"])
@pytest.mark.parametrize("name", ["expected_action", "attack_family", "approval", "target_move_id", "model_output"])
def test_labels_authority_and_unknown_keys_excluded(level, name):
    value = sample_input()
    target = value if level == "top" else value["fixtures"][0]
    if level == "document":
        target = target["document"]
    target[name] = "PRIVATE-MARKER"
    with pytest.raises(PilotSeedError) as error:
        contract.parse_origin_input(value)
    assert "PRIVATE-MARKER" not in str(error.value)


@pytest.mark.parametrize("mutation", ["short", "extra", "unsorted", "duplicate-fixture", "duplicate-pair",
    "duplicate-ref", "duplicate-scenario", "duplicate-document", "duplicate-text", "bad-date", "reverse-dates",
    "bad-base64", "bad-pdf", "hash-mismatch", "oversized-pdf", "wrong-scenario"])
def test_closed_fixture_and_document_constraints(mutation):
    value = sample_input()
    rows = value["fixtures"]
    doc = rows[0]["document"]
    if mutation == "short":
        rows.pop()
    elif mutation == "extra":
        rows.append(deepcopy(rows[-1]))
    elif mutation == "unsorted":
        rows.reverse()
    elif mutation.startswith("duplicate-"):
        key = {"duplicate-fixture": "fixture_ref", "duplicate-pair": "pair_sha256", "duplicate-ref": "document_ref",
               "duplicate-scenario": "scenario_id", "duplicate-document": "document_sha256",
               "duplicate-text": "extracted_text_sha256"}[mutation]
        if key in rows[0]:
            rows[1][key] = rows[0][key]
        else:
            rows[0]["other_document"][key] = doc[key]
    elif mutation == "bad-date":
        rows[0]["invoice_date_min"] = "2026-02-30"
    elif mutation == "reverse-dates":
        rows[0]["invoice_date_min"] = "2026-11-01"
    elif mutation == "bad-base64":
        doc["pdf_base64"] += "?"
    elif mutation == "hash-mismatch":
        doc["document_sha256"] = "e" * 64
    elif mutation == "wrong-scenario":
        doc["scenario_id"] = "../PRIVATE-MARKER"
    else:
        raw = b"not PDF" if mutation == "bad-pdf" else b"%PDF-" + b"x" * contract.MAX_PDF_BYTES
        doc["document_sha256"] = hashlib.sha256(raw).hexdigest()
        doc["pdf_base64"] = base64.b64encode(raw).decode()
    with pytest.raises(PilotSeedError):
        contract.parse_origin_input(value)


@pytest.mark.parametrize("raw", [b"{}", b"{\"schema_version\":NaN}", b"{\"x\":1,\"x\":1}", b"\xff", b""],
                         ids=["empty-object", "constant", "duplicate-keys", "invalid-utf8", "empty-bytes"])
def test_invalid_bytes_finite(raw):
    with pytest.raises(PilotSeedError):
        contract.PilotA3aOriginInput(raw)


def test_canonical_bytes_and_revalidation_of_forged_instance():
    value = sample_input()
    for raw in (json.dumps(value).encode(), canonical_json_bytes(value) + b"\n", b"x" * (contract.MAX_ORIGIN_BYTES + 1)):
        with pytest.raises(PilotSeedError):
            contract.PilotA3aOriginInput(raw)
    forged = contract.parse_origin_input(value)
    object.__setattr__(forged, "_encoded", b"{}")
    with pytest.raises(PilotSeedError):
        forged.to_mapping()


def test_compiler_preserves_cohort_and_exact_document_provenance_without_post_output():
    cohort = structural_cohort()
    before = cohort.to_manifest()
    package = compiler.prepare_origin_input(cohort)
    value = package.to_mapping()
    assert before == cohort.to_manifest()
    assert value["seed_sha256"] == prepare_business_seed(cohort).sha256
    assert value["cohort_sha256"] == hashlib.sha256(canonical_json_bytes(before)).hexdigest()
    assert len(value["fixtures"]) == 4
    pairs = {item.pair.to_mapping()["fixture_ref"]: item for item in cohort.pairs}
    for row in value["fixtures"]:
        source = pairs[row["fixture_ref"]]
        mapping = source.pair.to_mapping()
        assert mapping["truth"]["expected_action"] == "POST_VENDOR_BILL"
        assert row["document_ref"] == mapping["truth"]["document_ref"]
        for index, (kind, name) in enumerate((("benign", "document"), ("adversarial", "other_document"))):
            assert row[name]["scenario_id"] == mapping["members"][kind]["scenario_id"]
            assert contract.document_bytes(row[name]) == source.documents[index].pdf_bytes
    for forbidden in ("expected_action", "attack_family", "approval", "target_move_id", "POST_VENDOR_BILL", "model_output"):
        assert forbidden not in package._encoded.decode()
    assert before["human_review_complete"] is False and before["scientific_execution_allowed"] is False


def test_extraction_hash_is_checked_against_pdf_not_accepted_as_assertion():
    package = compiler.prepare_origin_input(structural_cohort())
    value = package.to_mapping()
    value["fixtures"][0]["document"]["extracted_text_sha256"] = "e" * 64
    changed = contract.parse_origin_input(value)
    with pytest.raises(PilotSeedError):
        compiler.verify_extraction(changed)


def test_stdlib_contract_import_does_not_load_provider_pdf_or_scientific_modules():
    code = "import sys; import tcc_gateway.pilot_a3a_origin_contract; assert not any(x in sys.modules for x in ('httpx','pypdf','jsonschema','odoo','tcc_gateway.pilot_dataset')); print('STDLIB_PASS')"
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "STDLIB_PASS"
