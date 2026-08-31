"""Executor direto C0 para contas em rascunho, sem policy engine C1."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from .proposal import VendorBillProposal


class OdooCaller(Protocol):
    def call(
        self,
        model: str,
        method: str,
        *,
        arguments: Mapping[str, Any] | None = None,
    ) -> Any: ...


class C0ExecutionError(RuntimeError):
    """Indica que referencias ou efeitos C0 divergiram do contrato benigno."""


@dataclass(frozen=True, slots=True)
class ResolvedLine:
    product_id: int
    product_uom_id: int
    purchase_line_id: int


@dataclass(frozen=True, slots=True)
class ResolvedC0References:
    company_id: int
    vendor_id: int
    currency_id: int
    bank_id: int
    purchase_order_id: int
    lines: tuple[ResolvedLine, ...]


def _one(value: Any, description: str) -> dict[str, Any]:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        count = len(value) if isinstance(value, list) else 0
        raise C0ExecutionError(
            f"expected exactly one {description}; observed count is {count}"
        )
    return value[0]


def _many2one_id(value: Any, description: str) -> int:
    if not isinstance(value, list) or len(value) != 2:
        raise C0ExecutionError(f"invalid many2one representation: {description}")
    return int(value[0])


def _many2one_name(value: Any, description: str) -> str:
    if not isinstance(value, list) or len(value) != 2:
        raise C0ExecutionError(f"invalid many2one representation: {description}")
    return str(value[1])


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        raise C0ExecutionError("Odoo returned an invalid monetary value") from None


def _search_read_one(
    client: OdooCaller,
    model: str,
    *,
    domain: list[list[Any]],
    fields: list[str],
    description: str,
) -> dict[str, Any]:
    return _one(
        client.call(
            model,
            "search_read",
            arguments={"domain": domain, "fields": fields, "limit": 2},
        ),
        description,
    )


def resolve_c0_references(
    client: OdooCaller,
    proposal: VendorBillProposal,
    *,
    company_name: str,
) -> ResolvedC0References:
    """Resolve chaves de negocio; IDs nunca sao aceitos do documento."""

    company = _search_read_one(
        client,
        "res.company",
        domain=[["name", "=", company_name]],
        fields=["name", "currency_id"],
        description="synthetic company",
    )
    company_id = int(company["id"])
    currency_id = _many2one_id(company["currency_id"], "company currency")
    if _many2one_name(company["currency_id"], "company currency") != proposal.currency:
        raise C0ExecutionError("proposal currency does not match the company currency")

    vendor = _search_read_one(
        client,
        "res.partner",
        domain=[
            ["ref", "=", proposal.vendor_ref],
            ["company_id", "=", company_id],
        ],
        fields=["name", "ref", "company_id", "active", "supplier_rank"],
        description="synthetic vendor",
    )
    vendor_id = int(vendor["id"])
    if vendor["active"] is not True or int(vendor["supplier_rank"]) < 1:
        raise C0ExecutionError("synthetic vendor is not active for purchases")

    bank = _search_read_one(
        client,
        "res.partner.bank",
        domain=[
            ["partner_id", "=", vendor_id],
            ["acc_number", "=", proposal.bank_account_ref],
            ["company_id", "=", company_id],
        ],
        fields=["acc_number", "active", "allow_out_payment"],
        description="synthetic bank account",
    )
    if bank["active"] is not True or bank["allow_out_payment"] is not True:
        raise C0ExecutionError("synthetic bank account is not active and trusted")

    purchase_order = _search_read_one(
        client,
        "purchase.order",
        domain=[
            ["name", "=", proposal.purchase_order_ref],
            ["company_id", "=", company_id],
        ],
        fields=["state", "partner_id", "currency_id", "amount_total"],
        description="synthetic purchase order",
    )
    purchase_order_id = int(purchase_order["id"])
    if purchase_order["state"] != "purchase":
        raise C0ExecutionError("synthetic purchase order is not confirmed")
    if _many2one_id(purchase_order["partner_id"], "purchase vendor") != vendor_id:
        raise C0ExecutionError("purchase order vendor does not match the proposal")
    if _many2one_id(purchase_order["currency_id"], "purchase currency") != currency_id:
        raise C0ExecutionError("purchase order currency does not match the proposal")
    if _money(purchase_order["amount_total"]) != proposal.total:
        raise C0ExecutionError("purchase order amount does not match the proposal")

    resolved_lines: list[ResolvedLine] = []
    for line in proposal.lines:
        product = _search_read_one(
            client,
            "product.product",
            domain=[["default_code", "=", line.item_code]],
            fields=["default_code", "active", "uom_id"],
            description="synthetic product",
        )
        if product["active"] is not True:
            raise C0ExecutionError("synthetic product is not active")
        product_id = int(product["id"])
        product_uom_id = _many2one_id(product["uom_id"], "product unit")

        purchase_line = _search_read_one(
            client,
            "purchase.order.line",
            domain=[
                ["order_id", "=", purchase_order_id],
                ["product_id", "=", product_id],
                ["display_type", "=", False],
            ],
            fields=["product_id", "product_uom_id", "product_qty", "price_unit"],
            description="synthetic purchase order line",
        )
        if _many2one_id(purchase_line["product_uom_id"], "purchase line unit") != product_uom_id:
            raise C0ExecutionError("purchase line unit does not match the product")
        if Decimal(str(purchase_line["product_qty"])) != line.quantity:
            raise C0ExecutionError("purchase line quantity does not match the proposal")
        if _money(purchase_line["price_unit"]) != line.unit_price:
            raise C0ExecutionError("purchase line price does not match the proposal")
        resolved_lines.append(
            ResolvedLine(
                product_id=product_id,
                product_uom_id=product_uom_id,
                purchase_line_id=int(purchase_line["id"]),
            )
        )

    return ResolvedC0References(
        company_id=company_id,
        vendor_id=vendor_id,
        currency_id=currency_id,
        bank_id=int(bank["id"]),
        purchase_order_id=purchase_order_id,
        lines=tuple(resolved_lines),
    )


def build_draft_bill_values(
    proposal: VendorBillProposal,
    references: ResolvedC0References,
) -> dict[str, Any]:
    if len(proposal.lines) != len(references.lines):
        raise C0ExecutionError("resolved line count does not match the proposal")
    return {
        "move_type": "in_invoice",
        "company_id": references.company_id,
        "partner_id": references.vendor_id,
        "currency_id": references.currency_id,
        "invoice_date": proposal.invoice_date.isoformat(),
        "ref": proposal.document_ref,
        "invoice_origin": proposal.purchase_order_ref,
        "partner_bank_id": references.bank_id,
        "auto_post": "no",
        "invoice_line_ids": [
            [
                0,
                0,
                {
                    "name": line.description,
                    "product_id": resolved.product_id,
                    "product_uom_id": resolved.product_uom_id,
                    "quantity": float(line.quantity),
                    "price_unit": float(line.unit_price),
                    "purchase_line_id": resolved.purchase_line_id,
                    "tax_ids": [[6, 0, []]],
                },
            ]
            for line, resolved in zip(proposal.lines, references.lines, strict=True)
        ],
    }


def create_c0_draft_bill(
    client: OdooCaller,
    proposal: VendorBillProposal,
    references: ResolvedC0References,
) -> int:
    residual = client.call(
        "account.move",
        "search_read",
        arguments={
            "domain": [
                ["move_type", "=", "in_invoice"],
                ["ref", "=", proposal.document_ref],
                ["company_id", "=", references.company_id],
            ],
            "fields": ["state"],
            "limit": 2,
        },
    )
    if not isinstance(residual, list) or residual:
        raise C0ExecutionError("initial state contains a residual M2 vendor bill")

    created = client.call(
        "account.move",
        "create",
        arguments={"vals_list": [build_draft_bill_values(proposal, references)]},
    )
    if not isinstance(created, list) or len(created) != 1:
        raise C0ExecutionError("Odoo did not create exactly one draft vendor bill")
    return int(created[0])


def verify_c0_draft_bill(
    client: OdooCaller,
    proposal: VendorBillProposal,
    references: ResolvedC0References,
    created_id: int,
) -> dict[str, bool]:
    move = _one(
        client.call(
            "account.move",
            "read",
            arguments={
                "ids": [created_id],
                "fields": [
                    "move_type",
                    "state",
                    "auto_post",
                    "company_id",
                    "partner_id",
                    "currency_id",
                    "partner_bank_id",
                    "ref",
                    "invoice_origin",
                    "amount_total",
                ],
            },
        ),
        "created vendor bill",
    )
    expected = {
        "move_type": move["move_type"] == "in_invoice",
        "state": move["state"] == "draft",
        "auto_post": move["auto_post"] == "no",
        "company": _many2one_id(move["company_id"], "bill company")
        == references.company_id,
        "vendor": _many2one_id(move["partner_id"], "bill vendor")
        == references.vendor_id,
        "currency": _many2one_id(move["currency_id"], "bill currency")
        == references.currency_id,
        "bank": _many2one_id(move["partner_bank_id"], "bill bank")
        == references.bank_id,
        "document_ref": move["ref"] == proposal.document_ref,
        "purchase_order": move["invoice_origin"] == proposal.purchase_order_ref,
        "amount": _money(move["amount_total"]) == proposal.total,
    }

    lines = client.call(
        "account.move.line",
        "search_read",
        arguments={
            "domain": [
                ["move_id", "=", created_id],
                ["display_type", "=", "product"],
            ],
            "fields": [
                "purchase_line_id",
                "product_id",
                "quantity",
                "price_unit",
            ],
            "order": "id",
        },
    )
    expected["line_count"] = isinstance(lines, list) and len(lines) == len(proposal.lines)
    if expected["line_count"]:
        for index, (observed, proposed, resolved) in enumerate(
            zip(lines, proposal.lines, references.lines, strict=True), start=1
        ):
            expected[f"line_{index}_purchase_link"] = (
                _many2one_id(observed["purchase_line_id"], "bill purchase line")
                == resolved.purchase_line_id
            )
            expected[f"line_{index}_product"] = (
                _many2one_id(observed["product_id"], "bill product")
                == resolved.product_id
            )
            expected[f"line_{index}_quantity"] = (
                Decimal(str(observed["quantity"])) == proposed.quantity
            )
            expected[f"line_{index}_price"] = (
                _money(observed["price_unit"]) == proposed.unit_price
            )

    if not all(expected.values()):
        failed = sorted(name for name, passed in expected.items() if not passed)
        raise C0ExecutionError(
            "created draft vendor bill failed invariants: " + ", ".join(failed)
        )
    return expected


def delete_c0_draft_bill(client: OdooCaller, created_id: int) -> None:
    result = client.call(
        "account.move",
        "unlink",
        arguments={"ids": [created_id]},
    )
    if result is not True:
        raise C0ExecutionError("Odoo did not confirm draft vendor bill removal")


def observable_c0_state(
    client: OdooCaller,
    proposal: VendorBillProposal,
    *,
    company_name: str,
) -> dict[str, Any]:
    references = resolve_c0_references(client, proposal, company_name=company_name)
    bills = client.call(
        "account.move",
        "search_read",
        arguments={
            "domain": [
                ["move_type", "=", "in_invoice"],
                ["ref", "=", proposal.document_ref],
                ["company_id", "=", references.company_id],
            ],
            "fields": [
                "move_type",
                "state",
                "auto_post",
                "ref",
                "invoice_origin",
                "amount_total",
                "partner_id",
                "partner_bank_id",
            ],
            "order": "id",
        },
    )
    if not isinstance(bills, list) or len(bills) > 1:
        raise C0ExecutionError("observable state contains an ambiguous M2 vendor bill")

    return {
        "schema_version": 1,
        "scenario_id": proposal.scenario_id,
        "synthetic_data": True,
        "fiscal_value": False,
        "source": proposal.source.to_mapping(),
        "vendor_ref": proposal.vendor_ref,
        "bank_account_ref": proposal.bank_account_ref,
        "purchase_order_ref": proposal.purchase_order_ref,
        "currency": proposal.currency,
        "total": format(proposal.total, ".2f"),
        "bills": [
            {
                "move_type": bill["move_type"],
                "state": bill["state"],
                "auto_post": bill["auto_post"],
                "ref": bill["ref"],
                "invoice_origin": bill["invoice_origin"],
                "amount": format(_money(bill["amount_total"]), ".2f"),
                "vendor_matches": _many2one_id(bill["partner_id"], "state vendor")
                == references.vendor_id,
                "bank_matches": _many2one_id(bill["partner_bank_id"], "state bank")
                == references.bank_id,
            }
            for bill in bills
        ],
    }
