from __future__ import annotations

from copy import deepcopy

import pytest

from tcc_gateway.model_output import (
    ModelOutputSchemaError,
    model_output_schema,
    normalise_model_output,
    validate_model_output_mapping,
)
from tcc_gateway.pdf_ingestion import ExtractedPdf


def _document() -> ExtractedPdf:
    return ExtractedPdf(
        text="DOCUMENTO SINTETICO - SEM VALOR FISCAL",
        document_sha256="a" * 64,
        text_sha256="b" * 64,
        page_count=1,
        byte_count=100,
    )


def _model_output() -> dict[str, object]:
    return {
        "vendor_ref": "TCC-VENDOR-001",
        "purchase_order_ref": "TCC-PO-001",
        "document_ref": "TCC-NF-001-SEM-VALOR-FISCAL",
        "invoice_date": "2026-08-31",
        "currency": "BRL",
        "bank_account_ref": "TCC-BANK-001",
        "lines": [
            {
                "item_code": "TCC-SERVICE-001",
                "description": "SERVICO SINTETICO SEM VALOR FISCAL",
                "quantity": "1.00",
                "unit_price": "125.50",
                "line_total": "125.50",
            }
        ],
        "total": "125.50",
    }


def test_model_schema_excludes_trusted_provenance_fields() -> None:
    schema = model_output_schema()

    assert schema["additionalProperties"] is False
    assert "producer" not in schema["properties"]
    assert "scenario_id" not in schema["properties"]
    assert "source" not in schema["properties"]
    assert "synthetic_data" not in schema["properties"]


def test_normalisation_injects_trusted_provenance() -> None:
    proposal = normalise_model_output(
        _model_output(),
        producer="ollama-chat/v1",
        scenario_id="G3A-BENIGN-001",
        document=_document(),
    )

    assert proposal.producer == "ollama-chat/v1"
    assert proposal.scenario_id == "G3A-BENIGN-001"
    assert proposal.source.document_sha256 == "a" * 64
    assert proposal.synthetic_data is True
    assert proposal.fiscal_value is False


def test_model_schema_rejects_extra_trusted_field_without_echo() -> None:
    marker = "DO-NOT-ECHO-MODEL-OUTPUT"
    value = deepcopy(_model_output())
    value["producer"] = marker

    with pytest.raises(ModelOutputSchemaError) as captured:
        validate_model_output_mapping(value)

    assert marker not in str(captured.value)
