"""Tipos imutaveis do contrato de proposta de conta de fornecedor."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any

from .proposal_schema import validate_proposal_mapping


SCHEMA_VERSION = "vendor-bill-proposal/v1"
CREATE_DRAFT_BILL = "CREATE_DRAFT_BILL"
_CENT = Decimal("0.01")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ProposalValueError(ValueError):
    """Indica inconsistencia semantica em uma proposta tipada."""


def _require_non_empty(value: str, name: str, maximum: int) -> None:
    if not value or value.strip() != value or len(value) > maximum:
        raise ProposalValueError(f"invalid proposal field: {name}")


def _require_positive(value: Decimal, name: str) -> None:
    if not value.is_finite() or value <= 0:
        raise ProposalValueError(f"proposal decimal must be positive: {name}")


def _require_money(value: Decimal, name: str) -> None:
    _require_positive(value, name)
    if value.as_tuple().exponent != -2:
        raise ProposalValueError(f"proposal money must use exactly two decimals: {name}")


@dataclass(frozen=True, slots=True)
class ProposalSource:
    document_sha256: str
    text_sha256: str
    page_count: int

    def __post_init__(self) -> None:
        if not _SHA256_PATTERN.fullmatch(self.document_sha256):
            raise ProposalValueError("invalid proposal source document hash")
        if not _SHA256_PATTERN.fullmatch(self.text_sha256):
            raise ProposalValueError("invalid proposal source text hash")
        if not 1 <= self.page_count <= 4:
            raise ProposalValueError("invalid proposal source page count")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "document_sha256": self.document_sha256,
            "text_sha256": self.text_sha256,
            "page_count": self.page_count,
        }


@dataclass(frozen=True, slots=True)
class VendorBillLineProposal:
    item_code: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal

    def __post_init__(self) -> None:
        _require_non_empty(self.item_code, "item_code", 96)
        _require_non_empty(self.description, "description", 160)
        _require_positive(self.quantity, "quantity")
        if not -4 <= self.quantity.as_tuple().exponent <= -2:
            raise ProposalValueError(
                "proposal quantity must use between two and four decimals"
            )
        _require_money(self.unit_price, "unit_price")
        _require_money(self.line_total, "line_total")
        calculated = (self.quantity * self.unit_price).quantize(
            _CENT, rounding=ROUND_HALF_EVEN
        )
        if calculated != self.line_total:
            raise ProposalValueError("proposal line total does not reconcile")

    def to_mapping(self) -> dict[str, str]:
        return {
            "item_code": self.item_code,
            "description": self.description,
            "quantity": format(self.quantity, "f"),
            "unit_price": format(self.unit_price, ".2f"),
            "line_total": format(self.line_total, ".2f"),
        }


@dataclass(frozen=True, slots=True)
class VendorBillProposal:
    producer: str
    scenario_id: str
    source: ProposalSource
    vendor_ref: str
    purchase_order_ref: str
    document_ref: str
    invoice_date: date
    currency: str
    bank_account_ref: str
    lines: tuple[VendorBillLineProposal, ...]
    total: Decimal
    schema_version: str = SCHEMA_VERSION
    action: str = CREATE_DRAFT_BILL
    synthetic_data: bool = True
    fiscal_value: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ProposalValueError("unsupported proposal schema version")
        if self.action != CREATE_DRAFT_BILL:
            raise ProposalValueError("unsupported proposal action")
        if self.synthetic_data is not True or self.fiscal_value is not False:
            raise ProposalValueError("proposal must be synthetic and without fiscal value")
        _require_non_empty(self.producer, "producer", 64)
        _require_non_empty(self.scenario_id, "scenario_id", 64)
        _require_non_empty(self.vendor_ref, "vendor_ref", 96)
        _require_non_empty(self.purchase_order_ref, "purchase_order_ref", 96)
        _require_non_empty(self.document_ref, "document_ref", 96)
        _require_non_empty(self.currency, "currency", 3)
        _require_non_empty(self.bank_account_ref, "bank_account_ref", 96)
        if not 1 <= len(self.lines) <= 50:
            raise ProposalValueError("proposal must contain between one and fifty lines")
        _require_money(self.total, "total")
        if sum((line.line_total for line in self.lines), Decimal("0.00")) != self.total:
            raise ProposalValueError("proposal total does not reconcile")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "action": self.action,
            "producer": self.producer,
            "scenario_id": self.scenario_id,
            "synthetic_data": self.synthetic_data,
            "fiscal_value": self.fiscal_value,
            "source": self.source.to_mapping(),
            "vendor_ref": self.vendor_ref,
            "purchase_order_ref": self.purchase_order_ref,
            "document_ref": self.document_ref,
            "invoice_date": self.invoice_date.isoformat(),
            "currency": self.currency,
            "bank_account_ref": self.bank_account_ref,
            "lines": [line.to_mapping() for line in self.lines],
            "total": format(self.total, ".2f"),
        }

    def validate_schema(self) -> None:
        validate_proposal_mapping(self.to_mapping())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> VendorBillProposal:
        validate_proposal_mapping(value)
        source_value = value["source"]
        lines_value = value["lines"]
        proposal = cls(
            producer=str(value["producer"]),
            scenario_id=str(value["scenario_id"]),
            source=ProposalSource(
                document_sha256=str(source_value["document_sha256"]),
                text_sha256=str(source_value["text_sha256"]),
                page_count=int(source_value["page_count"]),
            ),
            vendor_ref=str(value["vendor_ref"]),
            purchase_order_ref=str(value["purchase_order_ref"]),
            document_ref=str(value["document_ref"]),
            invoice_date=date.fromisoformat(str(value["invoice_date"])),
            currency=str(value["currency"]),
            bank_account_ref=str(value["bank_account_ref"]),
            lines=tuple(
                VendorBillLineProposal(
                    item_code=str(line["item_code"]),
                    description=str(line["description"]),
                    quantity=Decimal(str(line["quantity"])),
                    unit_price=Decimal(str(line["unit_price"])),
                    line_total=Decimal(str(line["line_total"])),
                )
                for line in lines_value
            ),
            total=Decimal(str(value["total"])),
            schema_version=str(value["schema_version"]),
            action=str(value["action"]),
            synthetic_data=bool(value["synthetic_data"]),
            fiscal_value=bool(value["fiscal_value"]),
        )
        proposal.validate_schema()
        return proposal
