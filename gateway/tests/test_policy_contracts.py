from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tcc_gateway.policy_contracts import (
    CAPABILITY_COMMAND_VERSION, POLICY_DECISION_VERSION, POLICY_INPUT_VERSION,
    REASON_RULES, ApprovalFixture, CanonicalAction, CapabilityCommand,
    PolicyContractError, PolicyDecision, PolicyInput, ReasonCode, contract_schema,
)


def action_mapping(post: bool = False) -> dict:
    value = {
        "canonicalization_version": "canon/v1",
        "action_schema_version": "vendor-bill-action-proposal/v2",
        "policy_version": "policy-v1.0.0",
        "action": "POST_VENDOR_BILL" if post else "CREATE_DRAFT_BILL",
        "executor_mode": "POST_APPROVED" if post else "CREATE_DRAFT",
        "scenario_id": "TCC-SCN-001", "document_sha256": "a" * 64,
        "vendor_ref": "TCC-VENDOR-001", "purchase_order_ref": "TCC-PO-001",
        "document_ref": "TCC-NF-001-SEM-VALOR-FISCAL", "invoice_date": "2026-09-30",
        "currency": "BRL", "amount": "125.50", "recipient_bank_ref": "TCC-BANK-001",
        "lines": [{"item_code": "TCC-SERVICE-001", "quantity": "1.00", "unit_price": "125.50"}],
    }
    if post:
        value["target_move_id"] = 42
    return value


def input_mapping(post: bool = False) -> dict:
    action = action_mapping(post)
    return {
        "schema_version": POLICY_INPUT_VERSION, "action": action,
        "evaluated_at": "2026-09-30T12:00:00Z", "expires_at": "2026-09-30T12:10:00Z",
        "trusted_state": {
            "company_ref": "TCC-COMPANY-001", "scenario_id": "TCC-SCN-001",
            "document_sha256": "a" * 64, "phase": "POST_REVIEW" if post else "DRAFT_INTAKE",
            "purchase_order": {
                "purchase_order_ref": "TCC-PO-001", "vendor_ref": "TCC-VENDOR-001",
                "currency": "BRL", "confirmed": True, "amount": "125.50",
                "lines": [{**action["lines"][0], "quantity_to_invoice": "0.00" if post else "1.00"}],
            },
            "allowed_bank_refs": ["TCC-BANK-001"], "duplicate_detected": False,
            "invoice_date_min": "2026-09-01", "invoice_date_max": "2026-10-31",
            "accounting_period_open": True, "monetary_tolerance": "0.00", "quantity_scale": 2,
            "dependencies": {"state": "AVAILABLE", "policy": "AVAILABLE", "audit": "AVAILABLE"},
            "target_bill": {"move_id": 42, "state": "draft", "action": deepcopy(action)} if post else None,
        },
    }


def make_decision(policy_input: PolicyInput) -> PolicyDecision:
    post = policy_input.action.executor_mode == "POST_APPROVED"
    return PolicyDecision.for_input(
        policy_input, decision="REVIEW" if post else "ALLOW",
        reason_codes=(ReasonCode.CRITICAL_ACTION_REQUIRES_APPROVAL if post else ReasonCode.DRAFT_CONSISTENT,),
    )


def make_approval(action: CanonicalAction) -> ApprovalFixture:
    return ApprovalFixture(
        fixture_id="TCC-APR-001", scenario_id=action.scenario_id,
        approver_ref="TCC-APPROVER-FIXTURE-001", canonical_action_hash=action.action_hash,
        nonce="synthetic-nonce-not-a-credential", issued_at="2026-09-30T12:00:01Z",
        expires_at="2026-09-30T12:10:00Z", key_id="synthetic-fixture-v1",
        signature="SYNTHETIC-UNVERIFIED-SIGNATURE-NOT-A-CREDENTIAL",
    )


def make_command(post: bool = False) -> tuple[PolicyInput, CapabilityCommand]:
    policy_input = PolicyInput.from_mapping(input_mapping(post))
    return policy_input, CapabilityCommand(
        policy_input.action, make_decision(policy_input), "sha256:" + "b" * 64,
        make_approval(policy_input.action) if post else None,
    )


@pytest.mark.parametrize("post", [False, True])
def test_contracts_roundtrip_and_explicit_binding(post: bool) -> None:
    policy_input, command = make_command(post)
    assert PolicyInput.from_mapping(policy_input.to_mapping()) == policy_input
    assert PolicyDecision.from_mapping(command.policy_decision.to_mapping()) == command.policy_decision
    assert CapabilityCommand.from_mapping(command.to_mapping()) == command
    command.validate_binding(policy_input)


def test_fixed_canonical_bytes_and_independently_checked_digest_vector() -> None:
    # Digest conferido separadamente com SHA-256 da biblioteca .NET; candidato,
    # ainda sujeito ao aceite e ao freeze. Futuro add-on deve consumir o mesmo vetor.
    vector = json.loads((Path(__file__).parent / "fixtures" / "canonical_action_v1.vector.json").read_text(encoding="utf-8"))
    action = CanonicalAction.from_mapping(vector["action"])
    assert action.canonical_bytes == vector["canonical_utf8"].encode("utf-8")
    assert action.action_hash == vector["canonical_action_hash"]


@pytest.mark.parametrize("version", [POLICY_INPUT_VERSION, POLICY_DECISION_VERSION, CAPABILITY_COMMAND_VERSION])
def test_exported_schema_is_self_contained_closed_and_defensive_copy(version: str) -> None:
    schema = contract_schema(version)
    Draft202012Validator.check_schema(schema)
    assert schema["$ref"].startswith("#/$defs/")
    assert schema["$defs"][schema["$ref"].split("/")[-1]]["additionalProperties"] is False
    schema["$defs"]["canonicalAction"]["properties"]["action"]["enum"].append("DELETE_VENDOR")
    assert "DELETE_VENDOR" not in contract_schema(version)["$defs"]["canonicalAction"]["properties"]["action"]["enum"]


def test_reason_catalog_is_complete_and_has_no_retired_rule() -> None:
    assert set(REASON_RULES) == set(ReasonCode)
    assert {code.value for code in ReasonCode} == set(contract_schema(POLICY_INPUT_VERSION)["$defs"]["reasonCode"]["enum"])
    assert "R-POL-08" not in REASON_RULES.values()
    assert REASON_RULES[ReasonCode.IDEMPOTENCY_CONFLICT] == "R-POL-05"


@pytest.mark.parametrize("field", ["context", "model", "method", "approval", "condition", "attack_family"])
def test_policy_input_rejects_free_fields_and_scenario_labels(field: str) -> None:
    value = input_mapping()
    value[field] = "SENSITIVE-MARKER-NOT-TO-ECHO"
    with pytest.raises(PolicyContractError) as captured:
        PolicyInput.from_mapping(value)
    assert "SENSITIVE-MARKER" not in str(captured.value)


@pytest.mark.parametrize("field", ["monetary_tolerance", "quantity_scale", "invoice_date_min", "invoice_date_max"])
def test_protocol_limits_are_required_not_implicit(field: str) -> None:
    value = input_mapping()
    del value["trusted_state"][field]
    with pytest.raises(PolicyContractError):
        PolicyInput.from_mapping(value)


def test_contract_does_not_evaluate_business_rules_or_repair_model_proposal() -> None:
    value = input_mapping()
    value["action"]["vendor_ref"] = "TCC-DIVERGENT-VENDOR"
    value["action"]["recipient_bank_ref"] = "TCC-DIVERGENT-BANK"
    value["trusted_state"]["dependencies"]["audit"] = "UNAVAILABLE"
    policy_input = PolicyInput.from_mapping(value)
    assert policy_input.action.vendor_ref == "TCC-DIVERGENT-VENDOR"
    assert policy_input.trusted_state.dependencies.audit == "UNAVAILABLE"
    # A decisão será produzida por C1-02. Tipagem não cria aceite de negócio.
    assert not hasattr(policy_input, "authorized")


@pytest.mark.parametrize("field,value", [("scenario_id", "TCC-OTHER-SCENARIO"), ("document_sha256", "b" * 64)])
def test_provenance_binding_does_not_come_from_model(field: str, value: str) -> None:
    mapping = input_mapping()
    mapping["action"][field] = value
    with pytest.raises(PolicyContractError, match="provenance binding"):
        PolicyInput.from_mapping(mapping)


@pytest.mark.parametrize("scale", [3, 4])
def test_quantity_scale_is_explicit_and_matches_all_snapshots(scale: int) -> None:
    value = input_mapping(True)
    value["trusted_state"]["quantity_scale"] = scale
    for lines in (value["action"]["lines"], value["trusted_state"]["purchase_order"]["lines"], value["trusted_state"]["target_bill"]["action"]["lines"]):
        for line in lines:
            line["quantity"] = "1." + "0" * scale
            if "quantity_to_invoice" in line:
                line["quantity_to_invoice"] = "0." + "0" * scale
    PolicyInput.from_mapping(value)
    value["action"]["lines"][0]["quantity"] = "1.00"
    with pytest.raises(PolicyContractError, match="quantity scale"):
        PolicyInput.from_mapping(value)


@pytest.mark.parametrize("change", [
    lambda v: v.update(target_move_id=42),
    lambda v: v.update(executor_mode="POST_APPROVED"),
    lambda v: v.update(action_schema_version="vendor-bill-proposal/v1"),
    lambda v: v.update(amount="126.50"),
    lambda v: v["lines"][0].update(description="DOCUMENT-INSTRUCTION"),
    lambda v: v.update(evidence=[]),
])
def test_canonical_action_rejects_ambiguous_or_unbound_data(change) -> None:
    value = action_mapping()
    change(value)
    with pytest.raises(PolicyContractError):
        CanonicalAction.from_mapping(value)


@pytest.mark.parametrize("target", [True, 42.0, None, 0])
def test_post_target_is_required_strict_positive_integer(target) -> None:
    value = action_mapping(True)
    value["target_move_id"] = target
    with pytest.raises(PolicyContractError):
        CanonicalAction.from_mapping(value)


def test_lines_are_sorted_unique_and_immutable() -> None:
    value = action_mapping()
    value["amount"] = "251.00"
    value["lines"] *= 2
    with pytest.raises(PolicyContractError, match="unique and sorted"):
        CanonicalAction.from_mapping(value)
    value["lines"][0] = {**value["lines"][0], "item_code": "TCC-SERVICE-002"}
    with pytest.raises(PolicyContractError, match="unique and sorted"):
        CanonicalAction.from_mapping(value)
    policy_input = PolicyInput.from_mapping(input_mapping())
    with pytest.raises(FrozenInstanceError):
        policy_input.action.amount = "251.00"
    with pytest.raises(PolicyContractError, match="typed tuple"):
        replace(policy_input.action, lines=list(policy_input.action.lines))
    mutable_copy = policy_input.to_mapping()
    mutable_copy["action"]["lines"][0]["quantity"] = "2.00"
    assert policy_input.action.lines[0].quantity == "1.00"


@pytest.mark.parametrize("field,value", [
    ("vendor_ref", "TCC-VENDOR-002"), ("purchase_order_ref", "TCC-PO-002"),
    ("document_ref", "TCC-NF-002-SEM-VALOR-FISCAL"), ("invoice_date", "2026-10-01"),
    ("currency", "USD"), ("recipient_bank_ref", "TCC-BANK-002"),
    ("policy_version", "policy-v1.0.1"), ("scenario_id", "TCC-SCN-002"),
    ("document_sha256", "c" * 64),
])
def test_command_rejects_changed_preimage_with_previous_decision(field: str, value: str) -> None:
    _, command = make_command()
    mapping = command.to_mapping()
    mapping["action"][field] = value
    with pytest.raises(PolicyContractError, match="command action binding"):
        CapabilityCommand.from_mapping(mapping)


def test_money_line_and_target_changes_also_invalidate_action_hash() -> None:
    _, command = make_command()
    value = command.to_mapping()
    value["action"]["lines"][0]["quantity"] = "2.00"
    value["action"]["amount"] = "251.00"
    with pytest.raises(PolicyContractError, match="command action binding"):
        CapabilityCommand.from_mapping(value)
    _, command = make_command(True)
    value = command.to_mapping()
    value["action"]["target_move_id"] = 43
    with pytest.raises(PolicyContractError, match="command action binding"):
        CapabilityCommand.from_mapping(value)


def test_trusted_context_change_invalidates_decision_without_changing_action_hash() -> None:
    policy_input, command = make_command()
    value = policy_input.to_mapping()
    value["trusted_state"]["company_ref"] = "TCC-COMPANY-002"
    changed = PolicyInput.from_mapping(value)
    assert changed.action.action_hash == policy_input.action.action_hash
    with pytest.raises(PolicyContractError, match="input binding"):
        command.validate_binding(changed)


@pytest.mark.parametrize("field", ["context", "model", "method", "partner_id", "company_id"])
def test_command_has_no_generic_rpc_or_external_context(field: str) -> None:
    _, command = make_command()
    value = command.to_mapping()
    value[field] = "SYNTHETIC-EXTERNAL-ARGUMENT"
    with pytest.raises(PolicyContractError):
        CapabilityCommand.from_mapping(value)


def test_critical_mode_cannot_be_allowed_or_sent_without_approval() -> None:
    policy_input, command = make_command(True)
    with pytest.raises(PolicyContractError, match="executor binding"):
        PolicyDecision.for_input(policy_input, decision="ALLOW", reason_codes=(ReasonCode.DRAFT_CONSISTENT,))
    value = command.to_mapping()
    value.pop("approval")
    with pytest.raises(PolicyContractError):
        CapabilityCommand.from_mapping(value)


def test_denied_decision_cannot_be_a_capability_command() -> None:
    policy_input, command = make_command()
    denied = PolicyDecision.for_input(
        policy_input, decision="DENY", reason_codes=(ReasonCode.BANK_NOT_ALLOWED,), deny_class="POLICY_RULE",
    )
    value = command.to_mapping()
    value["policy_decision"] = denied.to_mapping()
    with pytest.raises(PolicyContractError):
        CapabilityCommand.from_mapping(value)


@pytest.mark.parametrize("deny_class,code", [
    ("POLICY_RULE", ReasonCode.DEPENDENCY_UNAVAILABLE),
    ("FAIL_CLOSED_UNAVAILABILITY", ReasonCode.BANK_NOT_ALLOWED),
    ("POLICY_RULE", ReasonCode.DRAFT_CONSISTENT),
])
def test_deny_class_cannot_disguise_unavailability_or_success(deny_class, code) -> None:
    policy_input = PolicyInput.from_mapping(input_mapping())
    with pytest.raises(PolicyContractError):
        PolicyDecision.for_input(policy_input, decision="DENY", reason_codes=(code,), deny_class=deny_class)


def test_unavailability_is_valid_explicit_deny_and_not_missing() -> None:
    policy_input = PolicyInput.from_mapping(input_mapping())
    denied = PolicyDecision.for_input(
        policy_input, decision="DENY", reason_codes=(ReasonCode.AUDIT_UNAVAILABLE,),
        deny_class="FAIL_CLOSED_UNAVAILABILITY",
    )
    assert denied.to_mapping()["deny_class"] == "FAIL_CLOSED_UNAVAILABILITY"
    assert denied.allowed_executor is None


@pytest.mark.parametrize("field,value", [
    ("scenario_id", "TCC-SCN-002"), ("canonical_action_hash", "sha256:" + "c" * 64),
])
def test_approval_cannot_be_rebound_to_different_action_or_scenario(field: str, value: str) -> None:
    _, command = make_command(True)
    mapping = command.to_mapping()
    mapping["approval"][field] = value
    with pytest.raises(PolicyContractError, match="approval binding"):
        CapabilityCommand.from_mapping(mapping)


def test_approval_structure_is_not_signature_verification_and_does_not_leak_repr() -> None:
    _, command = make_command(True)
    marker = "SYNTHETIC-UNVERIFIED-SIGNATURE-NOT-A-CREDENTIAL"
    assert command.approval.signature == marker
    assert marker not in repr(command)
    assert marker not in repr(command.approval)
    assert not hasattr(command.approval, "signature_valid")
    assert not hasattr(command, "execute")
    value = command.to_mapping()
    value["approval"]["signature"] = marker + "\n"
    with pytest.raises(PolicyContractError) as captured:
        CapabilityCommand.from_mapping(value)
    assert marker not in str(captured.value)


@pytest.mark.parametrize("expires_at", ["2026-09-30T11:59:59Z", "2026-09-30T12:00:00Z", "2026-09-30T12:10:00-03:00"])
def test_input_lifetime_is_ordered_utc_and_supplied(expires_at: str) -> None:
    value = input_mapping()
    value["expires_at"] = expires_at
    with pytest.raises(PolicyContractError):
        PolicyInput.from_mapping(value)


def test_target_snapshot_binds_existing_move_and_provenance() -> None:
    value = input_mapping(True)
    value["trusted_state"]["target_bill"]["move_id"] = 43
    with pytest.raises(PolicyContractError, match="target move binding"):
        PolicyInput.from_mapping(value)
    value = input_mapping(True)
    value["trusted_state"]["target_bill"]["action"]["scenario_id"] = "TCC-SCN-002"
    with pytest.raises(PolicyContractError, match="target provenance"):
        PolicyInput.from_mapping(value)
