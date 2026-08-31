from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from tcc_gateway.c0_executor import (
    C0ExecutionError,
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

    def call(self, model: str, method: str, *, arguments=None):
        if model == "res.company":
            return [{"id": 1, "name": "TCC LAB", "currency_id": [2, "USD"]}]
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
                    "acc_number": "TCC-SYNTHETIC-BANK-0001",
                    "active": True,
                    "allow_out_payment": True,
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
    references = resolve_c0_references(client, proposal, company_name="TCC LAB")
    initial = observable_c0_state(client, proposal, company_name="TCC LAB")

    created_id = create_c0_draft_bill(client, proposal, references)
    invariants = verify_c0_draft_bill(client, proposal, references, created_id)
    created = observable_c0_state(client, proposal, company_name="TCC LAB")
    delete_c0_draft_bill(client, created_id)
    restored = observable_c0_state(client, proposal, company_name="TCC LAB")

    assert all(invariants.values())
    assert canonical_json_sha256(created) != canonical_json_sha256(initial)
    assert canonical_json_sha256(restored) == canonical_json_sha256(initial)
    assert client.created_values == build_draft_bill_values(proposal, references)
    assert client.created_values["move_type"] == "in_invoice"
    assert client.created_values["auto_post"] == "no"


def test_resolver_rejects_purchase_order_amount_mismatch() -> None:
    client = FakeOdoo()
    client.purchase_amount = 126.50

    with pytest.raises(C0ExecutionError, match="purchase order amount"):
        resolve_c0_references(client, _proposal(), company_name="TCC LAB")


def test_create_rejects_residual_document() -> None:
    client = FakeOdoo()
    proposal = _proposal()
    references = resolve_c0_references(client, proposal, company_name="TCC LAB")
    client.created = True

    with pytest.raises(C0ExecutionError, match="residual"):
        create_c0_draft_bill(client, proposal, references)
