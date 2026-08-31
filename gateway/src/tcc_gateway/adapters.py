"""Adaptadores que transformam texto de documento em proposta tipada."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Protocol

from .pdf_ingestion import ExtractedPdf
from .proposal import ProposalSource, VendorBillLineProposal, VendorBillProposal
from .synthetic_pdf import DOCUMENT_END, DOCUMENT_HEADER


DEVELOPMENT_ADAPTER_ID = "deterministic-development/v1"
_FIELD_NAMES = {
    "SCENARIO_ID",
    "VENDOR_REF",
    "PURCHASE_ORDER",
    "DOCUMENT_REF",
    "INVOICE_DATE",
    "CURRENCY",
    "BANK_ACCOUNT",
    "ITEM_CODE",
    "ITEM_DESCRIPTION",
    "QUANTITY",
    "UNIT_PRICE",
    "TOTAL",
}


class ProposalAdapterError(ValueError):
    """Indica que o adaptador nao produziu uma proposta aceitavel."""


class ProposalAdapter(Protocol):
    adapter_id: str

    def propose(self, document: ExtractedPdf) -> VendorBillProposal: ...


def _parse_declared_fields(text: str) -> dict[str, str]:
    lines = [line for line in text.split("\n") if line]
    if len(lines) < 3 or lines[0] != DOCUMENT_HEADER or lines[-1] != DOCUMENT_END:
        raise ProposalAdapterError("document envelope is invalid")

    fields: dict[str, str] = {}
    for line in lines[1:-1]:
        if ": " not in line:
            raise ProposalAdapterError("document field syntax is invalid")
        name, value = line.split(": ", 1)
        if name not in _FIELD_NAMES:
            raise ProposalAdapterError("document contains an unknown field")
        if name in fields:
            raise ProposalAdapterError("document contains a duplicate field")
        if not value or value.strip() != value:
            raise ProposalAdapterError("document contains an invalid field value")
        fields[name] = value

    if set(fields) != _FIELD_NAMES:
        raise ProposalAdapterError("document is missing a required field")
    return fields


class DeterministicDevelopmentAdapter:
    """Parser M2 limitado; proibido para runs cientificas conforme DEC-017."""

    adapter_id = DEVELOPMENT_ADAPTER_ID

    def propose(self, document: ExtractedPdf) -> VendorBillProposal:
        fields = _parse_declared_fields(document.text)
        try:
            quantity = Decimal(fields["QUANTITY"])
            unit_price = Decimal(fields["UNIT_PRICE"])
            total = Decimal(fields["TOTAL"])
            invoice_date = date.fromisoformat(fields["INVOICE_DATE"])
        except (InvalidOperation, ValueError):
            raise ProposalAdapterError("document contains an invalid typed value") from None

        try:
            proposal = VendorBillProposal(
                producer=self.adapter_id,
                scenario_id=fields["SCENARIO_ID"],
                source=ProposalSource(
                    document_sha256=document.document_sha256,
                    text_sha256=document.text_sha256,
                    page_count=document.page_count,
                ),
                vendor_ref=fields["VENDOR_REF"],
                purchase_order_ref=fields["PURCHASE_ORDER"],
                document_ref=fields["DOCUMENT_REF"],
                invoice_date=invoice_date,
                currency=fields["CURRENCY"],
                bank_account_ref=fields["BANK_ACCOUNT"],
                lines=(
                    VendorBillLineProposal(
                        item_code=fields["ITEM_CODE"],
                        description=fields["ITEM_DESCRIPTION"],
                        quantity=quantity,
                        unit_price=unit_price,
                        line_total=total,
                    ),
                ),
                total=total,
            )
            proposal.validate_schema()
        except ValueError as error:
            raise ProposalAdapterError("document could not produce a valid proposal") from error
        return proposal
