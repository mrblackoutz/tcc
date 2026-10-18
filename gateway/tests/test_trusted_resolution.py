"""C1-03: chaves confiaveis, leitura sem efeitos e snapshot nao reparado.

Todas as referencias e descricoes deste arquivo sao sinteticas, sem valor fiscal.
O fake aplica os dominios antes de projetar os campos como search_read do Odoo.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from typing import Any

import httpx
import pytest

from tcc_gateway.action_proposal_v2 import ActionProposalV2, normalise_action_model_output
from tcc_gateway.config import OdooConfig
from tcc_gateway.odoo_json2 import OdooJson2Client
from tcc_gateway.pdf_ingestion import ExtractedPdf
from tcc_gateway.policy_contracts import DependencyStatus, ReasonCode
from tcc_gateway.policy_engine import POLICY_VERSION, evaluate_policy
from tcc_gateway.trusted_resolution import (
    CanonicalizationError,
    TrustedBindingError,
    TrustedOperationalStatus,
    TrustedStateResolutionError,
    TrustedWorkflow,
    prepare_policy_input,
    read_trusted_state,
)


COMPANY_NAME = "TCC LAB SEM VALOR FISCAL"
COMPANY_REF = "TCC-COMPANY-001"
SCENARIO_ID = "SCN-001"
DOCUMENT_SHA256 = "a" * 64
DOCUMENT_REF = "TCC-NF-001-SEM-VALOR-FISCAL"
PO_REF = "TCC-PO-001"


def _workflow(*, post: bool = False, **changes: Any) -> TrustedWorkflow:
    value = {
        "company_name": COMPANY_NAME,
        "company_ref": COMPANY_REF,
        "scenario_id": SCENARIO_ID,
        "document_sha256": DOCUMENT_SHA256,
        "purchase_order_ref": PO_REF,
        "phase": "POST_REVIEW" if post else "DRAFT_INTAKE",
        "allowed_bank_refs": ("TCC-BANK-001",),
        "invoice_date_min": "2026-09-01",
        "invoice_date_max": "2026-10-31",
        "monetary_tolerance": "0.00",
        "quantity_scale": 2,
        "target_document_ref": DOCUMENT_REF if post else None,
    }
    value.update(changes)
    return TrustedWorkflow(**value)


def _operational(**changes: Any) -> TrustedOperationalStatus:
    value = {
        "company_ref": COMPANY_REF,
        "scenario_id": SCENARIO_ID,
        "document_sha256": DOCUMENT_SHA256,
        "purchase_order_ref": PO_REF,
        "duplicate_detected": False,
        "accounting_period_open": True,
        "dependencies": DependencyStatus("AVAILABLE", "AVAILABLE", "AVAILABLE"),
    }
    value.update(changes)
    return TrustedOperationalStatus(**value)


def _proposal(*, post: bool = False, **changes: Any) -> ActionProposalV2:
    value = {
        "action": "POST_VENDOR_BILL" if post else "CREATE_DRAFT_BILL",
        "vendor_ref": "TCC-VENDOR-001",
        "purchase_order_ref": PO_REF,
        "document_ref": DOCUMENT_REF,
        "invoice_date": "2026-09-30",
        "currency": "BRL",
        "bank_account_ref": "TCC-BANK-001",
        "lines": [{
            "item_code": "TCC-SERVICE-001",
            "description": "DESCRICAO DO DOCUMENTO SEM VALOR FISCAL",
            "quantity": "1.00",
            "unit_price": "125.50",
            "line_total": "125.50",
        }],
        "total": "125.50",
    }
    value.update(changes)
    return normalise_action_model_output(
        value, producer="deterministic-development/v1", scenario_id=SCENARIO_ID,
        document=ExtractedPdf(
            text="DOCUMENTO SINTETICO SEM VALOR FISCAL", document_sha256=DOCUMENT_SHA256,
            text_sha256="b" * 64, page_count=1, byte_count=100,
        ),
    )


def _many2one(record_id: int, label: str = "NOME SINTETICO SEM AUTORIDADE") -> list[Any]:
    return [record_id, label]


def _domain_matches(record: dict[str, Any], domain: list[Any]) -> bool:
    """Subset de dominios Odoo usado por consultas confiaveis destes testes."""
    terms = iter(domain)

    def evaluate(term: Any) -> bool:
        if term == "&":
            left = evaluate(next(terms))
            right = evaluate(next(terms))
            return left and right
        if term == "|":
            left = evaluate(next(terms))
            right = evaluate(next(terms))
            return left or right
        if term == "!":
            return not evaluate(next(terms))
        field, operator, expected = term
        actual = record[field]
        if isinstance(actual, list) and field.endswith("_id"):
            actual = actual[0]
        if operator == "=":
            return actual == expected
        if operator == "!=":
            return actual != expected
        if operator == "in":
            return actual in expected
        if operator == "not in":
            return actual not in expected
        raise AssertionError("operator outside read-only fake contract")

    results = [evaluate(term) for term in terms]
    return all(results)


class FakeOdoo:
    def __init__(self, *, post: bool = False) -> None:
        company = _many2one(1, COMPANY_NAME)
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.response_overrides: dict[str, Any] = {}
        self.fail_model: str | None = None
        self.records: dict[str, list[dict[str, Any]]] = {
            "res.company": [{"id": 1, "name": COMPANY_NAME}],
            "purchase.order": [{
                "id": 20, "name": PO_REF, "company_id": company,
                "partner_id": _many2one(10), "currency_id": _many2one(2),
                "state": "purchase", "amount_total": 125.5,
            }],
            "res.partner": [
                {"id": 10, "ref": "TCC-VENDOR-001", "company_id": company,
                 "active": True, "supplier_rank": 1},
                {"id": 12, "ref": "TCC-VENDOR-002", "company_id": company,
                 "active": True, "supplier_rank": 1},
            ],
            "res.currency": [{"id": 2, "name": "BRL"}, {"id": 3, "name": "USD"}],
            "purchase.order.line": [{
                "id": 40, "order_id": _many2one(20), "company_id": company,
                "product_id": _many2one(30), "product_uom_id": _many2one(31),
                "display_type": False, "name": "SERVICO CONFIAVEL SEM VALOR FISCAL",
                "product_qty": 1.0, "price_unit": 125.5,
                "qty_to_invoice": 0.0 if post else 1.0, "tax_ids": [], "discount": 0.0,
            }],
            "product.product": [{
                "id": 30, "default_code": "TCC-SERVICE-001", "company_id": False,
                "active": True, "uom_id": _many2one(31),
            }],
            "res.partner.bank": [
                {"id": 11, "acc_number": "TCC-BANK-001", "company_id": company,
                 "partner_id": _many2one(10), "active": True, "allow_out_payment": True},
                {"id": 13, "acc_number": "TCC-BANK-002", "company_id": company,
                 "partner_id": _many2one(12), "active": True, "allow_out_payment": True},
            ],
            "account.move": [{
                "id": 42, "company_id": company, "move_type": "in_invoice", "state": "draft",
                "partner_id": _many2one(10), "currency_id": _many2one(2),
                "partner_bank_id": _many2one(11), "invoice_date": "2026-09-30",
                "ref": DOCUMENT_REF, "invoice_origin": PO_REF, "amount_total": 125.5,
                "auto_post": "no", "invoice_line_ids": [51],
            }] if post else [],
            "account.move.line": [{
                "id": 51, "move_id": _many2one(42), "company_id": company,
                "display_type": "product", "product_id": _many2one(30),
                "purchase_line_id": _many2one(40), "product_uom_id": _many2one(31),
                "quantity": 1.0, "price_unit": 125.5, "discount": 0.0, "tax_ids": [],
            }] if post else [],
        }

    def call(self, model: str, method: str, *, arguments: dict[str, Any] | None = None) -> Any:
        assert method == "search_read", "C1-03 must never invoke mutation or arbitrary methods"
        assert arguments is not None and "context" not in arguments
        self.calls.append((model, method, deepcopy(arguments)))
        if model == self.fail_model:
            raise RuntimeError("RAW-TRANSPORT-MARKER-NOT-FOR-LOGS")
        if model in self.response_overrides:
            return deepcopy(self.response_overrides[model])
        selected = [row for row in self.records[model] if _domain_matches(row, arguments["domain"])]
        if arguments.get("limit"):
            selected = selected[:arguments["limit"]]
        return [
            {field: deepcopy(row[field]) for field in {"id", *arguments["fields"]}}
            for row in selected
        ]


def _read(client: FakeOdoo, *, post: bool = False, workflow=None, operational=None):
    return read_trusted_state(
        client, workflow or _workflow(post=post), operational or _operational(),
        policy_version=POLICY_VERSION,
    )


def _prepare(proposal: ActionProposalV2, resolved):
    return prepare_policy_input(
        proposal, resolved, policy_version=POLICY_VERSION,
        evaluated_at="2026-09-30T12:00:00Z", expires_at="2026-09-30T12:01:00Z",
    )


def test_resolves_trusted_po_lines_bank_and_description_without_effects() -> None:
    client = FakeOdoo()
    resolved = _read(client)
    state = resolved.state
    assert (resolved.company_id, resolved.vendor_id, resolved.purchase_order_id) == (1, 10, 20)
    assert state.company_ref == COMPANY_REF
    assert (state.scenario_id, state.document_sha256) == (SCENARIO_ID, DOCUMENT_SHA256)
    assert state.purchase_order.purchase_order_ref == PO_REF
    assert state.purchase_order.vendor_ref == "TCC-VENDOR-001"
    assert state.purchase_order.currency == "BRL"
    assert state.purchase_order.amount == "125.50"
    assert state.purchase_order.lines[0].quantity_to_invoice == "1.00"
    assert state.allowed_bank_refs == ("TCC-BANK-001",)
    assert resolved.bank_ids == (("TCC-BANK-001", 11),)
    line = resolved.lines[0]
    assert (line.item_code, line.purchase_line_id, line.product_id, line.uom_id) == (
        "TCC-SERVICE-001", 40, 30, 31,
    )
    assert line.description == "SERVICO CONFIAVEL SEM VALOR FISCAL"
    assert state.target_bill is None
    assert evaluate_policy(_prepare(_proposal(), resolved)).decision == "ALLOW"
    assert all(method == "search_read" for _, method, _ in client.calls)


@pytest.mark.parametrize("post", [False, True])
@pytest.mark.parametrize("field,value,expected_code", [
    ("vendor_ref", "TCC-VENDOR-002", ReasonCode.VENDOR_MISMATCH),
    ("purchase_order_ref", "TCC-PO-002", ReasonCode.PURCHASE_ORDER_MISMATCH),
    ("bank_account_ref", "TCC-BANK-002", ReasonCode.BANK_NOT_ALLOWED),
    ("currency", "USD", ReasonCode.CURRENCY_MISMATCH),
])
def test_adversarial_proposal_cannot_change_trusted_queries_or_snapshot(post, field, value, expected_code) -> None:
    first_client, second_client = FakeOdoo(post=post), FakeOdoo(post=post)
    first = _read(first_client, post=post)
    second = _read(second_client, post=post)
    benign_input = _prepare(_proposal(post=post), first)
    adversarial_input = _prepare(_proposal(post=post, **{field: value}), second)
    assert first == second
    assert first_client.calls == second_client.calls
    assert benign_input.trusted_state == adversarial_input.trusted_state
    decision = evaluate_policy(adversarial_input)
    assert decision.decision == "DENY"
    assert expected_code in decision.reason_codes
    assert adversarial_input.action.to_mapping()[{
        "bank_account_ref": "recipient_bank_ref",
    }.get(field, field)] == value


def test_altered_amount_is_preserved_and_denied_not_repaired() -> None:
    resolved = _read(FakeOdoo())
    lines = _proposal().to_mapping()["lines"]
    lines[0].update(unit_price="126.50", line_total="126.50")
    value = _prepare(_proposal(lines=lines, total="126.50"), resolved)
    assert value.action.amount == "126.50"
    assert value.trusted_state.purchase_order.amount == "125.50"
    decision = evaluate_policy(value)
    assert {ReasonCode.LINE_MISMATCH, ReasonCode.AMOUNT_MISMATCH} <= set(decision.reason_codes)


def test_post_target_is_reconstructed_from_odoo_and_uses_trusted_target_id() -> None:
    resolved = _read(FakeOdoo(post=True), post=True)
    target = resolved.state.target_bill
    assert target is not None
    assert target.move_id == target.action.target_move_id == 42
    assert target.action.action == "POST_VENDOR_BILL"
    assert target.action.document_ref == DOCUMENT_REF
    assert target.action.amount == "125.50"
    assert resolved.state.purchase_order.lines[0].quantity_to_invoice == "0.00"
    policy_input = _prepare(_proposal(post=True), resolved)
    assert policy_input.action.action_hash == target.action.action_hash
    assert evaluate_policy(policy_input).decision == "REVIEW"


@pytest.mark.parametrize("field,value", [
    ("invoice_date", "2026-10-01"),
    ("partner_id", _many2one(12)),
    ("currency_id", _many2one(3)),
    ("partner_bank_id", _many2one(13)),
])
def test_target_snapshot_never_copies_proposed_fields(field, value) -> None:
    client = FakeOdoo(post=True)
    client.records["account.move"][0][field] = value
    try:
        resolved = _read(client, post=True)
    except TrustedStateResolutionError as error:
        # Uma relacao inconsistente pode impedir a formacao do snapshot,
        # mas jamais pode ser substituida pelos argumentos do modelo.
        assert error.category in {"STATE_INVALID", "REFERENCE_NOT_FOUND"}
        return
    policy_input = _prepare(_proposal(post=True), resolved)
    assert resolved.state.target_bill.action.action_hash != policy_input.action.action_hash
    decision = evaluate_policy(policy_input)
    assert decision.decision == "DENY"
    assert ReasonCode.TARGET_BILL_MISMATCH in decision.reason_codes


def test_target_amount_and_line_price_are_read_not_filled_from_model_or_po() -> None:
    client = FakeOdoo(post=True)
    client.records["account.move"][0]["amount_total"] = 126.5
    client.records["account.move.line"][0]["price_unit"] = 126.5
    resolved = _read(client, post=True)
    assert resolved.state.target_bill.action.amount == "126.50"
    assert resolved.state.target_bill.action.lines[0].unit_price == "126.50"
    value = _prepare(_proposal(post=True), resolved)
    assert value.action.amount == "125.50"
    assert ReasonCode.TARGET_BILL_MISMATCH in evaluate_policy(value).reason_codes


@pytest.mark.parametrize("state", ["posted", "cancel"])
def test_existing_non_draft_target_is_denied_without_fabricating_a_draft(state) -> None:
    client = FakeOdoo(post=True)
    client.records["account.move"][0]["state"] = state
    resolved = _read(client, post=True)
    assert resolved.state.target_bill.state == state
    decision = evaluate_policy(_prepare(_proposal(post=True), resolved))
    assert decision.decision == "DENY"
    assert ReasonCode.TARGET_BILL_MISMATCH in decision.reason_codes


def test_post_proposal_without_resolved_target_cannot_be_demoted_or_get_fake_id() -> None:
    resolved = _read(FakeOdoo())
    with pytest.raises(CanonicalizationError):
        _prepare(_proposal(post=True), resolved)
    assert resolved.state.phase == "DRAFT_INTAKE"
    assert resolved.state.target_bill is None


@pytest.mark.parametrize("model", ["res.company", "purchase.order", "res.partner", "res.currency", "product.product"])
def test_required_unique_reference_missing_is_classified(model) -> None:
    client = FakeOdoo()
    client.records[model] = []
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client)
    assert caught.value.category == "REFERENCE_NOT_FOUND"


@pytest.mark.parametrize("model", ["res.company", "purchase.order", "res.partner", "res.currency", "product.product", "account.move"])
def test_duplicate_unique_reference_is_classified(model) -> None:
    client = FakeOdoo(post=model == "account.move")
    original = deepcopy(client.records[model][0])
    duplicate = deepcopy(original)
    duplicate["id"] = 999
    # Simula resposta anomala que viola inclusive filtro por ID.
    client.response_overrides[model] = [original, duplicate]
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client, post=model == "account.move")
    assert caught.value.category == "REFERENCE_AMBIGUOUS"


@pytest.mark.parametrize("bad_id", [True, False, 0, -1, "20", None])
def test_record_ids_are_strict_positive_integers(bad_id) -> None:
    client = FakeOdoo()
    row = deepcopy(client.records["purchase.order"][0])
    row["id"] = bad_id
    client.response_overrides["purchase.order"] = [row]
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client)
    assert caught.value.category == "STATE_INVALID"


@pytest.mark.parametrize("bad_relation", [True, 10, "10", [], [True, "LABEL"], [0, "LABEL"], [10], [10, "LABEL", "EXTRA"]])
def test_many2one_shape_cannot_supply_unvalidated_internal_ids(bad_relation) -> None:
    client = FakeOdoo()
    client.records["purchase.order"][0]["partner_id"] = bad_relation
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client)
    assert caught.value.category == "STATE_INVALID"


@pytest.mark.parametrize("model", ["purchase.order", "res.partner", "purchase.order.line", "account.move", "account.move.line"])
def test_returned_foreign_company_record_is_rejected_even_if_transport_ignores_domain(model) -> None:
    client = FakeOdoo(post=model.startswith("account."))
    row = deepcopy(client.records[model][0])
    row["company_id"] = _many2one(99, "FOREIGN SYNTHETIC COMPANY")
    client.response_overrides[model] = [row]
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client, post=model.startswith("account."))
    assert caught.value.category == "STATE_INVALID"


@pytest.mark.parametrize("field,value", [
    ("purchase_line_id", _many2one(999)),
    ("product_id", _many2one(999)),
    ("product_uom_id", _many2one(999)),
    ("tax_ids", [999]),
    ("discount", 10.0),
])
def test_target_lines_must_be_tied_to_trusted_po_and_untaxed_undiscounted(field, value) -> None:
    client = FakeOdoo(post=True)
    client.records["account.move.line"][0][field] = value
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client, post=True)
    assert caught.value.category == "STATE_INVALID"


@pytest.mark.parametrize("field,value", [
    ("active", False), ("allow_out_payment", False), ("partner_id", _many2one(12)),
])
def test_bank_trust_loss_cannot_leave_reference_allowed(field, value) -> None:
    client = FakeOdoo()
    client.records["res.partner.bank"][0][field] = value
    try:
        resolved = _read(client)
    except TrustedStateResolutionError as error:
        assert error.category in {"STATE_INVALID", "REFERENCE_NOT_FOUND"}
        return
    assert "TCC-BANK-001" not in resolved.state.allowed_bank_refs
    assert ReasonCode.BANK_NOT_ALLOWED in evaluate_policy(_prepare(_proposal(), resolved)).reason_codes


def test_odoo_bank_flag_alone_does_not_expand_explicit_workflow_allowlist() -> None:
    client = FakeOdoo()
    client.records["res.partner.bank"][1]["partner_id"] = _many2one(10)
    resolved = _read(client)
    assert resolved.state.allowed_bank_refs == ("TCC-BANK-001",)
    assert resolved.bank_ids == (("TCC-BANK-001", 11),)


@pytest.mark.parametrize("model,field", [
    ("purchase.order", "amount_total"),
    ("purchase.order.line", "product_qty"),
    ("purchase.order.line", "price_unit"),
    ("purchase.order.line", "qty_to_invoice"),
])
@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), float("-inf"), -1.0])
def test_invalid_odoo_numeric_values_are_rejected(model, field, value) -> None:
    client = FakeOdoo()
    client.records[model][0][field] = value
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client)
    assert caught.value.category == "STATE_INVALID"


@pytest.mark.parametrize("field,value", [("product_qty", 1.001), ("price_unit", 125.501), ("qty_to_invoice", 1.001)])
def test_odoo_values_cannot_be_silently_rounded_to_protocol_scale(field, value) -> None:
    client = FakeOdoo()
    client.records["purchase.order.line"][0][field] = value
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client)
    assert caught.value.category == "STATE_INVALID"


@pytest.mark.parametrize("field,value", [
    ("company_ref", "TCC-COMPANY-002"), ("scenario_id", "SCN-002"),
    ("document_sha256", "c" * 64), ("purchase_order_ref", "TCC-PO-002"),
])
def test_operational_observation_requires_exact_workflow_provenance(field, value) -> None:
    client = FakeOdoo()
    with pytest.raises((TrustedStateResolutionError, ValueError)):
        _read(client, operational=_operational(**{field: value}))
    assert client.calls == [], "unbound operational status must fail before I/O"


def test_operational_status_is_explicit_not_derived_from_presence_of_post_target() -> None:
    resolved = _read(FakeOdoo(post=True), post=True, operational=_operational(duplicate_detected=True))
    assert resolved.state.duplicate_detected is True
    assert ReasonCode.DUPLICATE_DOCUMENT in evaluate_policy(_prepare(_proposal(post=True), resolved)).reason_codes
    closed_period = _read(FakeOdoo(), operational=_operational(accounting_period_open=False))
    assert ReasonCode.ACCOUNTING_PERIOD_CLOSED in evaluate_policy(_prepare(_proposal(), closed_period)).reason_codes


def test_operational_dependency_status_is_preserved_not_fabricated_available() -> None:
    resolved = _read(FakeOdoo(), operational=_operational(
        dependencies=DependencyStatus("AVAILABLE", "AVAILABLE", "UNAVAILABLE"),
    ))
    decision = evaluate_policy(_prepare(_proposal(), resolved))
    assert decision.decision == "DENY"
    assert decision.deny_class == "FAIL_CLOSED_UNAVAILABILITY"
    assert decision.reason_codes == (ReasonCode.AUDIT_UNAVAILABLE,)


def test_transport_failure_is_classified_without_echoing_raw_error() -> None:
    client = FakeOdoo()
    client.fail_model = "purchase.order"
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client)
    assert caught.value.category == "DEPENDENCY_UNAVAILABLE"
    assert "RAW-TRANSPORT-MARKER" not in str(caught.value)
    assert caught.value.__suppress_context__ is True


def test_snapshots_and_workflow_are_immutable() -> None:
    workflow = _workflow()
    resolved = _read(FakeOdoo(), workflow=workflow)
    with pytest.raises(FrozenInstanceError):
        workflow.quantity_scale = 4
    with pytest.raises(FrozenInstanceError):
        resolved.company_id = 99
    with pytest.raises(FrozenInstanceError):
        resolved.lines[0].description = "ATTACKER-CONTROLLED"


def test_proposal_provenance_cannot_be_rebound_to_trusted_snapshot() -> None:
    resolved = _read(FakeOdoo())
    value = _proposal().to_mapping()
    value["scenario_id"] = "SCN-002"
    proposal = ActionProposalV2.from_mapping(value)
    with pytest.raises((CanonicalizationError, ValueError)):
        _prepare(proposal, resolved)


def test_po_state_not_confirmed_is_observed_for_policy_denial() -> None:
    client = FakeOdoo()
    client.records["purchase.order"][0]["state"] = "draft"
    resolved = _read(client)
    assert resolved.state.purchase_order.confirmed is False
    assert ReasonCode.PURCHASE_ORDER_NOT_CONFIRMED in evaluate_policy(_prepare(_proposal(), resolved)).reason_codes


def test_create_with_insufficient_quantity_keeps_actual_available_quantity() -> None:
    client = FakeOdoo()
    client.records["purchase.order.line"][0]["qty_to_invoice"] = 0.0
    resolved = _read(client)
    assert resolved.state.purchase_order.lines[0].quantity_to_invoice == "0.00"
    assert ReasonCode.LINE_MISMATCH in evaluate_policy(_prepare(_proposal(), resolved)).reason_codes


def test_multiple_po_lines_are_sorted_and_resolve_without_model_item_lookup() -> None:
    client = FakeOdoo()
    first = client.records["purchase.order.line"][0]
    first.update(product_qty=1.0, price_unit=100.0)
    second = deepcopy(first)
    second.update(id=41, product_id=_many2one(32), price_unit=25.5,
                  name="SEGUNDO SERVICO CONFIAVEL SEM VALOR FISCAL")
    client.records["purchase.order.line"] = [second, first]
    client.records["product.product"].append({
        "id": 32, "default_code": "TCC-SERVICE-002", "company_id": False,
        "active": True, "uom_id": _many2one(31),
    })
    resolved = _read(client)
    assert tuple(line.item_code for line in resolved.state.purchase_order.lines) == (
        "TCC-SERVICE-001", "TCC-SERVICE-002",
    )
    assert tuple(line.item_code for line in resolved.lines) == (
        "TCC-SERVICE-001", "TCC-SERVICE-002",
    )


def test_duplicate_item_codes_in_po_are_rejected_not_merged() -> None:
    client = FakeOdoo()
    duplicate = deepcopy(client.records["purchase.order.line"][0])
    duplicate["id"] = 41
    client.records["purchase.order.line"].append(duplicate)
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client)
    assert caught.value.category == "STATE_INVALID"


def test_many2one_display_names_do_not_supply_business_references() -> None:
    client = FakeOdoo()
    for model in ("purchase.order", "purchase.order.line", "product.product", "res.partner.bank"):
        for row in client.records[model]:
            for field, value in row.items():
                if field.endswith("_id") and isinstance(value, list):
                    value[1] = "TCC-ATTACKER-LABEL-NO-AUTHORITY"
    resolved = _read(client)
    assert resolved.state.purchase_order.vendor_ref == "TCC-VENDOR-001"
    assert resolved.state.purchase_order.currency == "BRL"
    assert resolved.lines[0].item_code == "TCC-SERVICE-001"
    assert resolved.state.allowed_bank_refs == ("TCC-BANK-001",)


def test_missing_post_target_is_not_replaced_by_proposed_document_ref() -> None:
    client = FakeOdoo(post=True)
    client.records["account.move"][0]["ref"] = "TCC-OTHER-NF-SEM-VALOR-FISCAL"
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client, post=True)
    assert caught.value.category == "REFERENCE_NOT_FOUND"


@pytest.mark.parametrize("bad_ids", [[], [51, 51], [True], ["51"], [51, 52]])
def test_target_invoice_line_ids_are_complete_unique_strict_membership(bad_ids) -> None:
    client = FakeOdoo(post=True)
    client.records["account.move"][0]["invoice_line_ids"] = bad_ids
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client, post=True)
    assert caught.value.category == "STATE_INVALID"


@pytest.mark.parametrize("display_type", ["line_section", "line_note", "payment_term", False])
def test_target_nonproduct_invoice_lines_cannot_be_hidden_by_search_filter(display_type) -> None:
    client = FakeOdoo(post=True)
    extra = deepcopy(client.records["account.move.line"][0])
    extra.update(id=52, display_type=display_type)
    client.records["account.move.line"].append(extra)
    client.records["account.move"][0]["invoice_line_ids"].append(52)
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client, post=True)
    assert caught.value.category == "STATE_INVALID"
    line_calls = [arguments for model, _, arguments in client.calls if model == "account.move.line"]
    assert line_calls
    assert not any(term[0] == "display_type" for term in line_calls[0]["domain"] if isinstance(term, list))


def test_returned_extra_invoice_line_outside_declared_membership_is_rejected() -> None:
    client = FakeOdoo(post=True)
    original = deepcopy(client.records["account.move.line"][0])
    extra = deepcopy(original)
    extra["id"] = 52
    client.response_overrides["account.move.line"] = [original, extra]
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client, post=True)
    assert caught.value.category == "STATE_INVALID"


@pytest.mark.parametrize("field,value", [("auto_post", "at_date"), ("move_type", "out_invoice"), ("invoice_origin", "TCC-PO-002")])
def test_target_cannot_leave_fixed_accounting_workflow(field, value) -> None:
    client = FakeOdoo(post=True)
    row = deepcopy(client.records["account.move"][0])
    row[field] = value
    client.response_overrides["account.move"] = [row]
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client, post=True)
    assert caught.value.category == "STATE_INVALID"


@pytest.mark.parametrize("bad_rows", [None, True, {}, [None], [True], ["RAW-RECORD-MARKER-NOT-FOR-LOGS"]])
def test_malformed_transport_response_is_classified_without_raw_payload(bad_rows) -> None:
    client = FakeOdoo()
    client.response_overrides["purchase.order"] = bad_rows
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client)
    assert caught.value.category == "STATE_INVALID"
    assert "RAW-RECORD-MARKER" not in str(caught.value)


@pytest.mark.parametrize("discount", [0.01, 10.0, True, float("nan")])
def test_po_line_discounts_cannot_bypass_price_and_total_checks(discount) -> None:
    client = FakeOdoo()
    client.records["purchase.order.line"][0]["discount"] = discount
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client)
    assert caught.value.category == "STATE_INVALID"


def test_unknown_po_state_is_not_fabricated_confirmed() -> None:
    client = FakeOdoo()
    client.records["purchase.order"][0]["state"] = "done"
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client)
    assert caught.value.category == "STATE_INVALID"


@pytest.mark.parametrize("scale", [2, 3, 4])
def test_protocol_quantity_scale_is_applied_identically_to_po_and_proposal(scale) -> None:
    resolved = _read(FakeOdoo(), workflow=_workflow(quantity_scale=scale))
    policy_input = _prepare(_proposal(), resolved)
    expected = "1." + "0" * scale
    assert resolved.state.purchase_order.lines[0].quantity == expected
    assert resolved.state.purchase_order.lines[0].quantity_to_invoice == expected
    assert policy_input.action.lines[0].quantity == expected
    assert evaluate_policy(policy_input).decision == "ALLOW"


def test_explicit_empty_bank_allowlist_is_not_replaced_by_supplier_default_bank() -> None:
    resolved = _read(FakeOdoo(), workflow=_workflow(allowed_bank_refs=()))
    assert resolved.state.allowed_bank_refs == ()
    assert resolved.bank_ids == ()
    assert ReasonCode.BANK_NOT_ALLOWED in evaluate_policy(_prepare(_proposal(), resolved)).reason_codes


def test_observed_state_unavailability_stops_before_any_odoo_read() -> None:
    client = FakeOdoo()
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client, operational=_operational(
            dependencies=DependencyStatus("UNAVAILABLE", "AVAILABLE", "AVAILABLE"),
        ))
    assert caught.value.category == "DEPENDENCY_UNAVAILABLE"
    assert client.calls == []


@pytest.mark.parametrize("field,value", [("active", 1), ("allow_out_payment", "true")])
def test_bank_boolean_fields_are_not_coerced_from_transport_values(field, value) -> None:
    client = FakeOdoo()
    row = deepcopy(client.records["res.partner.bank"][0])
    row[field] = value
    client.response_overrides["res.partner.bank"] = [row]
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client)
    assert caught.value.category == "STATE_INVALID"


def test_transport_cannot_return_wrong_identity_for_id_lookup() -> None:
    client = FakeOdoo()
    row = deepcopy(client.records["res.partner"][0])
    row["id"] = 12
    client.response_overrides["res.partner"] = [row]
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client)
    assert caught.value.category == "STATE_INVALID"


def test_post_target_cannot_substitute_vendor_and_bank_ids_using_colliding_business_references() -> None:
    """Mesmo hash de referencias nao autoriza identidades internas distintas."""
    client = FakeOdoo(post=True)
    client.records["res.partner"][1]["ref"] = "TCC-VENDOR-001"
    client.records["res.partner.bank"][1]["acc_number"] = "TCC-BANK-001"
    client.records["account.move"][0].update(
        partner_id=_many2one(12), partner_bank_id=_many2one(13),
    )
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client, post=True)
    assert caught.value.category == "STATE_INVALID"


def test_two_allowlisted_bank_records_with_same_reference_never_authorize_post() -> None:
    client = FakeOdoo(post=True)
    alternate = client.records["res.partner.bank"][1]
    alternate.update(partner_id=_many2one(10), acc_number="TCC-BANK-001")
    client.records["account.move"][0]["partner_bank_id"] = _many2one(13)
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client, post=True)
    assert caught.value.category == "REFERENCE_AMBIGUOUS"


def test_target_bank_cannot_borrow_allowlisted_reference_from_a_different_bank_id() -> None:
    client = FakeOdoo(post=True)
    alternate = client.records["res.partner.bank"][1]
    alternate.update(
        partner_id=_many2one(10), acc_number="TCC-BANK-001", allow_out_payment=False,
    )
    client.records["account.move"][0]["partner_bank_id"] = _many2one(13)
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client, post=True)
    assert caught.value.category == "STATE_INVALID"


def test_discounted_po_cannot_be_hidden_inside_explicit_monetary_tolerance() -> None:
    client = FakeOdoo()
    client.records["purchase.order"][0]["amount_total"] = 125.49
    client.records["purchase.order.line"][0]["discount"] = 0.01
    with pytest.raises(TrustedStateResolutionError) as caught:
        _read(client, workflow=_workflow(monetary_tolerance="0.01"))
    assert caught.value.category == "STATE_INVALID"


@pytest.mark.parametrize("post,decision", [(False, "ALLOW"), (True, "REVIEW")])
def test_read_path_through_actual_json2_client_with_mock_http_transport(post, decision) -> None:
    """Prova de contrato do transporte, nao integracao com servidor/ACL reais."""
    fake = FakeOdoo(post=post)

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        prefix, model, method = request.url.path.rsplit("/", 2)
        assert prefix == "/json/2" and method == "search_read"
        payload = json.loads(request.content)
        assert "context" not in payload
        return httpx.Response(200, json=fake.call(model, method, arguments=payload))

    config = OdooConfig(
        base_url="http://odoo:8069", database="tcc_synthetic",
        api_token="synthetic-json2-token-do-not-use",
        connect_timeout_seconds=1.0, request_timeout_seconds=3.0,
    )
    with OdooJson2Client(config, transport=httpx.MockTransport(respond)) as client:
        resolved = read_trusted_state(client, _workflow(post=post), _operational(), policy_version=POLICY_VERSION)
    assert evaluate_policy(_prepare(_proposal(post=post), resolved)).decision == decision
    assert fake.calls and all(method == "search_read" for _, method, _ in fake.calls)


def test_proposed_post_in_draft_phase_stays_a_content_failure() -> None:
    """DEC-063: proposed content that does not canonicalize is a policy denial."""
    with pytest.raises(CanonicalizationError) as captured:
        _prepare(_proposal(post=True), _read(FakeOdoo()))
    assert type(captured.value) is CanonicalizationError


@pytest.mark.parametrize("problem", ["policy_version", "lifetime", "provenance"])
def test_trusted_binding_failures_are_technical(problem) -> None:
    """DEC-063: binding faults come from the runner or workflow, not from the proposal."""
    post = problem == "policy_version"
    resolved = _read(FakeOdoo(post=post), post=post)
    proposal = _proposal(post=post)
    args = {"policy_version": POLICY_VERSION, "evaluated_at": "2026-09-30T12:00:00Z",
            "expires_at": "2026-09-30T12:01:00Z"}
    if problem == "policy_version":
        args["policy_version"] = "policy-other-v1"
    elif problem == "lifetime":
        args["expires_at"] = args["evaluated_at"]
    else:
        value = proposal.to_mapping()
        value["scenario_id"] = "SCN-002"
        proposal = ActionProposalV2.from_mapping(value)
    with pytest.raises(TrustedBindingError):
        prepare_policy_input(proposal, resolved, **args)
