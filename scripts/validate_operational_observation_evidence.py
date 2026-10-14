"""Validate native synthetic observations against the gateway contract.

This proves schema/hash parity and the separately prepared fixture binding,
not a live gateway policy round-trip, scientific classification or authority
against a malicious administrator. It never publishes payloads or secrets.
"""

from __future__ import annotations

import argparse
from dataclasses import fields
import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway" / "src"))

from tcc_gateway.operational_observation import (  # noqa: E402
    ObservationBinding, parse_registered_observation,
)


CASE_IDS = (
    "observe_create_open_clean_readonly",
    "observe_ledger_duplicate_changed_reference",
    "observe_native_reference_duplicate",
    "observe_closed_period_executor_identity",
    "observe_post_origin_not_duplicate",
    "observe_post_additional_reference_duplicate",
    "observe_audit_preflight_unavailable",
    "observe_candidate_hash_changes_with_reference_and_date",
)

COMMON_CHECKS = frozenset({
    "ordinary_cursor_and_registry", "original_registration_preserved",
    "full_company_projection_unchanged_before_and_after_commit",
    "financial_receipts_approval_events_attachments_and_guards_unchanged",
    "purchase_computeds_and_supplier_rank_unchanged", "caller_callback_counts_preserved",
    "caller_callback_runs_once_after_real_commit", "complete_candidate_and_trusted_scope_verified",
    "server_observation_integrity_verified",
})
CASE_CHECKS = dict(zip(CASE_IDS, (
    {"real_open_period_and_no_duplicate", "no_financial_preparation_needed"},
    {"registered_document_duplicate_survives_changed_reference", "secondary_reference_not_mistaken_for_document_identity"},
    {"real_native_vendor_bill_reference_detected", "no_ledger_document_receipt_fabricated"},
    {"native_executor_uid_period_closed", "uid1_only_exception_does_not_authorize_executor", "no_clock_override"},
    {"actual_audited_create_origin_excluded_from_duplicate", "target_derived_from_actual_original_receipt", "no_post_or_approval_performed"},
    {"only_original_create_receipt_and_move_excluded", "additional_native_reference_duplicate_detected", "no_post_or_approval_performed"},
    {"real_attachment_storage_preflight_unavailable", "no_test_insert_or_healthcheck_artifact", "audit_unavailability_explicit"},
    {"both_candidate_actions_independently_hash_verified", "changed_reference_and_date_change_action_hash", "same_registration_provenance_and_unchanged_state"},
), strict=True))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def validate_records(proof, *, git_base, source_bundle_sha256, configuration_sha256):
    """Check closed records without using observations as their own binding."""
    if (type(proof) is not dict or proof.get("schema_version") != "operational-observation-transactions-evidence/v1"
            or proof.get("status") != "PASS" or proof.get("git_base") != git_base
            or proof.get("source_bundle_sha256") != source_bundle_sha256
            or proof.get("configuration_sha256") != configuration_sha256
            or type(proof.get("record_count")) is not int or proof["record_count"] != 9):
        raise ValueError("invalid native observation proof")
    for name, expected in (("normal_registry", True), ("test_cursor_used", False),
            ("registry_test_mode", False), ("mocked_sql_commit", False),
            ("mocked_financial_method", False), ("mocked_clock", False),
            ("approval_material_emitted", False), ("public_executor_enabled", False),
            ("public_financial_effects_enabled", False), ("scientific_run", False),
            ("human_review_complete", False), ("real_api_used", False)):
        if proof.get(name) is not expected:
            raise ValueError("native profile flags must be strict booleans")
    for name, expected in (("case_count", 8), ("test_count", 8), ("passed_case_count", 8),
            ("real_provider_calls_executed", 0)):
        if type(proof.get(name)) is not int or proof[name] != expected:
            raise ValueError("native profile counts must be strict integers")
    cases = proof.get("cases")
    if (type(cases) is not list or len(cases) != 8
            or tuple(case.get("case_id") for case in cases) != CASE_IDS
            or any(case.get("status") != "PASS" for case in cases)):
        raise ValueError("native cases incomplete")
    for case in cases:
        checks = case.get("checks")
        required = COMMON_CHECKS | CASE_CHECKS[case["case_id"]]
        if (type(checks) is not dict or set(checks) != required | {"projection_sha256"}
                or any(checks[name] is not True for name in required)
                or type(checks["projection_sha256"]) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", checks["projection_sha256"]) is None):
            raise ValueError("native checks incomplete or not strict")
    records = proof.get("observation_records")
    if type(records) is not list or len(records) != 9:
        raise ValueError("native records incomplete")
    counts = dict.fromkeys(CASE_IDS, 0)
    grouped = {name: [] for name in CASE_IDS}
    binding_fields = {field.name for field in fields(ObservationBinding)}
    for record in records:
        if (type(record) is not dict or set(record) != {"case_id", "observation", "expected_binding"}
                or record["case_id"] not in counts or type(record["expected_binding"]) is not dict
                or set(record["expected_binding"]) != binding_fields):
            raise ValueError("invalid native observation record")
        binding = ObservationBinding.from_mapping(record["expected_binding"])
        if (binding.code_commit != git_base or binding.code_sha256 != "sha256:" + source_bundle_sha256
                or binding.configuration_sha256 != "sha256:" + configuration_sha256):
            raise ValueError("native observation source binding differs")
        observation = parse_registered_observation(record["observation"], binding)
        if observation.to_mapping() != record["observation"]:
            raise ValueError("native observation must not be repaired")
        value = observation.to_mapping()
        facts, scope = value["facts"], value["scope"]
        expected_document = record["case_id"] == CASE_IDS[1]
        expected_reference = record["case_id"] in {CASE_IDS[2], CASE_IDS[5]}
        expected_period = record["case_id"] != CASE_IDS[3]
        expected_audit = "UNAVAILABLE" if record["case_id"] == CASE_IDS[6] else "AVAILABLE"
        expected_mode = "POST_APPROVED" if record["case_id"] in {CASE_IDS[4], CASE_IDS[5]} else "CREATE_DRAFT"
        if (facts != {"document_duplicate": expected_document, "reference_duplicate": expected_reference,
                "duplicate_detected": expected_document or expected_reference, "accounting_period_open": expected_period}
                or value["preflight"] != {"state": "AVAILABLE", "audit": expected_audit}
                or scope["executor_mode"] != expected_mode):
            raise ValueError("native case facts or mode differ from its objective")
        grouped[record["case_id"]].append(value)
        counts[record["case_id"]] += 1
    if any(count != (2 if name == CASE_IDS[-1] else 1) for name, count in counts.items()):
        raise ValueError("native observation case coverage incomplete")
    first, second = grouped[CASE_IDS[-1]]
    if (first["registration"] != second["registration"] or first["provenance"] != second["provenance"]
            or any(first["scope"][name] == second["scope"][name] for name in ("action_sha256", "document_ref", "invoice_date"))
            or {name: item for name, item in first["scope"].items() if name not in {"action_sha256", "document_ref", "invoice_date"}}
            != {name: item for name, item in second["scope"].items() if name not in {"action_sha256", "document_ref", "invoice_date"}}):
        raise ValueError("native candidate-change proof incomplete")
    return len(records)


def main():
    parser = argparse.ArgumentParser(description="Validate ignored native observation contract evidence")
    for name in ("evidence", "git-base", "source-bundle-sha256", "configuration-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    result = {
        "schema_version": "registered-operational-contract-validation/v1",
        "status": "FAIL", "record_count": 0,
        "scope": "schema-integrity-and-independent-fixture-binding-only",
        "gateway_live_state_reader_used": False, "scientific_run": False,
        "human_review_complete": False,
    }
    try:
        if (re.fullmatch(r"[0-9a-f]{40}", args.git_base) is None
                or re.fullmatch(r"[0-9a-f]{64}", args.source_bundle_sha256) is None
                or re.fullmatch(r"[0-9a-f]{64}", args.configuration_sha256) is None):
            raise ValueError("invalid source declaration")
        evidence = Path(args.evidence).resolve(strict=True)
        allowed = (ROOT / ".runtime" / "run-02-observation").resolve()
        if (not evidence.is_relative_to(allowed) or evidence.name != "operational-observation-transactions.json"
                or not 1 <= evidence.stat().st_size <= 2_097_152):
            raise ValueError("invalid ignored evidence path or size")
        raw = evidence.read_bytes()
        proof = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        result["record_count"] = validate_records(proof, git_base=args.git_base,
            source_bundle_sha256=args.source_bundle_sha256, configuration_sha256=args.configuration_sha256)
        result["status"] = "PASS"
        result["native_evidence_sha256"] = hashlib.sha256(raw).hexdigest()
    except Exception:
        # No repr/traceback/exception messages, records or trusted fixture data.
        result["status"] = "FAIL"
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
