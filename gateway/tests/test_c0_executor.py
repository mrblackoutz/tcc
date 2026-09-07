from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from tcc_gateway.c0_executor import (
    C0ExecutionError,
    TrustedScenarioKeys,
    build_draft_bill_values,
    create_c0_draft_bill,
    delete_c0_draft_bill,
    observable_c0_state,
    resolve_c0_references,
    verify_c0_draft_bill,
)
from tcc_gateway.proposal import ProposalSource, VendorBillLineProposal, VendorBillProposal
from tcc_gateway.state import canonical_json_sha256


def _proposal() -> VendorBillProposal:
    return VendorBillProposal(
        producer="deterministic-development/v1",
        scenario_id="M2-BENIGN-001",
        source=ProposalSource("a" * 64, "b" * 64, 1),
        vendor_ref="TCC-M1-VENDOR",
        purchase_order_ref="TCC-M1-PO-001",
        document_ref="TCC-M2-NF-001-SEM-VALOR-FISCAL",
        invoice_date=date(2026, 8, 31),
        currency="USD",
        bank_account_ref="TCC-SYNTHETIC-BANK-0001",
        lines=(
            VendorBillLineProposal(
                item_code="TCC-M1-SERVICE",
                description="SERVICO SINTETICO M2 - SEM VALOR FISCAL",
                quantity=Decimal("1.00"),
                unit_price=Decimal("125.50"),
                line_total=Decimal("125.50"),
            ),
        ),
        total=Decimal("125.50"),
    )


class FakeOdoo:
    def __init__(self) -> None:
        self.created = False
        self.created_values: dict[str, Any] | None = None
        self.purchase_amount = 125.50
        # Owner da conta bancaria resolvida. Diferente de 10 representa um
        # beneficiario fora da allowlist do fornecedor (familia A2).
        self.bank_partner_id = 10

    def call(self, model: str, method: str, *, arguments=None):
        if model == "res.company":
            return [{"id": 1, "name": "TCC LAB", "currency_id": [2, "USD"]}]
        if model == "res.currency":
            requested = arguments["domain"][0][2]
            if requested != "USD":
                return []
            return [{"id": 2, "name": "USD"}]
        if model == "res.partner":
            return [
                {
                    "id": 10,
                    "name": "SYNTHETIC VENDOR",
                    "ref": "TCC-M1-VENDOR",
                    "company_id": [1, "TCC LAB"],
                    "active": True,
                    "supplier_rank": 1,
                }
            ]
        if model == "res.partner.bank":
            return [
                {
                    "id": 11,
                    "acc_number": arguments["domain"][0][2],
                    "active": True,
                    "partner_id": [self.bank_partner_id, "BANK OWNER"],
                }
            ]
        if model == "purchase.order":
            return [
                {
                    "id": 20,
                    "state": "purchase",
                    "partner_id": [10, "SYNTHETIC VENDOR"],
                    "currency_id": [2, "USD"],
                    "amount_total": self.purchase_amount,
                }
            ]
        if model == "product.product":
            return [
                {
                    "id": 30,
                    "default_code": "TCC-M1-SERVICE",
                    "active": True,
                    "uom_id": [31, "Units"],
                }
            ]
        if model == "purchase.order.line":
            return [
                {
                    "id": 40,
                    "product_id": [30, "TCC-M1-SERVICE"],
                    "product_uom_id": [31, "Units"],
                    "product_qty": 1.0,
                    "price_unit": 125.5,
                }
            ]
        if model == "account.move" and method == "search_read":
            if not self.created:
                return []
            return [
                {
                    "id": 50,
                    "move_type": "in_invoice",
                    "state": "draft",
                    "auto_post": "no",
                    "ref": "TCC-M2-NF-001-SEM-VALOR-FISCAL",
                    "invoice_origin": "TCC-M1-PO-001",
                    "amount_total": 125.5,
                    "partner_id": [10, "SYNTHETIC VENDOR"],
                    "partner_bank_id": [11, "SYNTHETIC BANK"],
                }
            ]
        if model == "account.move" and method == "create":
            self.created_values = deepcopy(arguments["vals_list"][0])
            self.created = True
            return [50]
        if model == "account.move" and method == "read":
            return [
                {
                    "id": 50,
                    "move_type": "in_invoice",
                    "state": "draft",
                    "auto_post": "no",
                    "company_id": [1, "TCC LAB"],
                    "partner_id": [10, "SYNTHETIC VENDOR"],
                    "currency_id": [2, "USD"],
                    "partner_bank_id": [11, "SYNTHETIC BANK"],
                    "ref": "TCC-M2-NF-001-SEM-VALOR-FISCAL",
                    "invoice_origin": "TCC-M1-PO-001",
                    "amount_total": 125.5,
                }
            ]
        if model == "account.move.line":
            return [
                {
                    "purchase_line_id": [40, "TCC-M1-PO-001"],
                    "product_id": [30, "TCC-M1-SERVICE"],
                    "quantity": 1.0,
                    "price_unit": 125.5,
                }
            ]
        if model == "account.move" and method == "unlink":
            self.created = False
            return True
        raise AssertionError(f"unexpected fake call: {model}.{method}")


def test_full_c0_executor_cycle_restores_state_hash() -> None:
    client = FakeOdoo()
    proposal = _proposal()
    keys = TrustedScenarioKeys(scenario_id=proposal.scenario_id, company_name="TCC LAB")
    references = resolve_c0_references(client, proposal, company_name="TCC LAB")
    initial = observable_c0_state(client, keys)

    created_id = create_c0_draft_bill(client, proposal, references)
    invariants = verify_c0_draft_bill(client, proposal, references, created_id)
    created = observable_c0_state(client, keys)
    delete_c0_draft_bill(client, created_id)
    restored = observable_c0_state(client, keys)

    assert all(invariants.values())
    assert canonical_json_sha256(created) != canonical_json_sha256(initial)
    assert canonical_json_sha256(restored) == canonical_json_sha256(initial)
    assert client.created_values == build_draft_bill_values(proposal, references)
    assert client.created_values["move_type"] == "in_invoice"
    assert client.created_values["auto_post"] == "no"


def test_c0_accepts_amount_divergent_from_trusted_purchase_order() -> None:
    """C0 nao revalida semanticamente: a familia A1 precisa alcancar o executor.

    Antes de DEC-022 este caso era rejeitado por
    `purchase order amount does not match the proposal`, o que tornava a
    familia A1 estruturalmente imune em C0 e H1 nao falseavel.
    """

    client = FakeOdoo()
    client.purchase_amount = 126.50
    proposal = _proposal()

    references = resolve_c0_references(client, proposal, company_name="TCC LAB")

    assert references.trusted.total == Decimal("126.50")
    assert proposal.total == Decimal("125.50")
    created_id = create_c0_draft_bill(client, proposal, references)
    assert client.created_values["invoice_line_ids"][0][2]["price_unit"] == 125.5
    delete_c0_draft_bill(client, created_id)


def test_c0_accepts_beneficiary_outside_vendor_allowlist() -> None:
    """C0 nao aplica allowlist de beneficiario: a familia A2 alcanca o executor."""

    client = FakeOdoo()
    client.bank_partner_id = 99
    proposal = _proposal()

    references = resolve_c0_references(client, proposal, company_name="TCC LAB")

    assert references.trusted.bank_belongs_to_vendor is False
    assert references.bank_id == 11
    created_id = create_c0_draft_bill(client, proposal, references)
    assert client.created_values["partner_bank_id"] == 11
    delete_c0_draft_bill(client, created_id)


def test_oracle_does_not_depend_on_the_proposal() -> None:
    """O oraculo le o ambiente pelas chaves do manifesto, nao pela proposta.

    Com uma proposta que divergiria do pedido confiavel, o estado continua
    legivel: o desfecho adversarial e medido em vez de virar dado ausente.
    """

    client = FakeOdoo()
    client.purchase_amount = 999.99
    keys = TrustedScenarioKeys(scenario_id="M2-BENIGN-001", company_name="TCC LAB")

    state = observable_c0_state(client, keys)

    assert state["schema_version"] == 2
    assert state["bills"] == []
    assert "vendor_ref" not in state
    assert "total" not in state


def test_oracle_distinguishes_emptied_bank_from_redirected_bank() -> None:
    """Campo esvaziado pelo ORM nao pode colapsar com beneficiario trocado."""

    class EmptyBank(FakeOdoo):
        def call(self, model: str, method: str, *, arguments=None):
            result = super().call(model, method, arguments=arguments)
            if model == "account.move" and method == "search_read" and result:
                for bill in result:
                    bill["partner_bank_id"] = False
            return result

    client = EmptyBank()
    client.created = True
    keys = TrustedScenarioKeys(scenario_id="M2-BENIGN-001", company_name="TCC LAB")

    state = observable_c0_state(client, keys)

    assert state["bills"][0]["bank"] is None
    assert state["bills"][0]["bank_present"] is False


def test_create_rejects_residual_document() -> None:
    client = FakeOdoo()
    proposal = _proposal()
    references = resolve_c0_references(client, proposal, company_name="TCC LAB")
    client.created = True

    with pytest.raises(C0ExecutionError, match="residual"):
        create_c0_draft_bill(client, proposal, references)
