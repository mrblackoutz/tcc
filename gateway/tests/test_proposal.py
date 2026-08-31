from __future__ import annotations

from copy import deepcopy

import pytest

from tcc_gateway.adapters import (
    DEVELOPMENT_ADAPTER_ID,
    DeterministicDevelopmentAdapter,
    ProposalAdapterError,
)
from tcc_gateway.pdf_ingestion import ExtractedPdf, extract_pdf_text
from tcc_gateway.proposal import VendorBillProposal
from tcc_gateway.proposal_schema import ProposalSchemaError, validate_proposal_mapping
from tcc_gateway.synthetic_pdf import write_m2_synthetic_pdf


def _fixture() -> dict[str, object]:
    return {
        "synthetic_data": True,
        "fiscal_value": False,
        "vendor_ref": "TCC-M1-VENDOR",
        "purchase_order_ref": "TCC-M1-PO-001",
        "invoice_date": "2026-08-31",
        "currency_name": "USD",
        "bank_account": "TCC-SYNTHETIC-BANK-0001",
        "product_code": "TCC-M1-SERVICE",
        "amount": "125.50",
    }


def _proposal(tmp_path) -> VendorBillProposal:
    path = tmp_path / "m2.pdf"
    write_m2_synthetic_pdf(path, _fixture())
    return DeterministicDevelopmentAdapter().propose(extract_pdf_text(path))


def _with_text(document: ExtractedPdf, text: str) -> ExtractedPdf:
    return ExtractedPdf(
        text=text,
        document_sha256=document.document_sha256,
        text_sha256=document.text_sha256,
        page_count=document.page_count,
        byte_count=document.byte_count,
    )


def test_adapter_produces_typed_schema_valid_proposal(tmp_path) -> None:
    proposal = _proposal(tmp_path)
    value = proposal.to_mapping()

    assert proposal.producer == DEVELOPMENT_ADAPTER_ID
    assert proposal.schema_version == "vendor-bill-proposal/v1"
    assert proposal.action == "CREATE_DRAFT_BILL"
    assert proposal.synthetic_data is True
    assert proposal.fiscal_value is False
    assert value["scenario_id"] == "M2-BENIGN-001"
    assert value["document_ref"] == "TCC-M2-NF-001-SEM-VALOR-FISCAL"
    assert value["total"] == "125.50"
    assert value["lines"] == [
        {
            "item_code": "TCC-M1-SERVICE",
            "description": "SERVICO SINTETICO M2 - SEM VALOR FISCAL",
            "quantity": "1.00",
            "unit_price": "125.50",
            "line_total": "125.50",
        }
    ]
    assert VendorBillProposal.from_mapping(value) == proposal


@pytest.mark.parametrize(
    "mutator",
    [
        lambda text: text.replace(
            "TOTAL: 125.50", "TOTAL: 125.50\nTOTAL: 125.50"
        ),
        lambda text: text.replace("TOTAL: 125.50\n", ""),
        lambda text: text.replace("TOTAL: 125.50", "UNKNOWN: 125.50"),
        lambda text: text.replace("TOTAL: 125.50", "TOTAL=125.50"),
        lambda text: text.replace("TOTAL: 125.50", "TOTAL: 126.50"),
    ],
)
def test_adapter_rejects_duplicate_missing_unknown_malformed_or_unbalanced_fields(
    tmp_path, mutator
) -> None:
    path = tmp_path / "m2.pdf"
    write_m2_synthetic_pdf(path, _fixture())
    document = extract_pdf_text(path)

    with pytest.raises(ProposalAdapterError):
        DeterministicDevelopmentAdapter().propose(
            _with_text(document, mutator(document.text))
        )


@pytest.mark.parametrize(
    ("mutation", "validator"),
    [
        (lambda value: value.update({"unexpected": True}), "additionalProperties"),
        (lambda value: value.pop("vendor_ref"), "required"),
        (lambda value: value.update({"invoice_date": "31/08/2026"}), "format"),
        (lambda value: value.update({"currency": "usd"}), "pattern"),
        (lambda value: value.update({"total": 125.50}), "type"),
    ],
)
def test_schema_rejects_extra_missing_or_invalid_fields(tmp_path, mutation, validator) -> None:
    value = deepcopy(_proposal(tmp_path).to_mapping())
    mutation(value)

    with pytest.raises(ProposalSchemaError, match=validator):
        validate_proposal_mapping(value)


def test_schema_error_does_not_copy_invalid_value(tmp_path) -> None:
    marker = "DO-NOT-ECHO-THIS-VALUE"
    value = deepcopy(_proposal(tmp_path).to_mapping())
    value["currency"] = marker

    with pytest.raises(ProposalSchemaError) as captured:
        validate_proposal_mapping(value)

    assert marker not in str(captured.value)
