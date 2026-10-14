"""Adversarial synthetic tests of proof gates, never native evidence."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("operational_evidence_validator",
    ROOT / "scripts" / "validate_operational_observation_evidence.py")
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)

DECLARATION = {"git_base": "f" * 40, "source_bundle_sha256": "1" * 64,
               "configuration_sha256": "2" * 64}


def _hash_record(value):
    payload = {name: item for name, item in value.items() if name != "observation_sha256"}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    value["observation_sha256"] = "sha256:" + hashlib.sha256(b"tcc-operational-observation/v1\0" + raw).hexdigest()


def _proof():
    result = {"schema_version": "operational-observation-transactions-evidence/v1", "status": "PASS",
        **DECLARATION, "record_count": 9, "case_count": 8, "test_count": 8, "passed_case_count": 8,
        "real_provider_calls_executed": 0, "cases": [], "observation_records": [],
        "normal_registry": True, "test_cursor_used": False, "registry_test_mode": False,
        "mocked_sql_commit": False, "mocked_financial_method": False, "mocked_clock": False,
        "approval_material_emitted": False, "public_executor_enabled": False,
        "public_financial_effects_enabled": False, "scientific_run": False, "human_review_complete": False,
        "real_api_used": False}
    for index, case_id in enumerate(validator.CASE_IDS):
        checks = {name: True for name in validator.COMMON_CHECKS | validator.CASE_CHECKS[case_id]}
        checks["projection_sha256"] = "sha256:" + "3" * 64
        result["cases"].append({"case_id": case_id, "status": "PASS", "checks": checks})
        for variant in range(2 if index == 7 else 1):
            post = index in {4, 5}
            document, reference = index == 1, index in {2, 5}
            provenance = {"code_commit": DECLARATION["git_base"],
                "code_sha256": "sha256:" + DECLARATION["source_bundle_sha256"],
                "configuration_sha256": "sha256:" + DECLARATION["configuration_sha256"]}
            registration = {"registration_id": 1, "registration_sha256": "sha256:" + "4" * 64}
            scope = {"company_id": 1, "executor_user_id": 2, "vendor_id": 3,
                "purchase_order_id": 4, "purchase_line_ids": [5], "journal_id": 6,
                "allowed_bank_ids": [7], "scenario_id": "TCC-VALIDATOR-SEM-VALOR-FISCAL",
                "document_sha256": "5" * 64, "policy_version": "policy-v1.0.0",
                "invoice_date_min": "2026-09-01", "invoice_date_max": "2026-09-30",
                "monetary_tolerance": "0.00", "quantity_scale": 2,
                "executor_mode": "POST_APPROVED" if post else "CREATE_DRAFT",
                "action_sha256": "sha256:" + format(index + variant + 10, "064x"),
                "document_ref": "NF-TCC-CHANGED" if variant else "NF-TCC-BASE",
                "invoice_date": "2026-09-29" if variant else "2026-09-30",
                "target_move_id": 8 if post else None}
            observation = {"schema_version": "registered-operational-observation/v1",
                "registration": registration, "provenance": provenance, "scope": scope,
                "facts": {"document_duplicate": document, "reference_duplicate": reference,
                    "duplicate_detected": document or reference, "accounting_period_open": index != 3},
                "preflight": {"state": "AVAILABLE", "audit": "UNAVAILABLE" if index == 6 else "AVAILABLE"},
                "observed_at": "2026-09-30T12:00:00Z"}
            _hash_record(observation)
            binding = {**registration, **provenance, **{name: copy.deepcopy(scope[name]) for name in (
                "company_id", "executor_user_id", "vendor_id", "purchase_order_id", "journal_id",
                "purchase_line_ids", "allowed_bank_ids")}}
            result["observation_records"].append({"case_id": case_id, "observation": observation,
                "expected_binding": binding})
    return result


def _accept(proof):
    return validator.validate_records(proof, **DECLARATION)


def test_all_nine_explicit_synthetic_records_pass_without_repair():
    proof = _proof()
    original = copy.deepcopy(proof)
    assert _accept(proof) == 9
    assert proof == original


@pytest.mark.parametrize("invalid", ["true", 1, 0, None])
def test_nonboolean_native_profile_flags_rejected(invalid):
    proof = _proof()
    proof["normal_registry"] = invalid
    with pytest.raises(ValueError):
        _accept(proof)


@pytest.mark.parametrize("invalid", [True, "8", 8.0, None])
def test_noninteger_case_count_rejected(invalid):
    proof = _proof()
    proof["case_count"] = invalid
    with pytest.raises(ValueError):
        _accept(proof)


@pytest.mark.parametrize("invalid", [True, "false", 0, None])
def test_real_api_flag_must_be_explicit_boolean_false(invalid):
    proof = _proof()
    proof["real_api_used"] = invalid
    with pytest.raises(ValueError):
        _accept(proof)


@pytest.mark.parametrize("mutation", ["empty", "digest-only", "false", "numeric", "string", "extra", "bad-digest"])
def test_no_empty_innocuous_or_coercible_checks(mutation):
    proof = _proof()
    checks = proof["cases"][0]["checks"]
    if mutation == "empty":
        checks.clear()
    elif mutation == "digest-only":
        proof["cases"][0]["checks"] = {"projection_sha256": 123}
    elif mutation in {"false", "numeric", "string"}:
        checks["ordinary_cursor_and_registry"] = {"false": False, "numeric": 1, "string": "true"}[mutation]
    elif mutation == "extra":
        checks["irrelevant"] = True
    else:
        checks["projection_sha256"] = "invalid"
    with pytest.raises(ValueError):
        _accept(proof)


@pytest.mark.parametrize("index", [1, 2, 3, 4, 5, 6])
def test_clean_observation_cannot_fabricate_named_native_case(index):
    proof = _proof()
    proof["observation_records"][index]["observation"] = copy.deepcopy(proof["observation_records"][0]["observation"])
    with pytest.raises(ValueError):
        _accept(proof)


@pytest.mark.parametrize("field", ["document_ref", "invoice_date", "action_sha256"])
def test_candidate_pair_must_change_all_three_bindings(field):
    proof = _proof()
    first, second = proof["observation_records"][-2:]
    second["observation"]["scope"][field] = first["observation"]["scope"][field]
    _hash_record(second["observation"])
    with pytest.raises(ValueError):
        _accept(proof)


def test_rehashed_extra_bank_not_in_independent_binding_rejected():
    proof = _proof()
    value = proof["observation_records"][0]["observation"]
    value["scope"]["allowed_bank_ids"].append(9)
    _hash_record(value)
    with pytest.raises(ValueError):
        _accept(proof)


def test_caller_binding_cannot_change_source_provenance():
    proof = _proof()
    proof["observation_records"][0]["expected_binding"]["code_commit"] = "a" * 40
    with pytest.raises(ValueError):
        _accept(proof)
