"""Contrato reduzido que o LLM pode propor sem controlar proveniencia."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .pdf_ingestion import ExtractedPdf
from .proposal import CREATE_DRAFT_BILL, SCHEMA_VERSION, VendorBillProposal


MODEL_OUTPUT_SCHEMA_VERSION = "vendor-bill-model-output/v1"


class ModelOutputSchemaError(ValueError):
    """Indica output fora do schema sem repetir o valor nao confiavel."""


@lru_cache(maxsize=1)
def _schema_and_validator() -> tuple[dict[str, Any], Draft202012Validator]:
    schema_path = files("tcc_gateway.schemas").joinpath(
        "vendor_bill_model_output_v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return schema, validator


def model_output_schema() -> dict[str, Any]:
    """Retorna uma copia serializavel do schema enviado aos provedores."""

    schema, _ = _schema_and_validator()
    return deepcopy(schema)


def validate_model_output_mapping(value: Mapping[str, Any]) -> None:
    """Valida o output do modelo sem copiar conteudo para a excecao."""

    _, validator = _schema_and_validator()
    errors = sorted(
        validator.iter_errors(dict(value)),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if not errors:
        return

    first = errors[0]
    path = "$"
    for part in first.absolute_path:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    raise ModelOutputSchemaError(
        f"model output schema validation failed at {path} ({first.validator})"
    )


def normalise_model_output(
    value: Mapping[str, Any],
    *,
    producer: str,
    scenario_id: str,
    document: ExtractedPdf,
) -> VendorBillProposal:
    """Injeta metadados confiaveis e produz o contrato completo M2."""

    validate_model_output_mapping(value)
    proposal_value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "action": CREATE_DRAFT_BILL,
        "producer": producer,
        "scenario_id": scenario_id,
        "synthetic_data": True,
        "fiscal_value": False,
        "source": {
            "document_sha256": document.document_sha256,
            "text_sha256": document.text_sha256,
            "page_count": document.page_count,
        },
        **dict(value),
    }
    return VendorBillProposal.from_mapping(proposal_value)
