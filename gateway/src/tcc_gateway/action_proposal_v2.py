"""Contrato v2 pré-freeze: ação escolhida pelo LLM, proveniência pelo gateway.

Não executa ações e não converte saída v1 em ação crítica. O v1 de M2/G3c
permanece imutável; adapters científicos precisarão optar explicitamente pelo
v2 para ambos C0/C1 antes do piloto.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
from decimal import Context, Decimal, DecimalException, ROUND_HALF_UP, localcontext
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker

from .pdf_ingestion import ExtractedPdf
from .proposal import (
    CREATE_DRAFT_BILL, SCHEMA_VERSION, ProposalSource, VendorBillLineProposal,
    VendorBillProposal,
)
from .proposal_schema import ProposalSchemaError


ACTION_MODEL_OUTPUT_SCHEMA_VERSION = "vendor-bill-action-output/v2"
ACTION_PROPOSAL_SCHEMA_VERSION = "vendor-bill-action-proposal/v2"
POST_VENDOR_BILL = "POST_VENDOR_BILL"
Action = Literal["CREATE_DRAFT_BILL", "POST_VENDOR_BILL"]
_EVIDENCE_FIELDS = frozenset({
    "action", "vendor_ref", "purchase_order_ref", "document_ref",
    "invoice_date", "currency", "bank_account_ref", "lines", "total",
})


class ActionProposalSchemaError(ValueError):
    """Contrato inválido; a exceção nunca contém valores do documento."""


@lru_cache(maxsize=2)
def _schema_and_validator(name: str) -> tuple[dict[str, Any], Draft202012Validator]:
    if name not in {
        "vendor_bill_action_output_v2.schema.json",
        "vendor_bill_action_proposal_v2.schema.json",
    }:
        raise ActionProposalSchemaError("unsupported action schema resource")
    path = files("tcc_gateway.schemas").joinpath(name)
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema, Draft202012Validator(schema, format_checker=FormatChecker())


def _validate(value: Mapping[str, Any], name: str) -> None:
    if not isinstance(value, Mapping):
        raise ActionProposalSchemaError("action proposal must be a JSON object")
    _, validator = _schema_and_validator(name)
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
    raise ActionProposalSchemaError(
        f"action proposal schema validation failed at {path} ({first.validator})"
    )


def action_model_output_schema() -> dict[str, Any]:
    """Cópia do contrato exato a fornecer ao modelo no fluxo científico."""

    schema, _ = _schema_and_validator("vendor_bill_action_output_v2.schema.json")
    return deepcopy(schema)


def validate_action_model_output(value: Mapping[str, Any]) -> None:
    _validate(value, "vendor_bill_action_output_v2.schema.json")


def validate_action_proposal_mapping(value: Mapping[str, Any]) -> None:
    _validate(value, "vendor_bill_action_proposal_v2.schema.json")


@dataclass(frozen=True, slots=True)
class EvidenceSpan:
    field: str
    source_span: str

    def __post_init__(self) -> None:
        if not isinstance(self.field, str) or self.field not in _EVIDENCE_FIELDS:
            raise ActionProposalSchemaError("unsupported evidence field")
        if not isinstance(self.source_span, str) or not 1 <= len(self.source_span) <= 200:
            raise ActionProposalSchemaError("invalid evidence span length")
        if unicodedata.normalize("NFC", self.source_span) != self.source_span:
            raise ActionProposalSchemaError("evidence span must be NFC-normalised")
        if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in self.source_span):
            raise ActionProposalSchemaError("evidence span contains forbidden formatting")

    def to_mapping(self) -> dict[str, str]:
        return {"field": self.field, "source_span": self.source_span}


@dataclass(frozen=True, slots=True)
class ActionProposalV2:
    """Ação v2 e campos financeiros validados; nunca autorização de execução."""

    action: Action
    _bill_fields: VendorBillProposal = field(repr=False)
    evidence: tuple[EvidenceSpan, ...] = ()
    schema_version: str = ACTION_PROPOSAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.action, str) or self.action not in {CREATE_DRAFT_BILL, POST_VENDOR_BILL}:
            raise ActionProposalSchemaError("unsupported proposed action")
        if self.schema_version != ACTION_PROPOSAL_SCHEMA_VERSION:
            raise ActionProposalSchemaError("unsupported action proposal version")
        if not isinstance(self._bill_fields, VendorBillProposal):
            raise ActionProposalSchemaError("validated financial fields are required")
        try:
            self._bill_fields.validate_schema()
        except ProposalSchemaError:
            raise ActionProposalSchemaError("invalid financial action fields") from None
        if type(self.evidence) is not tuple or len(self.evidence) > 8:
            raise ActionProposalSchemaError("evidence spans must be a bounded tuple")
        if any(not isinstance(item, EvidenceSpan) for item in self.evidence):
            raise ActionProposalSchemaError("evidence spans must be typed")

    @property
    def scenario_id(self) -> str:
        return self._bill_fields.scenario_id

    @property
    def document_sha256(self) -> str:
        return self._bill_fields.source.document_sha256

    def to_mapping(self) -> dict[str, Any]:
        value = self._bill_fields.to_mapping()
        value["schema_version"] = self.schema_version
        value["action"] = self.action
        value["evidence"] = [item.to_mapping() for item in self.evidence]
        return value

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ActionProposalV2:
        validate_action_proposal_mapping(value)
        # Reutiliza a validação semântica de dinheiro/linhas do v1 sem expor o
        # campo `action` v1 ao modelo ou inferir ação do manifesto.
        financial_value = dict(value)
        financial_value.pop("evidence")
        financial_value["schema_version"] = SCHEMA_VERSION
        financial_value["action"] = CREATE_DRAFT_BILL
        try:
            bill_fields = VendorBillProposal.from_mapping(financial_value)
        except (ProposalSchemaError, TypeError, ValueError):
            raise ActionProposalSchemaError("invalid financial action fields") from None
        evidence = tuple(
            EvidenceSpan(field=item["field"], source_span=item["source_span"])
            for item in value["evidence"]
        )
        return cls(action=value["action"], _bill_fields=bill_fields, evidence=evidence)


def normalise_action_model_output(
    value: Mapping[str, Any],
    *,
    producer: str,
    scenario_id: str,
    document: ExtractedPdf,
) -> ActionProposalV2:
    """Injeta somente metadata confiável; `action` vem exclusivamente do modelo."""

    validate_action_model_output(value)
    proposal_value: dict[str, Any] = {
        "schema_version": ACTION_PROPOSAL_SCHEMA_VERSION,
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
    proposal_value.setdefault("evidence", [])
    return ActionProposalV2.from_mapping(proposal_value)


def revalidate_action_proposal_v2(proposal: ActionProposalV2) -> ActionProposalV2:
    """Revalida a entrada tipada sem arredondar uma adulteração para aceitá-la.

    ``frozen=True`` evita mutação acidental, não constitui fronteira de segurança.
    Os consumidores repetem a validação antes da serialização, que formata dinheiro
    com duas casas. Não compara fatos com PO, workflow ou rótulos do dataset.
    """
    try:
        if type(proposal) is not ActionProposalV2:
            raise ValueError("exact v2 type required")
        bill = proposal._bill_fields
        if type(bill) is not VendorBillProposal or type(bill.source) is not ProposalSource:
            raise ValueError("exact financial types required")
        if any(type(getattr(bill, name)) is not str for name in (
            "producer", "scenario_id", "vendor_ref", "purchase_order_ref", "document_ref",
            "currency", "bank_account_ref", "schema_version", "action",
        )) or type(bill.invoice_date) is not date or type(bill.total) is not Decimal:
            raise ValueError("invalid financial field type")
        source = bill.source
        if (type(source.document_sha256) is not str or type(source.text_sha256) is not str
                or type(source.page_count) is not int):
            raise ValueError("invalid source field type")
        if type(bill.lines) is not tuple or not 1 <= len(bill.lines) <= 50:
            raise ValueError("invalid line collection")
        if type(proposal.evidence) is not tuple or len(proposal.evidence) > 8:
            raise ValueError("invalid evidence collection")
        if type(proposal.action) is not str or type(proposal.schema_version) is not str:
            raise ValueError("invalid action type")
        with localcontext(Context(prec=32, rounding=ROUND_HALF_UP)):
            source.__post_init__()
            for line in bill.lines:
                if (type(line) is not VendorBillLineProposal or type(line.item_code) is not str
                        or type(line.description) is not str or any(
                            type(getattr(line, name)) is not Decimal
                            for name in ("quantity", "unit_price", "line_total")
                        )):
                    raise ValueError("invalid line type")
                line.__post_init__()
            for span in proposal.evidence:
                if (type(span) is not EvidenceSpan or type(span.field) is not str
                        or type(span.source_span) is not str):
                    raise ValueError("invalid evidence type")
                span.__post_init__()
            bill.__post_init__()
            proposal.__post_init__()
            return ActionProposalV2.from_mapping(proposal.to_mapping())
    except (AttributeError, TypeError, ValueError, DecimalException):
        raise ActionProposalSchemaError("invalid typed v2 action proposal") from None
