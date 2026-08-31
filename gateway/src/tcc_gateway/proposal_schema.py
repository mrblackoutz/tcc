"""Validacao saneada do contrato JSON de proposta de conta de fornecedor."""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


class ProposalSchemaError(ValueError):
    """Indica que uma proposta nao satisfaz o contrato versionado."""


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema_path = files("tcc_gateway.schemas").joinpath(
        "vendor_bill_proposal_v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_proposal_mapping(value: Mapping[str, Any]) -> None:
    """Valida sem copiar valores potencialmente nao confiaveis para o erro."""

    errors = sorted(
        _validator().iter_errors(dict(value)),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if not errors:
        return

    first = errors[0]
    path = "$"
    for part in first.absolute_path:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    raise ProposalSchemaError(
        f"proposal schema validation failed at {path} ({first.validator})"
    )
