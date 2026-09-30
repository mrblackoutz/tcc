from __future__ import annotations

from copy import deepcopy
from decimal import ROUND_DOWN, getcontext, localcontext
import json
from pathlib import Path

import httpx
import pytest

from tcc_gateway.odoo_json2 import OdooJson2Client
from tcc_gateway.policy_contracts import PolicyContractError, PolicyInput, ReasonCode
from tcc_gateway.policy_engine import POLICY_VERSION, evaluate_policy
from tcc_gateway.state import canonical_json_bytes


def input_mapping(post: bool = False) -> dict:
    vector = json.loads((Path(__file__).parent / "fixtures" / "canonical_action_v1.vector.json").read_text(encoding="utf-8"))
    action = vector["action"]
    if post:
        action.update(action="POST_VENDOR_BILL", executor_mode="POST_APPROVED", target_move_id=42)
    return {
        "schema_version": "policy-input/v1", "action": action,
        "evaluated_at": "2026-09-30T12:00:00Z", "expires_at": "2026-09-30T12:10:00Z",
        "trusted_state": {
            "company_ref": "TCC-COMPANY-001", "scenario_id": action["scenario_id"],
            "document_sha256": action["document_sha256"],
            "phase": "POST_REVIEW" if post else "DRAFT_INTAKE",
            "purchase_order": {
                "purchase_order_ref": action["purchase_order_ref"], "vendor_ref": action["vendor_ref"],
                "currency": "BRL", "confirmed": True, "amount": "125.50",
                "lines": [{**line, "quantity_to_invoice": "0.00" if post else "1.00"} for line in action["lines"]],
            },
            "allowed_bank_refs": ["TCC-BANK-001"], "duplicate_detected": False,
            "invoice_date_min": "2026-09-01", "invoice_date_max": "2026-10-31",
            "accounting_period_open": True, "monetary_tolerance": "0.00", "quantity_scale": 2,
            "dependencies": {"state": "AVAILABLE", "policy": "AVAILABLE", "audit": "AVAILABLE"},
            "target_bill": {"move_id": 42, "state": "draft", "action": deepcopy(action)} if post else None,
        },
    }


def evaluate(value: dict):
    return evaluate_policy(PolicyInput.from_mapping(value))


@pytest.mark.parametrize("post,expected,reason,executor", [
    (False, "ALLOW", ReasonCode.DRAFT_CONSISTENT, "create_bill_executor"),
    (True, "REVIEW", ReasonCode.CRITICAL_ACTION_REQUIRES_APPROVAL, "post_bill_executor"),
])
def test_legitimate_actions_have_bound_decisions(post, expected, reason, executor) -> None:
    policy_input = PolicyInput.from_mapping(input_mapping(post))
    result = evaluate_policy(policy_input)
    assert result.decision == expected
    assert result.reason_codes == (reason,)
    assert result.allowed_executor == executor
    assert result.deny_class is None
    assert result.policy_version == POLICY_VERSION
    assert result.proposed_action_hash == policy_input.action.action_hash
    assert result.input_sha256 == policy_input.input_hash
    result.validate_binding(policy_input)


@pytest.mark.parametrize("post", [False, True])
@pytest.mark.parametrize("field,value,code", [
    ("vendor_ref", "TCC-VENDOR-002", ReasonCode.VENDOR_MISMATCH),
    ("purchase_order_ref", "TCC-PO-002", ReasonCode.PURCHASE_ORDER_MISMATCH),
    ("currency", "USD", ReasonCode.CURRENCY_MISMATCH),
    ("recipient_bank_ref", "TCC-BANK-002", ReasonCode.BANK_NOT_ALLOWED),
])
def test_business_arguments_cannot_replace_trusted_po_or_bank(post, field, value, code) -> None:
    mapping = input_mapping(post)
    mapping["action"][field] = value
    result = evaluate(mapping)
    assert result.decision == "DENY"
    assert result.deny_class == "POLICY_RULE"
    assert code in result.reason_codes
    assert result.allowed_executor is None


@pytest.mark.parametrize("post", [False, True])
def test_unconfirmed_po_is_denied(post: bool) -> None:
    value = input_mapping(post)
    value["trusted_state"]["purchase_order"]["confirmed"] = False
    result = evaluate(value)
    assert result.reason_codes == (ReasonCode.PURCHASE_ORDER_NOT_CONFIRMED,)
    assert result.decision == "DENY"


@pytest.mark.parametrize("post", [False, True])
def test_phase_mismatch_is_denied(post: bool) -> None:
    value = input_mapping(post)
    value["trusted_state"]["phase"] = "DRAFT_INTAKE" if post else "POST_REVIEW"
    result = evaluate(value)
    assert result.decision == "DENY"
    assert result.reason_codes == (ReasonCode.PHASE_MISMATCH,)


def test_create_cannot_consume_an_existing_post_target() -> None:
    value = input_mapping()
    value["trusted_state"]["target_bill"] = input_mapping(True)["trusted_state"]["target_bill"]
    assert evaluate(value).reason_codes == (ReasonCode.PHASE_MISMATCH,)


@pytest.mark.parametrize("post", [False, True])
@pytest.mark.parametrize("change", ["item", "quantity", "price"])
def test_line_arguments_must_match_po_even_when_amount_still_matches(post: bool, change: str) -> None:
    value = input_mapping(post)
    line = value["action"]["lines"][0]
    if change == "item":
        line["item_code"] = "TCC-SERVICE-002"
    elif change == "quantity":
        # Mesmo total, quantidade/preço alterados em compensação.
        line.update(quantity="2.00", unit_price="62.75")
    else:
        line.update(quantity="0.50", unit_price="251.00")
    result = evaluate(value)
    assert result.decision == "DENY"
    assert ReasonCode.LINE_MISMATCH in result.reason_codes
    assert ReasonCode.AMOUNT_MISMATCH not in result.reason_codes


def test_changed_price_and_total_cannot_hide_inside_amount_tolerance() -> None:
    value = input_mapping()
    value["action"]["lines"][0]["unit_price"] = "125.51"
    value["action"]["amount"] = "125.51"
    value["trusted_state"]["monetary_tolerance"] = "0.01"
    result = evaluate(value)
    assert result.reason_codes == (ReasonCode.LINE_MISMATCH,)
    assert result.decision == "DENY"


@pytest.mark.parametrize("available,expected", [("0.00", "DENY"), ("0.99", "DENY"), ("1.00", "ALLOW")])
def test_create_requires_sufficient_billable_quantity(available: str, expected: str) -> None:
    value = input_mapping()
    value["trusted_state"]["purchase_order"]["lines"][0]["quantity_to_invoice"] = available
    result = evaluate(value)
    assert result.decision == expected
    if expected == "DENY":
        assert result.reason_codes == (ReasonCode.LINE_MISMATCH,)


def test_post_of_exact_draft_remains_review_when_billable_quantity_is_zero() -> None:
    value = input_mapping(True)
    assert value["trusted_state"]["purchase_order"]["lines"][0]["quantity_to_invoice"] == "0.00"
    result = evaluate(value)
    assert result.decision == "REVIEW"
    assert result.reason_codes == (ReasonCode.CRITICAL_ACTION_REQUIRES_APPROVAL,)


def two_line_mapping(post: bool) -> dict:
    value = input_mapping(post)
    second = {"item_code": "TCC-SERVICE-002", "quantity": "2.00", "unit_price": "37.25"}
    value["action"]["lines"].append(second)
    value["action"]["amount"] = "200.00"
    value["trusted_state"]["purchase_order"]["lines"].append({**second, "quantity_to_invoice": "0.00" if post else "2.00"})
    value["trusted_state"]["purchase_order"]["amount"] = "200.00"
    if post:
        value["trusted_state"]["target_bill"]["action"] = deepcopy(value["action"])
    return value


@pytest.mark.parametrize("post", [False, True])
def test_multiline_legitimate_action_and_missing_item(post: bool) -> None:
    value = two_line_mapping(post)
    assert evaluate(value).decision == ("REVIEW" if post else "ALLOW")
    value["action"]["lines"].pop()
    value["action"]["amount"] = "125.50"
    result = evaluate(value)
    assert result.decision == "DENY"
    assert ReasonCode.LINE_MISMATCH in result.reason_codes


@pytest.mark.parametrize("trusted_amount,tolerance,expected", [
    ("125.50", "0.00", "ALLOW"),
    ("125.51", "0.00", "DENY"),
    ("125.49", "0.00", "DENY"),
    ("125.51", "0.01", "ALLOW"),
    ("125.49", "0.01", "ALLOW"),
    ("125.52", "0.01", "DENY"),
    ("125.48", "0.01", "DENY"),
])
def test_absolute_monetary_tolerance_boundary(trusted_amount: str, tolerance: str, expected: str) -> None:
    # Valores isolam a regra do total; não representam dataset/estado Odoo real.
    value = input_mapping()
    value["trusted_state"]["purchase_order"]["amount"] = trusted_amount
    value["trusted_state"]["monetary_tolerance"] = tolerance
    result = evaluate(value)
    assert result.decision == expected
    if expected == "DENY":
        assert result.reason_codes == (ReasonCode.AMOUNT_MISMATCH,)


@pytest.mark.parametrize("invoice_date,expected", [
    ("2026-08-31", "DENY"), ("2026-09-01", "ALLOW"),
    ("2026-10-31", "ALLOW"), ("2026-11-01", "DENY"),
])
def test_invoice_date_window_includes_both_boundaries(invoice_date: str, expected: str) -> None:
    value = input_mapping()
    value["action"]["invoice_date"] = invoice_date
    result = evaluate(value)
    assert result.decision == expected
    if expected == "DENY":
        assert result.reason_codes == (ReasonCode.DATE_OUTSIDE_WINDOW,)


@pytest.mark.parametrize("post", [False, True])
def test_closed_accounting_period_is_denied(post: bool) -> None:
    value = input_mapping(post)
    value["trusted_state"]["accounting_period_open"] = False
    assert evaluate(value).reason_codes == (ReasonCode.ACCOUNTING_PERIOD_CLOSED,)


@pytest.mark.parametrize("post", [False, True])
def test_duplicate_operation_is_denied_without_authorizing_executor(post: bool) -> None:
    value = input_mapping(post)
    value["trusted_state"]["duplicate_detected"] = True
    result = evaluate(value)
    assert result.decision == "DENY"
    assert result.reason_codes == (ReasonCode.DUPLICATE_DOCUMENT,)
    assert result.allowed_executor is None


def test_alternative_explicitly_allowed_bank_and_empty_allowlist() -> None:
    value = input_mapping()
    value["trusted_state"]["allowed_bank_refs"].append("TCC-BANK-002")
    value["action"]["recipient_bank_ref"] = "TCC-BANK-002"
    assert evaluate(value).decision == "ALLOW"
    value["trusted_state"]["allowed_bank_refs"] = []
    assert evaluate(value).reason_codes == (ReasonCode.BANK_NOT_ALLOWED,)


@pytest.mark.parametrize("target_state", ["posted", "cancel", None])
def test_post_requires_an_existing_draft(target_state) -> None:
    value = input_mapping(True)
    if target_state is None:
        value["trusted_state"]["target_bill"] = None
    else:
        value["trusted_state"]["target_bill"]["state"] = target_state
    result = evaluate(value)
    assert result.decision == "DENY"
    assert result.reason_codes == (ReasonCode.TARGET_BILL_MISMATCH,)


@pytest.mark.parametrize("field,new_value", [
    ("target_move_id", 43), ("vendor_ref", "TCC-VENDOR-002"),
    ("purchase_order_ref", "TCC-PO-002"), ("document_ref", "TCC-NF-002-SEM-VALOR-FISCAL"),
    ("invoice_date", "2026-10-01"), ("currency", "USD"),
    ("recipient_bank_ref", "TCC-BANK-002"), ("policy_version", "policy-v1.0.1"),
])
def test_post_compares_full_target_preimage_not_only_amount(field, new_value) -> None:
    value = input_mapping(True)
    target = value["trusted_state"]["target_bill"]
    target["action"][field] = new_value
    if field == "target_move_id":
        target["move_id"] = new_value
    result = evaluate(value)
    assert result.decision == "DENY"
    assert result.reason_codes == (ReasonCode.TARGET_BILL_MISMATCH,)


def test_post_draft_line_or_amount_difference_requires_exact_binding() -> None:
    value = input_mapping(True)
    target = value["trusted_state"]["target_bill"]["action"]
    target["lines"][0]["unit_price"] = "125.51"
    target["amount"] = "125.51"
    value["trusted_state"]["monetary_tolerance"] = "0.01"
    assert evaluate(value).reason_codes == (ReasonCode.TARGET_BILL_MISMATCH,)


@pytest.mark.parametrize("post", [False, True])
@pytest.mark.parametrize("dependency,code", [
    ("state", ReasonCode.DEPENDENCY_UNAVAILABLE),
    ("policy", ReasonCode.POLICY_UNAVAILABLE), ("audit", ReasonCode.AUDIT_UNAVAILABLE),
])
def test_unavailability_has_its_own_deny_class(post, dependency, code) -> None:
    value = input_mapping(post)
    value["trusted_state"]["dependencies"][dependency] = "UNAVAILABLE"
    # A indisponibilidade prevalece, ainda que haja violação de negócio.
    value["action"]["recipient_bank_ref"] = "TCC-BANK-002"
    result = evaluate(value)
    assert result.decision == "DENY"
    assert result.reason_codes == (code,)
    assert result.deny_class == "FAIL_CLOSED_UNAVAILABILITY"
    assert result.allowed_executor is None


def test_multiple_unavailable_dependencies_are_recorded_in_fixed_order() -> None:
    value = input_mapping()
    value["trusted_state"]["dependencies"] = dict.fromkeys(["state", "policy", "audit"], "UNAVAILABLE")
    assert evaluate(value).reason_codes == (
        ReasonCode.DEPENDENCY_UNAVAILABLE, ReasonCode.POLICY_UNAVAILABLE, ReasonCode.AUDIT_UNAVAILABLE,
    )


def test_all_business_failures_are_unique_ordered_and_bound_to_input() -> None:
    value = input_mapping(True)
    state = value["trusted_state"]
    state.update(phase="DRAFT_INTAKE", duplicate_detected=True, target_bill=None, accounting_period_open=False)
    state["purchase_order"].update(confirmed=False, amount="126.50")
    value["action"].update(
        vendor_ref="TCC-VENDOR-002", purchase_order_ref="TCC-PO-002", currency="USD",
        recipient_bank_ref="TCC-BANK-002", invoice_date="2026-11-01",
    )
    value["action"]["lines"][0]["item_code"] = "TCC-SERVICE-002"
    policy_input = PolicyInput.from_mapping(value)
    result = evaluate_policy(policy_input)
    assert result.reason_codes == (
        ReasonCode.PHASE_MISMATCH, ReasonCode.PURCHASE_ORDER_NOT_CONFIRMED,
        ReasonCode.VENDOR_MISMATCH, ReasonCode.PURCHASE_ORDER_MISMATCH,
        ReasonCode.CURRENCY_MISMATCH, ReasonCode.LINE_MISMATCH, ReasonCode.AMOUNT_MISMATCH,
        ReasonCode.BANK_NOT_ALLOWED, ReasonCode.DUPLICATE_DOCUMENT, ReasonCode.TARGET_BILL_MISMATCH,
        ReasonCode.DATE_OUTSIDE_WINDOW, ReasonCode.ACCOUNTING_PERIOD_CLOSED,
    )
    assert result.deny_class == "POLICY_RULE"
    result.validate_binding(policy_input)


def test_no_ground_truth_label_is_invented_for_new_reference_or_in_window_date() -> None:
    value = input_mapping()
    value["action"].update(document_ref="TCC-NF-002-SEM-VALOR-FISCAL", invoice_date="2026-10-01")
    assert evaluate(value).decision == "ALLOW"


@pytest.mark.parametrize("extra", ["approval", "attack_family", "condition", "expected_action", "context", "model", "method"])
def test_external_labels_or_authorization_claims_cannot_enter_policy_input(extra: str) -> None:
    value = input_mapping(True)
    value[extra] = "SENSITIVE-MARKER-NOT-TO-ECHO"
    with pytest.raises(PolicyContractError) as captured:
        evaluate(value)
    assert "SENSITIVE-MARKER" not in str(captured.value)


@pytest.mark.parametrize("invalid", [None, {}, "SENSITIVE-MARKER-NOT-TO-ECHO"])
def test_engine_rejects_untyped_input_without_fabricating_decision(invalid) -> None:
    with pytest.raises(PolicyContractError, match="typed input") as captured:
        evaluate_policy(invalid)
    assert "SENSITIVE-MARKER" not in str(captured.value)


def test_unknown_policy_implementation_version_is_not_misreported() -> None:
    value = input_mapping()
    value["action"]["policy_version"] = "policy-v9.0.0"
    with pytest.raises(PolicyContractError, match="implementation version"):
        evaluate(value)


@pytest.mark.parametrize("field,invalid", [
    ("duplicate_detected", "false"), ("quantity_scale", True), ("purchase_order", None),
])
def test_engine_revalidates_fault_injected_frozen_objects(field, invalid) -> None:
    policy_input = PolicyInput.from_mapping(input_mapping())
    object.__setattr__(policy_input.trusted_state, field, invalid)
    with pytest.raises(PolicyContractError):
        evaluate_policy(policy_input)


@pytest.mark.parametrize("trusted_amount,expected", [("999999999999.98", "ALLOW"), ("999999999999.97", "DENY")])
def test_decimal_limits_do_not_inherit_low_precision_or_rounding(trusted_amount: str, expected: str) -> None:
    value = input_mapping()
    value["action"]["amount"] = "999999999999.99"
    value["action"]["lines"][0]["unit_price"] = "999999999999.99"
    value["trusted_state"]["purchase_order"]["lines"][0]["unit_price"] = "999999999999.99"
    value["trusted_state"]["purchase_order"]["amount"] = trusted_amount
    value["trusted_state"]["monetary_tolerance"] = "0.01"
    policy_input = PolicyInput.from_mapping(value)
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        before = getcontext().copy()
        result = evaluate_policy(policy_input)
        assert result.decision == expected
        assert getcontext().prec == before.prec
        assert getcontext().rounding == before.rounding
        assert getcontext().flags == before.flags


def test_engine_is_deterministic_preserves_input_and_uses_no_external_io(monkeypatch) -> None:
    policy_input = PolicyInput.from_mapping(input_mapping(True))
    before = canonical_json_bytes(policy_input.to_mapping())

    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected external operation")

    monkeypatch.setattr(httpx.Client, "request", forbidden)
    monkeypatch.setattr(OdooJson2Client, "call", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr("time.time", forbidden)
    outputs = [canonical_json_bytes(evaluate_policy(policy_input).to_mapping()) for _ in range(3)]
    assert outputs[0] == outputs[1] == outputs[2]
    assert canonical_json_bytes(policy_input.to_mapping()) == before
