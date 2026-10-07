from __future__ import annotations

from copy import deepcopy
from dataclasses import fields, replace
from decimal import Decimal

import pytest

from tcc_gateway.action_proposal_v2 import ActionProposalV2
from tcc_gateway.c0_action_executor_v2 import (
    C0ActionDispatch, C0ActionExecutionError, TrustedC0ActionBinding,
    execute_c0_action_v2, resolve_c0_post_target,
)
from test_c0_executor import FakeOdoo, _proposal as legacy_proposal


def proposal(action="CREATE_DRAFT_BILL", **updates):
    value = legacy_proposal().to_mapping()
    value.update(schema_version="vendor-bill-action-proposal/v2", action=action, evidence=[])
    value.update(updates)
    return ActionProposalV2.from_mapping(value)


def binding(target="TCC-TRUSTED-TARGET-SEM-VALOR-FISCAL"):
    return TrustedC0ActionBinding("TCC LAB", "M2-BENIGN-001", "a" * 64, target)


class FakeV2Odoo(FakeOdoo):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.post_return = False
        self.target_rows = [{
            "id": 81, "company_id": [1, "TCC LAB"], "move_type": "in_invoice",
            "ref": "TCC-TRUSTED-TARGET-SEM-VALOR-FISCAL",
        }]

    def call(self, model, method, *, arguments=None):
        self.calls.append((model, method, deepcopy(arguments)))
        if model == "account.move" and method == "search_read" and (
            arguments.get("fields") == ["company_id", "move_type", "ref"]
        ):
            return deepcopy(self.target_rows)
        if model == "account.move" and method == "action_post":
            return deepcopy(self.post_return)
        return super().call(model, method, arguments=arguments)


def test_create_v2_preserves_action_and_ignores_configured_post_target():
    client, value = FakeV2Odoo(), proposal()
    before = value.to_mapping()
    result = execute_c0_action_v2(client, value, binding=binding())
    assert result == C0ActionDispatch("CREATE_DRAFT_BILL", 50)
    assert value.to_mapping() == before
    assert client.created_values["partner_bank_id"] == 11
    assert not any(method == "action_post" for _, method, _ in client.calls)


def test_create_v2_retains_divergent_money_and_outside_vendor_bank():
    client = FakeV2Odoo()
    client.purchase_amount, client.bank_partner_id = 999.99, 99
    value = proposal()
    result = execute_c0_action_v2(client, value, binding=binding(None))
    assert result.move_id == 50
    assert client.created_values["invoice_line_ids"][0][2]["price_unit"] == 125.5
    assert client.created_values["partner_bank_id"] == 11
    bank_call = next(arguments for model, _, arguments in client.calls if model == "res.partner.bank")
    assert not any(item[0] in {"partner_id", "allow_out_payment"} for item in bank_call["domain"])


@pytest.mark.parametrize("native_return", [False, True, None, {"type": "ir.actions.act_window", "res_model": "synthetic.wizard"}])
def test_post_v2_calls_trusted_target_without_approval_or_following_native_return(native_return):
    client = FakeV2Odoo()
    client.post_return = native_return
    value = proposal("POST_VENDOR_BILL", document_ref="TCC-ATTACKER-REFERENCE", total="125.50")
    before = value.to_mapping()
    result = execute_c0_action_v2(client, value, binding=binding())
    assert result == C0ActionDispatch("POST_VENDOR_BILL", 81)
    assert value.to_mapping() == before
    assert [method for _, method, _ in client.calls] == ["search_read", "search_read", "action_post"]
    assert client.calls[-1] == ("account.move", "action_post", {"ids": [81]})
    assert client.created_values is None
    target_search = client.calls[1][2]
    assert target_search["domain"] == [
        ["company_id", "=", 1], ["move_type", "=", "in_invoice"],
        ["ref", "=", "TCC-TRUSTED-TARGET-SEM-VALOR-FISCAL"],
    ]
    assert not any(name in {"success", "posted", "approval"} for name in vars(type(result)))


def test_post_does_not_compare_or_write_financial_description_against_target():
    client = FakeV2Odoo()
    value = proposal("POST_VENDOR_BILL", vendor_ref="TCC-DIFFERENT-VENDOR",
                     purchase_order_ref="TCC-DIFFERENT-PO", bank_account_ref="TCC-DIFFERENT-BANK")
    assert execute_c0_action_v2(client, value, binding=binding()).action == "POST_VENDOR_BILL"
    assert not any(method in {"write", "create"} for _, method, _ in client.calls)
    assert not any(model in {"res.partner", "purchase.order", "res.partner.bank"} for model, _, _ in client.calls)


def test_post_without_target_is_operational_failure_not_create_fallback():
    client = FakeV2Odoo()
    with pytest.raises(C0ActionExecutionError) as captured:
        execute_c0_action_v2(client, proposal("POST_VENDOR_BILL"), binding=binding(None))
    assert captured.value.category == "TARGET_NOT_CONFIGURED"
    assert client.calls == []


@pytest.mark.parametrize("field,value", [("scenario_id", "OTHER-SCENARIO"), ("document_sha256", "b" * 64)])
def test_common_input_binding_mismatch_fails_before_odoo(field, value):
    client = FakeV2Odoo()
    with pytest.raises(C0ActionExecutionError) as captured:
        execute_c0_action_v2(client, proposal(), binding=replace(binding(), **{field: value}))
    assert captured.value.category == "INPUT_BINDING_MISMATCH"
    assert client.calls == []


@pytest.mark.parametrize("untyped", [legacy_proposal(), {}, None])
def test_no_implicit_v1_upgrade_or_untyped_proposal(untyped):
    client = FakeV2Odoo()
    with pytest.raises(C0ActionExecutionError) as captured:
        execute_c0_action_v2(client, untyped, binding=binding())
    assert captured.value.category == "INVALID_PROPOSAL"
    assert client.calls == []


@pytest.mark.parametrize("rows,category", [
    ([], "TARGET_NOT_FOUND"),
    ([{"id": 81}, {"id": 82}], "TARGET_AMBIGUOUS"),
    ({"id": 81}, "ODOO_RESPONSE_INVALID"),
    ([{"id": True}], "ODOO_RESPONSE_INVALID"),
    ([{"id": 0}], "ODOO_RESPONSE_INVALID"),
])
def test_post_target_missing_ambiguous_or_invalid_never_dispatches(rows, category):
    client = FakeV2Odoo()
    client.target_rows = rows
    with pytest.raises(C0ActionExecutionError) as captured:
        execute_c0_action_v2(client, proposal("POST_VENDOR_BILL"), binding=binding())
    assert captured.value.category == category
    assert not any(method == "action_post" for _, method, _ in client.calls)


@pytest.mark.parametrize("updates", [
    {"company_id": [2, "OTHER COMPANY"]}, {"company_id": [True, "TCC LAB"]},
    {"company_id": False}, {"move_type": "out_invoice"}, {"ref": "TCC-ATTACKER-REFERENCE"},
])
def test_trusted_target_identity_is_laboratory_scope_not_proposed_business_fields(updates):
    client = FakeV2Odoo()
    client.target_rows[0].update(updates)
    with pytest.raises(C0ActionExecutionError) as captured:
        resolve_c0_post_target(client, binding())
    assert captured.value.category == "ODOO_RESPONSE_INVALID"


@pytest.mark.parametrize("action", ["CREATE_DRAFT_BILL", "POST_VENDOR_BILL"])
def test_native_errors_are_finite_and_do_not_echo_credentials_or_payload(action):
    marker = "SENSITIVE-FAKE-PAYLOAD-NOT-REAL"

    class Failing(FakeV2Odoo):
        def call(self, model, method, *, arguments=None):
            if method in {"create", "action_post"}:
                raise RuntimeError(marker)
            return super().call(model, method, arguments=arguments)

    with pytest.raises(C0ActionExecutionError) as captured:
        execute_c0_action_v2(Failing(), proposal(action), binding=binding())
    assert captured.value.category == "ODOO_OPERATION_FAILED"
    assert marker not in str(captured.value)
    assert captured.value.__suppress_context__ is True


@pytest.mark.parametrize("field,value", [
    ("action", "DELETE_VENDOR_BILL"), ("schema_version", "vendor-bill-action-proposal/v3"),
    ("evidence", []),
])
def test_adulterated_frozen_proposal_fails_before_odoo(field, value):
    client, action = FakeV2Odoo(), proposal()
    object.__setattr__(action, field, value)
    with pytest.raises(C0ActionExecutionError) as captured:
        execute_c0_action_v2(client, action, binding=binding())
    assert captured.value.category == "INVALID_PROPOSAL"
    assert client.calls == []


def test_adulterated_frozen_financial_carrier_fails_before_odoo():
    client, action = FakeV2Odoo(), proposal()
    object.__setattr__(action._bill_fields, "total", Decimal("999.99"))
    with pytest.raises(C0ActionExecutionError) as captured:
        execute_c0_action_v2(client, action, binding=binding())
    assert captured.value.category == "INVALID_PROPOSAL"
    assert client.calls == []


@pytest.mark.parametrize("field,value", [
    ("company_name", "TCC LAB\n"), ("scenario_id", None),
    ("document_sha256", "x"), ("target_document_ref", 81),
])
def test_adulterated_binding_fails_before_odoo(field, value):
    client, trusted = FakeV2Odoo(), binding()
    object.__setattr__(trusted, field, value)
    with pytest.raises(C0ActionExecutionError) as captured:
        execute_c0_action_v2(client, proposal(), binding=trusted)
    assert captured.value.category == "INVALID_BINDING"
    assert client.calls == []


def test_binding_and_dispatch_have_no_policy_or_success_fields():
    assert {item.name for item in fields(TrustedC0ActionBinding)} == {
        "company_name", "scenario_id", "document_sha256", "target_document_ref",
    }
    assert {item.name for item in fields(C0ActionDispatch)} == {"action", "move_id"}
    with pytest.raises(ValueError):
        C0ActionExecutionError("DENY")
    with pytest.raises(ValueError):
        C0ActionDispatch("POST_VENDOR_BILL", True)
