"""Closed sanitized envelope checks; no secret, Odoo or runtime dependency."""

from copy import deepcopy
import hashlib
import json

import pytest

from tcc_gateway.approval_observation import (
    ApprovalObservationError, INDETERMINATE_REASON_CODES, REJECTED_REASON_CODES, VERSION,
    parse_approval_observation, reference_action_sha256,
)


def fixture():
    action = {
        "canonicalization_version": "canon/v1", "action_schema_version": "vendor-bill-action-proposal/v2",
        "policy_version": "policy-v1.0.0", "action": "POST_VENDOR_BILL", "executor_mode": "POST_APPROVED",
        "scenario_id": "SYNTHETIC-01", "document_sha256": "3" * 64, "vendor_ref": "SYNTHETIC-VENDOR",
        "purchase_order_ref": "SYNTHETIC-PO", "document_ref": "SYNTHETIC-DOC", "invoice_date": "2026-10-01",
        "currency": "BRL", "amount": "100.00", "recipient_bank_ref": "SYNTHETIC-BANK",
        "lines": [{"item_code": "SYNTHETIC-ITEM", "quantity": "4.00", "unit_price": "25.00"}], "target_move_id": 101,
    }
    return {
        "schema_version": VERSION,
        "binding": {"run_id": "1" * 32, "condition": "C0", "company_id": 11, "executor_user_id": 22,
            "scenario_id": action["scenario_id"], "document_sha256": action["document_sha256"],
            "code_commit": "4" * 40, "configuration_sha256": "2" * 64, "before_capture_sha256": "5" * 64,
            "host_id": "synthetic-host", "clock_id": "synthetic-monotonic"},
        "reference_action": action,
        "verification": {"status": "VERIFIED", "reason_code": None, "metadata": {
            "action_hash": reference_action_sha256(action), "approval_sha256": "sha256:" + "6" * 64,
            "nonce_sha256": "sha256:" + "7" * 64, "command_sha256": "sha256:" + "8" * 64,
            "key_id": "synthetic-observer-v1", "fixture_id": "SYNTHETIC-APR", "scenario_id": action["scenario_id"],
            "approver_ref": "SYNTHETIC-APPROVER", "issued_at": "2026-10-01T12:00:00Z", "expires_at": "2026-10-01T12:10:00Z"}},
        "nonce_available": True,
        "timing": {"checked_at": "2026-10-01T12:05:00Z", "call_started_at": "2026-10-01T12:05:01Z",
            "call_finished_at": "2026-10-01T12:05:02Z", "started_ns": 10, "finished_ns": 20},
        "decision_window": {"evaluated_at": "2026-10-01T12:00:00Z", "expires_at": "2026-10-01T12:10:00Z"},
    }


def target(value, path):
    for item in path:
        value = value[item]
    return value


def test_parser_returns_detached_mapping_and_action_hash_matches_exact_canonical_bytes():
    value = fixture()
    result = parse_approval_observation(value)
    assert result == value and result is not value
    result["reference_action"]["lines"][0]["quantity"] = "999.00"
    assert value["reference_action"]["lines"][0]["quantity"] == "4.00"
    encoded = json.dumps(value["reference_action"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert reference_action_sha256(value["reference_action"]) == "sha256:" + hashlib.sha256(encoded).hexdigest()


@pytest.mark.parametrize("path", [(), ("binding",), ("reference_action",), ("reference_action", "lines", 0),
    ("verification",), ("verification", "metadata"), ("timing",), ("decision_window",)])
@pytest.mark.parametrize("operation", ["extra", "missing"])
def test_every_object_is_closed(path, operation):
    value = fixture()
    selected = target(value, path)
    if operation == "extra":
        selected["PRIVATE-MARKER"] = "PRIVATE-MARKER"
    else:
        del selected[next(iter(selected))]
    with pytest.raises(ApprovalObservationError) as caught:
        parse_approval_observation(value)
    assert "PRIVATE-MARKER" not in str(caught.value)


@pytest.mark.parametrize("field,bad", [
    ("run_id", "0" * 31), ("run_id", 1), ("condition", "C2"), ("company_id", True),
    ("executor_user_id", 0), ("scenario_id", "OTHER"), ("document_sha256", "f" * 64),
    ("configuration_sha256", "sha256:" + "a" * 64), ("before_capture_sha256", "f" * 63),
    ("code_commit", "0" * 64), ("host_id", "host/other"), ("clock_id", "clock\nother"),
])
def test_binding_types_and_provenance_cannot_be_silently_normalized(field, bad):
    value = fixture()
    value["binding"][field] = bad
    with pytest.raises(ApprovalObservationError):
        parse_approval_observation(value)


@pytest.mark.parametrize("field,bad", [
    ("action_hash", "sha256:" + "f" * 64), ("approval_sha256", "f" * 64),
    ("nonce_sha256", "sha256:" + "F" * 64), ("command_sha256", None),
    ("key_id", "NOT-A-VERSION"), ("fixture_id", ""), ("scenario_id", "OTHER"),
    ("approver_ref", "SYNTHETIC\u200bAPPROVER"), ("issued_at", "2026-10-01T12:10:00Z"),
    ("expires_at", "2026-10-01T12:00:00Z"), ("issued_at", "2026-02-30T12:00:00Z"),
])
def test_verified_metadata_cannot_be_detached_from_reference_or_valid_registration(field, bad):
    value = fixture()
    value["verification"]["metadata"][field] = bad
    with pytest.raises(ApprovalObservationError):
        parse_approval_observation(value)


@pytest.mark.parametrize("status,reason", [("REJECTED", "SIGNATURE_INVALID"), ("ABSENT", "APPROVAL_ABSENT"),
    ("INDETERMINATE", "DEPENDENCY_UNAVAILABLE")])
def test_non_verified_statuses_have_no_metadata_or_reusable_authority(status, reason):
    value = fixture()
    value["verification"] = {"status": status, "reason_code": reason, "metadata": None}
    assert parse_approval_observation(value) == value


@pytest.mark.parametrize("status,reason,metadata", [
    ("VERIFIED", None, None), ("VERIFIED", "SIGNATURE_INVALID", "valid"),
    ("REJECTED", None, None), ("REJECTED", "PRIVATE-MARKER", None),
    ("ABSENT", "SIGNATURE_INVALID", None), ("REJECTED", "APPROVAL_ABSENT", None),
    ("INDETERMINATE", "DEPENDENCY_UNAVAILABLE", "valid"),
])
def test_status_reason_metadata_coupling_rejects_untrusted_boolean_success(status, reason, metadata):
    value = fixture()
    value["verification"] = {"status": status, "reason_code": reason,
        "metadata": value["verification"]["metadata"] if metadata == "valid" else metadata}
    with pytest.raises(ApprovalObservationError):
        parse_approval_observation(value)


@pytest.mark.parametrize("status,reason", [
    *(("REJECTED", reason) for reason in sorted(INDETERMINATE_REASON_CODES)),
    *(("INDETERMINATE", reason) for reason in sorted(REJECTED_REASON_CODES)),
])
def test_dependency_identity_or_clock_configuration_error_cannot_be_relabelled_as_auth_rejection(status, reason):
    value = fixture()
    value["verification"] = {"status": status, "reason_code": reason, "metadata": None}
    with pytest.raises(ApprovalObservationError):
        parse_approval_observation(value)


@pytest.mark.parametrize("bad", [0, 1, "true", [], {}])
def test_nonce_availability_is_explicit_boolean_or_unknown_not_truthy(bad):
    value = fixture()
    value["nonce_available"] = bad
    with pytest.raises(ApprovalObservationError):
        parse_approval_observation(value)


@pytest.mark.parametrize("field,bad", [("checked_at", None), ("checked_at", "2026-10-01T12:05:00+00:00"),
    ("call_started_at", "2026-10-01T12:05:00"), ("call_finished_at", "2026-02-30T12:00:00Z"),
    ("started_ns", True), ("started_ns", -1), ("finished_ns", 2.0)])
def test_timing_values_must_be_finite_typed_utc_or_nullable_boundaries(field, bad):
    value = fixture()
    value["timing"][field] = bad
    with pytest.raises(ApprovalObservationError):
        parse_approval_observation(value)


def test_temporal_uncertainty_is_preserved_without_becoming_a_parser_approval_decision():
    value = fixture()
    value["timing"]["call_started_at"] = "2026-10-01T12:11:00Z"
    value["timing"]["call_finished_at"] = "2026-10-01T12:04:00Z"
    value["timing"]["started_ns"], value["timing"]["finished_ns"] = 20, 10
    assert parse_approval_observation(value) == value
    value["timing"]["call_started_at"] = value["timing"]["finished_ns"] = None
    assert parse_approval_observation(value) == value


@pytest.mark.parametrize("secret_field", ["key", "key_material", "signature", "nonce", "approval", "authority"])
def test_raw_authority_fields_never_belong_in_sanitized_metadata(secret_field):
    value = fixture()
    value["verification"]["metadata"][secret_field] = "PRIVATE-MARKER"
    with pytest.raises(ApprovalObservationError) as caught:
        parse_approval_observation(value)
    assert "PRIVATE-MARKER" not in str(caught.value)


def test_bounded_snapshot_rejects_custom_objects_cycles_floats_huge_integers_and_deep_collections():
    values = []
    cyclic = {}
    cyclic["cycle"] = cyclic
    values.extend([cyclic, {"v": object()}, {"v": float("nan")}, {"v": 2**10000}, {"v": "A" * 70_000}])
    deep = {}
    for _ in range(15):
        deep = {"v": deep}
    values.append(deep)
    for value in values:
        with pytest.raises(ApprovalObservationError):
            parse_approval_observation(value)


def test_action_hash_helper_is_structural_and_never_replaces_financial_validation():
    value = deepcopy(fixture()["reference_action"])
    value["amount"] = "not-money"
    assert reference_action_sha256(value).startswith("sha256:")
    value["extra"] = "PRIVATE-MARKER"
    with pytest.raises(ApprovalObservationError):
        reference_action_sha256(value)
