"""C1-03: proposta preservada e snapshot JSON-2 lido por chaves confiáveis.

Só há leituras. O chamador confiável fornece workflow e observações operacionais,
nunca o documento/modelo. Tipos e hashes não atestam procedência. Este snapshot
não substitui a revalidação sob lock nem o ledger transacional de C1-06.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Context, Decimal, DecimalException, ROUND_HALF_EVEN, localcontext
import re
import unicodedata
from typing import Any, Literal, Protocol

from .action_proposal_v2 import ActionProposalV2, revalidate_action_proposal_v2
from .policy_contracts import (
    CanonicalAction, CanonicalLine, DependencyStatus, PolicyContractError,
    PolicyInput, TrustedPolicyState, TrustedPurchaseLine, TrustedPurchaseOrder,
    TrustedTargetBill,
)


class CanonicalizationError(PolicyContractError):
    """Proposta não canonicalizável; nenhuma execução pode ser autorizada."""


class TrustedStateResolutionError(ValueError):
    """Categoria pública sem registros, payload ou causa bruta do transporte."""

    def __init__(self, category: str) -> None:
        if category not in {
            "DEPENDENCY_UNAVAILABLE", "STATE_INVALID",
            "REFERENCE_NOT_FOUND", "REFERENCE_AMBIGUOUS",
        }:
            raise ValueError("unsupported resolution category")
        self.category = category
        super().__init__("trusted state resolution failed: " + category)


class ReadOnlyOdooCaller(Protocol):
    def call(self, model: str, method: str, *, arguments: Mapping[str, Any]) -> Any: ...


_DECIMAL_CONTEXT = Context(prec=32, rounding=ROUND_HALF_EVEN)
_REFERENCE = re.compile(r"[A-Z0-9][A-Z0-9._ /-]{0,95}\Z")


def _text(value: Any, *, maximum: int = 96, reference: bool = False) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or value.strip() != value:
        raise ValueError("invalid trusted text")
    if any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value):
        raise ValueError("forbidden trusted text formatting")
    normalized = unicodedata.normalize("NFC", value)
    if reference and _REFERENCE.fullmatch(normalized) is None:
        raise ValueError("invalid trusted reference")
    return normalized


def _scale(value: Any) -> int:
    if type(value) is not int or value not in (2, 3, 4):
        raise ValueError("quantity scale must be explicit")
    return value


def _decimal(value: Any, scale: int, *, zero_allowed: bool = False) -> str:
    # Odoo JSON contains floats: convert their decimal spelling once at ingress.
    # Do not round an inexact amount/quantity into an otherwise permitted action.
    if type(value) not in (int, float, str, Decimal):
        raise ValueError("invalid decimal type")
    number = Decimal(str(value))
    if not number.is_finite() or number < 0 or (number == 0 and not zero_allowed):
        raise ValueError("invalid decimal value")
    if number >= Decimal("1000000000000"):
        raise ValueError("decimal outside contract bounds")
    with localcontext(_DECIMAL_CONTEXT):
        scaled = number.quantize(Decimal(1).scaleb(-scale))
        if scaled != number:
            raise ValueError("decimal precision loss")
        # Canonical zero is never signed.
        return format(abs(scaled) if scaled == 0 else scaled, f".{scale}f")


def canonicalize_proposal(
    proposal: ActionProposalV2, *, policy_version: str, quantity_scale: int,
    target_move_id: int | None = None,
) -> CanonicalAction:
    """Mantém argumentos divergentes para a política; não usa labels nem PO.

target_move_id só pode vir do leitor/workflow confiável. A saída do LLM v2
não possui esse campo. Descrição e evidence não são escritos nem autorizam.
"""
    try:
        if type(proposal) is not ActionProposalV2:
            raise ValueError("typed v2 proposal required")
        scale = _scale(quantity_scale)
        with localcontext(_DECIMAL_CONTEXT):
            value = revalidate_action_proposal_v2(proposal).to_mapping()
            post = value["action"] == "POST_VENDOR_BILL"
            if (post and (type(target_move_id) is not int or target_move_id <= 0)) or (
                not post and target_move_id is not None
            ):
                raise ValueError("invalid trusted action target")
            lines = tuple(sorted((CanonicalLine(
                _text(line["item_code"], reference=True),
                _decimal(line["quantity"], scale), _decimal(line["unit_price"], 2),
            ) for line in value["lines"]), key=lambda line: line.item_code))
            return CanonicalAction(
                policy_version=policy_version, action=value["action"],
                executor_mode="POST_APPROVED" if post else "CREATE_DRAFT",
                scenario_id=value["scenario_id"], document_sha256=value["source"]["document_sha256"],
                vendor_ref=_text(value["vendor_ref"], reference=True),
                purchase_order_ref=_text(value["purchase_order_ref"], reference=True),
                document_ref=_text(value["document_ref"], reference=True),
                invoice_date=value["invoice_date"], currency=value["currency"],
                amount=_decimal(value["total"], 2),
                recipient_bank_ref=_text(value["bank_account_ref"], reference=True),
                lines=lines, target_move_id=target_move_id,
            )
    except (AttributeError, TypeError, ValueError, DecimalException):
        raise CanonicalizationError("invalid canonical action proposal") from None


@dataclass(frozen=True, slots=True)
class TrustedWorkflow:
    company_name: str
    company_ref: str
    scenario_id: str
    document_sha256: str
    purchase_order_ref: str
    phase: Literal["DRAFT_INTAKE", "POST_REVIEW"]
    allowed_bank_refs: tuple[str, ...]
    invoice_date_min: str
    invoice_date_max: str
    monetary_tolerance: str
    quantity_scale: int
    target_document_ref: str | None = None

    def __post_init__(self) -> None:
        try:
            _text(self.company_name, maximum=160)
            for value in (self.company_ref, self.purchase_order_ref, *self.allowed_bank_refs):
                _text(value, reference=True)
            if type(self.allowed_bank_refs) is not tuple or len(self.allowed_bank_refs) > 50:
                raise ValueError("invalid bank collection")
            if len(set(self.allowed_bank_refs)) != len(self.allowed_bank_refs):
                raise ValueError("duplicate bank keys")
            if re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,63}", self.scenario_id) is None:
                raise ValueError("invalid scenario")
            if re.fullmatch(r"[0-9a-f]{64}", self.document_sha256) is None:
                raise ValueError("invalid digest")
            _scale(self.quantity_scale)
            if re.fullmatch(r"(0|[1-9][0-9]{0,11})\.[0-9]{2}", self.monetary_tolerance) is None:
                raise ValueError("invalid tolerance")
            for value in (self.invoice_date_min, self.invoice_date_max):
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError("invalid date")
            if self.invoice_date_min > self.invoice_date_max or self.phase not in {"DRAFT_INTAKE", "POST_REVIEW"}:
                raise ValueError("invalid workflow")
            if self.target_document_ref is not None:
                _text(self.target_document_ref, reference=True)
            if self.phase == "POST_REVIEW" and self.target_document_ref is None:
                raise ValueError("post workflow requires trusted target key")
        except (TypeError, ValueError):
            raise PolicyContractError("invalid trusted workflow configuration") from None


@dataclass(frozen=True, slots=True)
class TrustedOperationalStatus:
    """Observação do runtime confiável, não do modelo; sem defaults favoráveis.

O produtor deverá consultar ledger, período contábil e saúde efetivos antes da
execução. Fornecer False/AVAILABLE manualmente só é válido em testes isolados.
"""

    company_ref: str
    scenario_id: str
    document_sha256: str
    purchase_order_ref: str
    duplicate_detected: bool
    accounting_period_open: bool
    dependencies: DependencyStatus


@dataclass(frozen=True, slots=True)
class ResolvedPurchaseLine:
    item_code: str
    purchase_line_id: int
    product_id: int
    uom_id: int
    description: str


@dataclass(frozen=True, slots=True)
class ResolvedTrustedState:
    state: TrustedPolicyState
    company_id: int
    vendor_id: int
    purchase_order_id: int
    lines: tuple[ResolvedPurchaseLine, ...]
    bank_ids: tuple[tuple[str, int], ...]


def _id(value: Any) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("invalid internal record identity")
    return value


def _relation(value: Any) -> int:
    if type(value) is not list or len(value) != 2 or not isinstance(value[1], str):
        raise ValueError("invalid relation representation")
    return _id(value[0])


def _bool(value: Any) -> bool:
    if type(value) is not bool:
        raise ValueError("invalid boolean representation")
    return value


def _company(record: Mapping[str, Any], company_id: int, *, shared: bool = False) -> None:
    value = record["company_id"]
    if shared and value is False:
        return
    if _relation(value) != company_id:
        raise ValueError("foreign company record")


def _rows(
    client: ReadOnlyOdooCaller, model: str, domain: list, fields: list[str], *, limit: int,
) -> list[Mapping[str, Any]]:
    try:
        result = client.call(model, "search_read", arguments={
            "domain": domain, "fields": ["id", *fields], "limit": limit,
            "order": "id asc",
        })
    except Exception:
        raise TrustedStateResolutionError("DEPENDENCY_UNAVAILABLE") from None
    if type(result) is not list or len(result) > limit:
        raise TrustedStateResolutionError("STATE_INVALID")
    ids: set[int] = set()
    for row in result:
        if not isinstance(row, Mapping) or any(key not in row for key in ["id", *fields]):
            raise TrustedStateResolutionError("STATE_INVALID")
        try:
            record_id = _id(row["id"])
        except ValueError:
            raise TrustedStateResolutionError("STATE_INVALID") from None
        if record_id in ids:
            raise TrustedStateResolutionError("REFERENCE_AMBIGUOUS")
        ids.add(record_id)
    return result


def _one(client: ReadOnlyOdooCaller, model: str, domain: list, fields: list[str]) -> Mapping[str, Any]:
    rows = _rows(client, model, domain, fields, limit=2)
    if len(rows) != 1:
        raise TrustedStateResolutionError("REFERENCE_AMBIGUOUS" if rows else "REFERENCE_NOT_FOUND")
    return rows[0]


def _by_id(client: ReadOnlyOdooCaller, model: str, record_id: int, fields: list[str]) -> Mapping[str, Any]:
    row = _one(client, model, [["id", "=", record_id]], fields)
    if row["id"] != record_id:
        raise ValueError("wrong resolved identity")
    return row


def _partner(client: ReadOnlyOdooCaller, record_id: int, company_id: int) -> str:
    row = _by_id(client, "res.partner", record_id, ["ref", "company_id", "active", "supplier_rank"])
    _company(row, company_id)
    if not _bool(row["active"]) or type(row["supplier_rank"]) is not int or row["supplier_rank"] < 1:
        raise ValueError("inactive or non-vendor record")
    return _text(row["ref"], reference=True)


def _currency(client: ReadOnlyOdooCaller, record_id: int) -> str:
    value = _by_id(client, "res.currency", record_id, ["name"])["name"]
    if not isinstance(value, str) or re.fullmatch(r"[A-Z]{3}", value) is None:
        raise ValueError("invalid currency")
    return value


def _read_target(
    client: ReadOnlyOdooCaller, workflow: TrustedWorkflow, *, company_id: int,
    lines: tuple[ResolvedPurchaseLine, ...], policy_version: str,
    trusted_vendor_id: int, trusted_vendor_ref: str, bank_ids: tuple[tuple[str, int], ...],
) -> TrustedTargetBill | None:
    if workflow.target_document_ref is None:
        return None
    row = _one(client, "account.move", [
        ["company_id", "=", company_id], ["move_type", "=", "in_invoice"],
        ["ref", "=", workflow.target_document_ref],
    ], [
        "company_id", "move_type", "state", "partner_id", "currency_id", "partner_bank_id",
        "invoice_date", "ref", "invoice_origin", "amount_total", "auto_post", "invoice_line_ids",
    ])
    _company(row, company_id)
    if row["move_type"] != "in_invoice" or row["ref"] != workflow.target_document_ref or (
        row["invoice_origin"] != workflow.purchase_order_ref or row["auto_post"] != "no"
    ):
        raise ValueError("target outside fixed workflow")
    vendor_id = _relation(row["partner_id"])
    vendor_ref = _partner(client, vendor_id, company_id)
    # Equal business references do not prove internal record identity. Distinct
    # references remain factual differences for the policy; collisions cannot
    # masquerade as the exact PO vendor covered by the approval preimage.
    if vendor_ref == trusted_vendor_ref and vendor_id != trusted_vendor_id:
        raise ValueError("target vendor reference identity collision")
    bank = _by_id(client, "res.partner.bank", _relation(row["partner_bank_id"]), [
        "acc_number", "partner_id", "company_id", "active", "allow_out_payment",
    ])
    _company(bank, company_id)
    if _relation(bank["partner_id"]) != vendor_id or not _bool(bank["active"]):
        raise ValueError("target bank ownership invalid")
    _bool(bank["allow_out_payment"])
    bank_ref = _text(bank["acc_number"], reference=True)
    allowed_id = dict(bank_ids).get(bank_ref)
    if allowed_id is not None and bank["id"] != allowed_id:
        raise ValueError("target bank reference identity collision")
    invoice_ids = row["invoice_line_ids"]
    if type(invoice_ids) is not list or not 1 <= len(invoice_ids) <= 50:
        raise ValueError("invalid target invoice lines")
    wanted = {_id(value) for value in invoice_ids}
    if len(wanted) != len(invoice_ids):
        raise ValueError("duplicate target invoice line")
    stored_lines = _rows(client, "account.move.line", [
        ["id", "in", invoice_ids], ["move_id", "=", row["id"]], ["company_id", "=", company_id],
    ], [
        "company_id", "move_id", "display_type", "purchase_line_id", "product_id",
        "product_uom_id", "quantity", "price_unit", "discount", "tax_ids",
    ], limit=51)
    if {line["id"] for line in stored_lines} != wanted:
        raise ValueError("incomplete target invoice lines")
    by_po_line = {line.purchase_line_id: line for line in lines}
    canonical_lines = []
    for item in stored_lines:
        _company(item, company_id)
        if _relation(item["move_id"]) != row["id"] or item["display_type"] != "product" or (
            _decimal(item["discount"], 2, zero_allowed=True) != "0.00" or item["tax_ids"] != []
        ):
            raise ValueError("target line outside fixed scope")
        link = by_po_line.get(_relation(item["purchase_line_id"]))
        if link is None or (_relation(item["product_id"]), _relation(item["product_uom_id"])) != (
            link.product_id, link.uom_id
        ):
            raise ValueError("target line not linked to trusted PO")
        canonical_lines.append(CanonicalLine(
            link.item_code, _decimal(item["quantity"], workflow.quantity_scale), _decimal(item["price_unit"], 2),
        ))
    action = CanonicalAction(
        policy_version=policy_version, action="POST_VENDOR_BILL", executor_mode="POST_APPROVED",
        scenario_id=workflow.scenario_id, document_sha256=workflow.document_sha256,
        vendor_ref=vendor_ref, purchase_order_ref=workflow.purchase_order_ref,
        document_ref=_text(row["ref"], reference=True), invoice_date=row["invoice_date"],
        currency=_currency(client, _relation(row["currency_id"])), amount=_decimal(row["amount_total"], 2),
        recipient_bank_ref=bank_ref,
        lines=tuple(sorted(canonical_lines, key=lambda line: line.item_code)), target_move_id=row["id"],
    )
    return TrustedTargetBill(row["id"], row["state"], action)


def read_trusted_state(
    client: ReadOnlyOdooCaller, workflow: TrustedWorkflow, operational: TrustedOperationalStatus,
    *, policy_version: str,
) -> ResolvedTrustedState:
    """Não recebe proposta: nenhum argumento do documento seleciona a verdade.

Leituras não são atomicamente consistentes. O add-on terá de repetir a
resolução sob lock, com a identidade restrita e o contexto neutralizado.
"""
    try:
        if type(workflow) is not TrustedWorkflow or type(operational) is not TrustedOperationalStatus:
            raise ValueError("typed trusted context required")
        # Recheck immutable records, including callers bypassing constructors.
        TrustedWorkflow(**{name: getattr(workflow, name) for name in workflow.__dataclass_fields__})
        if (operational.company_ref, operational.scenario_id, operational.document_sha256,
            operational.purchase_order_ref) != (
            workflow.company_ref, workflow.scenario_id, workflow.document_sha256, workflow.purchase_order_ref
        ):
            raise ValueError("operational observation belongs to another workflow")
        _bool(operational.duplicate_detected)
        _bool(operational.accounting_period_open)
        if not isinstance(policy_version, str) or re.fullmatch(r"[a-z][a-z0-9._/-]{0,63}", policy_version) is None:
            raise ValueError("invalid policy version")
        if type(operational.dependencies) is not DependencyStatus or any(
            status not in {"AVAILABLE", "UNAVAILABLE"} for status in operational.dependencies.to_mapping().values()
        ):
            raise ValueError("invalid observed dependency status")
        if operational.dependencies.state != "AVAILABLE":
            raise TrustedStateResolutionError("DEPENDENCY_UNAVAILABLE")
        with localcontext(_DECIMAL_CONTEXT):
            company = _one(client, "res.company", [["name", "=", workflow.company_name]], ["name"])
            if company["name"] != workflow.company_name:
                raise ValueError("wrong company business key")
            company_id = company["id"]
            po = _one(client, "purchase.order", [
                ["name", "=", workflow.purchase_order_ref], ["company_id", "=", company_id],
            ], ["name", "company_id", "partner_id", "currency_id", "state", "amount_total"])
            _company(po, company_id)
            if po["name"] != workflow.purchase_order_ref or po["state"] not in {
                "draft", "sent", "to approve", "purchase", "cancel"
            }:
                raise ValueError("invalid PO state or key")
            vendor_id = _relation(po["partner_id"])
            vendor_ref = _partner(client, vendor_id, company_id)
            currency = _currency(client, _relation(po["currency_id"]))
            po_lines = _rows(client, "purchase.order.line", [
                ["order_id", "=", po["id"]], ["company_id", "=", company_id], ["display_type", "=", False],
            ], [
                "order_id", "company_id", "product_id", "product_uom_id", "display_type", "name",
                "product_qty", "price_unit", "qty_to_invoice", "discount", "tax_ids",
            ], limit=51)
            if not 1 <= len(po_lines) <= 50:
                raise ValueError("invalid PO line count")
            trusted_lines, resolved_lines = [], []
            for item in po_lines:
                _company(item, company_id)
                if _relation(item["order_id"]) != po["id"] or item["display_type"] is not False or (
                    item["tax_ids"] != [] or _decimal(item["discount"], 2, zero_allowed=True) != "0.00"
                ):
                    raise ValueError("PO line outside fixed scope")
                product_id, uom_id = _relation(item["product_id"]), _relation(item["product_uom_id"])
                product = _by_id(client, "product.product", product_id, ["default_code", "company_id", "active", "uom_id"])
                _company(product, company_id, shared=True)
                if not _bool(product["active"]) or _relation(product["uom_id"]) != uom_id:
                    raise ValueError("product inactive or unit conversion required")
                code = _text(product["default_code"], reference=True)
                trusted_lines.append(TrustedPurchaseLine(
                    code, _decimal(item["product_qty"], workflow.quantity_scale),
                    _decimal(item["price_unit"], 2),
                    _decimal(item["qty_to_invoice"], workflow.quantity_scale, zero_allowed=True),
                ))
                resolved_lines.append(ResolvedPurchaseLine(
                    code, item["id"], product_id, uom_id, _text(item["name"], maximum=160),
                ))
            purchase_order = TrustedPurchaseOrder(
                po["name"], vendor_ref, currency, po["state"] == "purchase",
                _decimal(po["amount_total"], 2), tuple(sorted(trusted_lines, key=lambda line: line.item_code)),
            )
            banks = _rows(client, "res.partner.bank", [
                ["acc_number", "in", list(workflow.allowed_bank_refs)], ["company_id", "=", company_id],
                ["partner_id", "=", vendor_id], ["active", "=", True], ["allow_out_payment", "=", True],
            ], ["acc_number", "company_id", "partner_id", "active", "allow_out_payment"], limit=51)
            bank_ids = []
            for bank in banks:
                _company(bank, company_id)
                ref = _text(bank["acc_number"], reference=True)
                if ref not in workflow.allowed_bank_refs or _relation(bank["partner_id"]) != vendor_id or not (
                    _bool(bank["active"]) and _bool(bank["allow_out_payment"])
                ):
                    raise ValueError("bank outside trusted allowlist")
                bank_ids.append((ref, bank["id"]))
            if len({ref for ref, _ in bank_ids}) != len(bank_ids):
                raise TrustedStateResolutionError("REFERENCE_AMBIGUOUS")
            lines = tuple(sorted(resolved_lines, key=lambda line: line.item_code))
            target = _read_target(
                client, workflow, company_id=company_id, lines=lines, policy_version=policy_version,
                trusted_vendor_id=vendor_id, trusted_vendor_ref=vendor_ref, bank_ids=tuple(bank_ids),
            )
            state = TrustedPolicyState(
                workflow.company_ref, workflow.scenario_id, workflow.document_sha256, workflow.phase,
                purchase_order, tuple(sorted(ref for ref, _ in bank_ids)),
                operational.duplicate_detected, workflow.invoice_date_min, workflow.invoice_date_max,
                operational.accounting_period_open, workflow.monetary_tolerance, workflow.quantity_scale,
                operational.dependencies, target,
            )
            return ResolvedTrustedState(state, company_id, vendor_id, po["id"], lines, tuple(sorted(bank_ids)))
    except TrustedStateResolutionError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, DecimalException):
        raise TrustedStateResolutionError("STATE_INVALID") from None


def prepare_policy_input(
    proposal: ActionProposalV2, resolved: ResolvedTrustedState, *, policy_version: str,
    evaluated_at: str, expires_at: str,
) -> PolicyInput:
    """Liga a proposta ao snapshot; não altera sua ação conforme fase/labels."""
    try:
        if type(proposal) is not ActionProposalV2 or type(resolved) is not ResolvedTrustedState:
            raise ValueError("typed proposal and snapshot required")
        state = resolved.state
        if (proposal.scenario_id, proposal.document_sha256) != (state.scenario_id, state.document_sha256):
            raise ValueError("proposal provenance differs from workflow")
        target = state.target_bill
        if target is not None and target.action.policy_version != policy_version:
            raise ValueError("target policy version differs")
        action = canonicalize_proposal(
            proposal, policy_version=policy_version, quantity_scale=state.quantity_scale,
            target_move_id=target.move_id if proposal.action == "POST_VENDOR_BILL" and target else None,
        )
        with localcontext(_DECIMAL_CONTEXT):
            return PolicyInput.from_mapping(PolicyInput(action, state, evaluated_at, expires_at).to_mapping())
    except (AttributeError, TypeError, ValueError, DecimalException):
        raise CanonicalizationError("invalid proposal and trusted state binding") from None
