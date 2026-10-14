"""DEC-053: observação administrativa advisory ligada à ação candidata.

Integridade e tipos não autenticam o produtor ou administrador SQL. O binding
e a fase vêm da integração confiável, nunca da proposta ou desta observação.
O kernel continua responsável pela revalidação transacional sob lock.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
import hashlib
from importlib.resources import files
import json
import re
from typing import Any
import unicodedata

from jsonschema import Draft202012Validator, FormatChecker

from .action_proposal_v2 import ActionProposalV2
from .policy_contracts import DependencyStatus, PolicyInput, TrustedPolicyState
from .state import canonical_json_bytes, canonical_json_sha256
from .trusted_resolution import (
    ReadOnlyOdooCaller, ResolvedPurchaseLine, ResolvedTrustedState,
    TrustedOperationalStatus, TrustedStateResolutionError, TrustedWorkflow,
    prepare_policy_input, read_trusted_state,
)


OBSERVATION_VERSION = "registered-operational-observation/v1"
_DOMAIN = b"tcc-operational-observation/v1\0"
_IDS = ("company_id", "executor_user_id", "vendor_id", "purchase_order_id", "journal_id")
_MAX_INPUT_BYTES = 65_536
_MAX_INPUT_DEPTH = 8
_MAX_INPUT_NODES = 4_096


class OperationalObservationError(ValueError):
    """Erro finito, sem payload, referência, causa de transporte ou segredo."""


def _strict_id(value: Any) -> None:
    if type(value) is not int or value <= 0:
        raise OperationalObservationError("invalid operational observation identity")


def _hash(value: Any, *, commit: bool = False) -> None:
    pattern = r"[0-9a-f]{40}" if commit else r"sha256:[0-9a-f]{64}"
    if type(value) is not str or re.fullmatch(pattern, value) is None:
        raise OperationalObservationError("invalid operational observation digest")


@dataclass(frozen=True, slots=True)
class ObservationBinding:
    """Configuração independente obrigatória, não copiada da observação recebida."""

    registration_id: int
    registration_sha256: str
    company_id: int
    executor_user_id: int
    vendor_id: int
    purchase_order_id: int
    journal_id: int
    code_commit: str
    code_sha256: str
    configuration_sha256: str
    purchase_line_ids: tuple[int, ...]
    allowed_bank_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        for name in ("registration_id", *_IDS):
            _strict_id(getattr(self, name))
        for name in ("registration_sha256", "code_sha256", "configuration_sha256"):
            _hash(getattr(self, name))
        _hash(self.code_commit, commit=True)
        for name in ("purchase_line_ids", "allowed_bank_ids"):
            value = getattr(self, name)
            if type(value) is not tuple or not 1 <= len(value) <= 50:
                raise OperationalObservationError("invalid independent registered identities")
            for item in value:
                _strict_id(item)
            if value != tuple(sorted(set(value))):
                raise OperationalObservationError("independent identities must be sorted and unique")

    def to_mapping(self) -> dict[str, Any]:
        self.__post_init__()
        return {name: list(getattr(self, name)) if name in {"purchase_line_ids", "allowed_bank_ids"}
                else getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ObservationBinding:
        """JSON independente fechado; não converter escalares nem aceitar extras."""
        try:
            if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
                raise ValueError("closed independent configuration required")
            fields = dict(value)
            for name in ("purchase_line_ids", "allowed_bank_ids"):
                if type(fields[name]) is not list:
                    raise ValueError("JSON ID list required")
                fields[name] = tuple(fields[name])
            return cls(**fields)
        except (AttributeError, KeyError, TypeError, ValueError):
            raise OperationalObservationError("invalid independent observation configuration") from None


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(files("tcc_gateway.schemas").joinpath(
        "registered_operational_observation_v1.schema.json",
    ).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _json_shape(value: Any) -> None:
    # Validate bounds before schema traversal/hash serialization. Ancestors,
    # rather than global visited objects, reject cycles but allow shared leaves.
    ancestors: set[int] = set()
    nodes, scalar_bytes = 0, 0

    def walk(item: Any, depth: int) -> None:
        nonlocal nodes, scalar_bytes
        nodes += 1
        if depth > _MAX_INPUT_DEPTH or nodes > _MAX_INPUT_NODES:
            raise ValueError("input traversal limit")
        if type(item) in (dict, list):
            identity = id(item)
            if identity in ancestors:
                raise ValueError("cyclic input")
            ancestors.add(identity)
            try:
                if type(item) is dict:
                    for key, child in item.items():
                        if type(key) is not str:
                            raise ValueError("invalid object key")
                        walk(key, depth + 1)
                        walk(child, depth + 1)
                else:
                    for child in item:
                        walk(child, depth + 1)
            finally:
                ancestors.remove(identity)
        elif type(item) is str:
            if len(item) > _MAX_INPUT_BYTES:
                raise ValueError("input string limit")
            scalar_bytes += len(item.encode("utf-8"))
            if scalar_bytes > _MAX_INPUT_BYTES:
                raise ValueError("input byte limit")
            if (item.strip() != item or unicodedata.normalize("NFC", item) != item
                    or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in item)):
                raise ValueError("noncanonical text")
        elif item is not None and type(item) not in (bool, int):
            # The observation has no floating-point field. JSON Schema's
            # integer accepts 1.0, so reject it before validation.
            raise ValueError("noncanonical scalar")

    walk(value, 0)
    if len(canonical_json_bytes(value)) > _MAX_INPUT_BYTES:
        raise ValueError("canonical input byte limit")


@dataclass(frozen=True, slots=True)
class RegisteredOperationalObservation:
    """Detached JSON bytes; consumers parse and recheck every trust boundary."""

    canonical_bytes: bytes

    def to_mapping(self) -> dict[str, Any]:
        if type(self.canonical_bytes) is not bytes or len(self.canonical_bytes) > _MAX_INPUT_BYTES:
            raise OperationalObservationError("invalid operational observation representation")
        try:
            value = json.loads(self.canonical_bytes)
            _json_shape(value)
            if type(value) is not dict or canonical_json_bytes(value) != self.canonical_bytes:
                raise ValueError("noncanonical representation")
            return value
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise OperationalObservationError("invalid operational observation representation") from None


def parse_registered_observation(
    value: Mapping[str, Any], binding: ObservationBinding,
) -> RegisteredOperationalObservation:
    """Valida forma fechada, integridade e configuração independente, sem reparo."""
    try:
        if not isinstance(value, Mapping) or type(binding) is not ObservationBinding:
            raise ValueError("typed independent binding required")
        ObservationBinding.from_mapping(binding.to_mapping())
        value = dict(value)
        _json_shape(value)
        if next(_validator().iter_errors(value), None) is not None:
            raise ValueError("schema invalid")
        scope, facts = value["scope"], value["facts"]
        for name in _IDS:
            _strict_id(scope[name])
            if scope[name] != getattr(binding, name):
                raise ValueError("identity binding differs")
        if value["registration"] != {
            "registration_id": binding.registration_id,
            "registration_sha256": binding.registration_sha256,
        } or value["provenance"] != {
            name: getattr(binding, name) for name in ("code_commit", "code_sha256", "configuration_sha256")
        }:
            raise ValueError("registration provenance differs")
        _strict_id(value["registration"]["registration_id"])
        if type(scope["quantity_scale"]) is not int:
            raise ValueError("scale must be strict integer")
        for name in ("purchase_line_ids", "allowed_bank_ids"):
            for item in scope[name]:
                _strict_id(item)
            if scope[name] != sorted(set(scope[name])):
                raise ValueError("IDs must be sorted and unique")
            if scope[name] != list(getattr(binding, name)):
                raise ValueError("registered identity list differs from independent configuration")
        target = scope["target_move_id"]
        if scope["executor_mode"] == "CREATE_DRAFT":
            if target is not None:
                raise ValueError("CREATE cannot select a target")
        else:
            _strict_id(target)
        if scope["invoice_date_min"] > scope["invoice_date_max"]:
            raise ValueError("invalid date window")
        if facts["duplicate_detected"] != (facts["document_duplicate"] or facts["reference_duplicate"]):
            raise ValueError("duplicate facts disagree")
        preimage = {name: item for name, item in value.items() if name != "observation_sha256"}
        digest = "sha256:" + hashlib.sha256(_DOMAIN + canonical_json_bytes(preimage)).hexdigest()
        if value["observation_sha256"] != digest:
            raise ValueError("observation integrity differs")
        return RegisteredOperationalObservation(canonical_json_bytes(value))
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
        raise OperationalObservationError("invalid registered operational observation") from None


def _dependencies(value: DependencyStatus) -> DependencyStatus:
    if type(value) is not DependencyStatus or any(
        type(item) is not str or item not in {"AVAILABLE", "UNAVAILABLE"}
        for item in value.to_mapping().values()
    ):
        raise OperationalObservationError("invalid supervisor dependency status")
    return DependencyStatus(**value.to_mapping())


def _merge_dependencies(value: DependencyStatus, preflight: Mapping[str, str]) -> DependencyStatus:
    value = _dependencies(value)
    return DependencyStatus(
        "AVAILABLE" if value.state == preflight["state"] == "AVAILABLE" else "UNAVAILABLE",
        value.policy,
        "AVAILABLE" if value.audit == preflight["audit"] == "AVAILABLE" else "UNAVAILABLE",
    )


def _workflow(value: TrustedWorkflow) -> TrustedWorkflow:
    if type(value) is not TrustedWorkflow:
        raise OperationalObservationError("typed trusted workflow required")
    return TrustedWorkflow(**{name: getattr(value, name) for name in value.__dataclass_fields__})


def _scope_context(
    workflow: TrustedWorkflow, resolved: ResolvedTrustedState,
    observation: RegisteredOperationalObservation, binding: ObservationBinding,
    dependencies: DependencyStatus, *, policy_version: str,
) -> None:
    if type(resolved) is not ResolvedTrustedState or type(resolved.state) is not TrustedPolicyState:
        raise ValueError("typed observed snapshot required")
    value = parse_registered_observation(observation.to_mapping(), binding).to_mapping()
    scope, facts, state = value["scope"], value["facts"], resolved.state
    TrustedPolicyState.from_mapping(state.to_mapping())
    _workflow(workflow)
    dependencies = _merge_dependencies(dependencies, value["preflight"])
    if state.dependencies != dependencies or (
        state.duplicate_detected, state.accounting_period_open
    ) != (facts["duplicate_detected"], facts["accounting_period_open"]):
        raise ValueError("operational state differs")
    if (resolved.company_id, resolved.vendor_id, resolved.purchase_order_id) != (
        binding.company_id, binding.vendor_id, binding.purchase_order_id,
    ):
        raise ValueError("resolved identity differs")
    for item in (resolved.company_id, resolved.vendor_id, resolved.purchase_order_id):
        _strict_id(item)
    if type(resolved.lines) is not tuple or any(type(line) is not ResolvedPurchaseLine for line in resolved.lines):
        raise ValueError("typed resolved lines required")
    for line in resolved.lines:
        for item in (line.purchase_line_id, line.product_id, line.uom_id):
            _strict_id(item)
    line_ids = [line.purchase_line_id for line in resolved.lines]
    if sorted(line_ids) != scope["purchase_line_ids"] or len(set(line_ids)) != len(line_ids):
        raise ValueError("registered lines differ")
    if tuple(line.item_code for line in resolved.lines) != tuple(line.item_code for line in state.purchase_order.lines):
        raise ValueError("resolved line keys differ")
    if type(resolved.bank_ids) is not tuple or any(type(item) is not tuple or len(item) != 2 for item in resolved.bank_ids):
        raise ValueError("typed resolved banks required")
    for ref, bank_id in resolved.bank_ids:
        _strict_id(bank_id)
        if ref not in workflow.allowed_bank_refs or bank_id not in scope["allowed_bank_ids"]:
            raise ValueError("bank outside registered scope")
    refs = tuple(ref for ref, _ in resolved.bank_ids)
    if refs != tuple(sorted(set(refs))) or refs != state.allowed_bank_refs:
        raise ValueError("resolved bank keys differ")
    if len({item[1] for item in resolved.bank_ids}) != len(resolved.bank_ids):
        raise ValueError("resolved bank identities repeat")
    for name in ("scenario_id", "document_sha256", "invoice_date_min", "invoice_date_max", "monetary_tolerance", "quantity_scale"):
        if scope[name] != getattr(workflow, name) or scope[name] != getattr(state, name):
            raise ValueError("registered workflow limits differ")
    if (scope["policy_version"] != policy_version or state.phase != workflow.phase
            or state.company_ref != workflow.company_ref
            or state.purchase_order.purchase_order_ref != workflow.purchase_order_ref):
        raise ValueError("trusted phase or policy differs")
    if scope["executor_mode"] == "POST_APPROVED":
        if state.target_bill is None or scope["target_move_id"] != state.target_bill.move_id:
            raise ValueError("registered POST origin differs")
    elif scope["target_move_id"] is not None:
        raise ValueError("unexpected CREATE target")


@dataclass(frozen=True, slots=True)
class ObservedTrustedState:
    """Contexto transitório: conserva observação, resolução, binding e supervisor."""

    workflow: TrustedWorkflow
    resolved: ResolvedTrustedState
    observation: RegisteredOperationalObservation
    binding: ObservationBinding
    dependencies: DependencyStatus
    policy_version: str
    _context_sha256: str = field(init=False, repr=False)

    def _mapping(self) -> dict[str, Any]:
        resolved = self.resolved
        return {
            "workflow": {name: getattr(self.workflow, name) for name in self.workflow.__dataclass_fields__},
            "resolved": {"state": resolved.state.to_mapping(), "company_id": resolved.company_id,
                         "vendor_id": resolved.vendor_id, "purchase_order_id": resolved.purchase_order_id,
                         "lines": [{name: getattr(line, name) for name in line.__dataclass_fields__} for line in resolved.lines],
                         "bank_ids": resolved.bank_ids},
            "observation": self.observation.to_mapping(), "binding": self.binding.to_mapping(),
            "dependencies": self.dependencies.to_mapping(), "policy_version": self.policy_version,
        }

    def __post_init__(self) -> None:
        try:
            if type(self.observation) is not RegisteredOperationalObservation:
                raise ValueError("typed observation required")
            _scope_context(self.workflow, self.resolved, self.observation, self.binding,
                           self.dependencies, policy_version=self.policy_version)
            object.__setattr__(self, "_context_sha256", canonical_json_sha256(self._mapping()))
        except (AttributeError, KeyError, TypeError, ValueError):
            raise OperationalObservationError("invalid observed trusted context") from None


def read_observed_trusted_state(
    client: ReadOnlyOdooCaller, workflow: TrustedWorkflow,
    observation: RegisteredOperationalObservation | Mapping[str, Any], binding: ObservationBinding,
    *, dependencies: DependencyStatus, policy_version: str,
) -> ObservedTrustedState:
    """Leituras existentes recebem status apenas derivado da observação validada.

Estado indisponível aborta a leitura; política/auditoria indisponíveis permanecem
na política e produzem DENY. Nenhum preflight melhora status do supervisor.
"""
    try:
        workflow = _workflow(workflow)
        dependencies = _dependencies(dependencies)
        value = observation.to_mapping() if type(observation) is RegisteredOperationalObservation else observation
        parsed = parse_registered_observation(value, binding)
        value = parsed.to_mapping()
        merged = _merge_dependencies(dependencies, value["preflight"])
        resolved = read_trusted_state(client, workflow, TrustedOperationalStatus(
            workflow.company_ref, workflow.scenario_id, workflow.document_sha256, workflow.purchase_order_ref,
            value["facts"]["duplicate_detected"], value["facts"]["accounting_period_open"], merged,
        ), policy_version=policy_version)
        return ObservedTrustedState(workflow, resolved, parsed, ObservationBinding.from_mapping(binding.to_mapping()),
                                    dependencies, policy_version)
    except TrustedStateResolutionError:
        raise
    except Exception:
        # This gateway boundary can encounter transport exceptions with raw
        # endpoint/body details. Never return them as favorable facts or echo
        # their cause. It does not intercept the Odoo transactional DB kernel.
        raise OperationalObservationError("invalid observed trusted state handoff") from None


def prepare_observed_policy_input(
    proposal: ActionProposalV2, observed: ObservedTrustedState, *, policy_version: str,
    evaluated_at: str, expires_at: str,
) -> PolicyInput:
    """Revalida snapshot e toda ação; não escolhe fase, alvo nem corrige proposta."""
    try:
        if type(observed) is not ObservedTrustedState or observed.policy_version != policy_version:
            raise ValueError("observed candidate-bound context required")
        _scope_context(observed.workflow, observed.resolved, observed.observation, observed.binding,
                       observed.dependencies, policy_version=policy_version)
        if canonical_json_sha256(observed._mapping()) != observed._context_sha256:
            raise ValueError("observed immutable context changed")
        policy_input = prepare_policy_input(proposal, observed.resolved, policy_version=policy_version,
                                            evaluated_at=evaluated_at, expires_at=expires_at)
        scope = observed.observation.to_mapping()["scope"]
        action = policy_input.action
        if (action.action_hash, action.executor_mode, action.document_ref, action.invoice_date, action.target_move_id) != (
            scope["action_sha256"], scope["executor_mode"], scope["document_ref"], scope["invoice_date"], scope["target_move_id"],
        ):
            raise ValueError("candidate action differs from observation")
        observed_at = observed.observation.to_mapping()["observed_at"]
        if datetime.fromisoformat(observed_at.replace("Z", "+00:00")) > datetime.fromisoformat(evaluated_at.replace("Z", "+00:00")):
            raise ValueError("observation is later than evaluation")
        return policy_input
    except (AttributeError, KeyError, TypeError, ValueError):
        raise OperationalObservationError("invalid observed candidate policy binding") from None
