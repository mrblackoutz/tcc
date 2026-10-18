# SPDX-License-Identifier: LGPL-3.0-or-later
"""Independent, bounded structural preflight for capability-command/v1.

These checks do not authenticate policy, workflow, approval or idempotency.
The scaffold must remain unable to apply effects until server-side revalidation,
approval verification and transactional auditing are implemented.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Context, Decimal, DecimalException, ROUND_HALF_UP, localcontext
import hashlib
import json
import re
from types import MappingProxyType
import unicodedata
from typing import Any


MAX_COMMAND_BYTES = 65_536
MAX_COMMAND_DEPTH = 8
COMMAND_VERSION = "capability-command/v1"
DECISION_VERSION = "policy-decision/v1"
CANONICALIZATION_VERSION = "canon/v1"
ACTION_SCHEMA_VERSION = "vendor-bill-action-proposal/v2"
_CENT = Decimal("0.01")

TEXT_PATTERNS = MappingProxyType({
    "reference": r"^[A-Z0-9][A-Z0-9._ /-]*$",
    "scenarioId": r"^[A-Z0-9][A-Z0-9._-]{0,63}$",
    "version": r"^[a-z][a-z0-9._/-]{0,63}$",
    "digest": r"^sha256:[0-9a-f]{64}$",
    "rawDigest": r"^[0-9a-f]{64}$",
    "money": r"^(0|[1-9][0-9]{0,11})\.[0-9]{2}$",
    "quantity": r"^(0|[1-9][0-9]{0,5})\.[0-9]{2,4}$",
    "utcTime": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z$",
    "currency": r"^[A-Z]{3}$",
})
REQUIRED_FIELDS = MappingProxyType({
    "capabilityCommand": frozenset({"schema_version", "action", "policy_decision", "idempotency_key"}),
    "canonicalAction": frozenset({
        "canonicalization_version", "action_schema_version", "policy_version", "action", "executor_mode",
        "scenario_id", "document_sha256", "vendor_ref", "purchase_order_ref", "document_ref",
        "invoice_date", "currency", "amount", "recipient_bank_ref", "lines",
    }),
    "canonicalLine": frozenset({"item_code", "quantity", "unit_price"}),
    "policyDecision": frozenset({
        "schema_version", "decision", "reason_codes", "proposed_action_hash", "input_sha256",
        "policy_version", "allowed_executor", "deny_class", "evaluated_at", "expires_at",
    }),
    "approvalFixture": frozenset({
        "fixture_id", "scenario_id", "approver_ref", "decision", "canonical_action_hash", "nonce",
        "issued_at", "expires_at", "key_id", "signature",
    }),
})
OPTIONAL_FIELDS = MappingProxyType({
    "capabilityCommand": frozenset({"approval"}),
    "canonicalAction": frozenset({"target_move_id"}),
    "canonicalLine": frozenset(), "policyDecision": frozenset(), "approvalFixture": frozenset(),
})


class ExecutorContractError(ValueError):
    """Categorized failure with no external field, value or signature echoed."""


@dataclass(frozen=True, slots=True)
class ValidatedCommand:
    """Only immutable, non-secret metadata escapes the structural preflight."""

    action_hash: str
    executor_mode: str
    scenario_id: str
    document_sha256: str
    policy_version: str


def _invalid() -> None:
    raise ExecutorContractError("executor command contract invalid")


def _text(value: str) -> None:
    if value.strip() != value or unicodedata.normalize("NFC", value) != value:
        _invalid()
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value):
        _invalid()


def _bounded_json(value: Any, depth: int, ancestors: set[int], budget: list[int]) -> None:
    if depth > MAX_COMMAND_DEPTH:
        _invalid()
    budget[0] += 1
    # Even malformed collections must be cheap to reject before serialization.
    if budget[0] > MAX_COMMAND_BYTES:
        _invalid()
    if type(value) is str:
        if len(value) > MAX_COMMAND_BYTES:
            _invalid()
        _text(value)
        budget[0] += len(value.encode("utf-8")) + 2 + value.count("\\") + value.count('"')
    elif value is None or type(value) is bool:
        budget[0] += 4 if value is None or value is True else 5
    elif type(value) is int:
        # Such an integer cannot fit the transport bound even before conversion.
        if value.bit_length() > MAX_COMMAND_BYTES * 4:
            _invalid()
        budget[0] += len(str(value))
    elif type(value) in {dict, list}:
        identity = id(value)
        if identity in ancestors:
            _invalid()
        ancestors.add(identity)
        try:
            if type(value) is dict:
                for key, item in value.items():
                    if type(key) is not str:
                        _invalid()
                    _bounded_json(key, depth + 1, ancestors, budget)
                    _bounded_json(item, depth + 1, ancestors, budget)
            else:
                for item in value:
                    _bounded_json(item, depth + 1, ancestors, budget)
        finally:
            ancestors.remove(identity)
    else:
        # No floats (including NaN/Infinity), tuples or caller-defined objects.
        _invalid()
    if budget[0] > MAX_COMMAND_BYTES:
        _invalid()


def _snapshot(value: Any) -> dict[str, Any]:
    if type(value) is not dict:
        _invalid()
    _bounded_json(value, 0, set(), [0])
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(encoded) > MAX_COMMAND_BYTES:
        _invalid()
    return json.loads(encoded)


def _closed(value: Any, definition: str) -> None:
    if type(value) is not dict:
        _invalid()
    keys = set(value)
    required = REQUIRED_FIELDS[definition]
    if not required <= keys or not keys <= required | OPTIONAL_FIELDS[definition]:
        _invalid()


def _match(value: Any, definition: str) -> None:
    if type(value) is not str or re.fullmatch(TEXT_PATTERNS[definition], value) is None:
        _invalid()
    if definition == "reference" and not 1 <= len(value) <= 96:
        _invalid()


def _date(value: Any) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        _invalid()
    date.fromisoformat(value)


def _time(value: Any) -> datetime:
    _match(value, "utcTime")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _lifetime(start: Any, end: Any) -> None:
    if _time(end) <= _time(start):
        _invalid()


def _action(action: Any) -> None:
    _closed(action, "canonicalAction")
    if action["canonicalization_version"] != CANONICALIZATION_VERSION or action["action_schema_version"] != ACTION_SCHEMA_VERSION:
        _invalid()
    _match(action["policy_version"], "version")
    _match(action["scenario_id"], "scenarioId")
    _match(action["document_sha256"], "rawDigest")
    for name in ("vendor_ref", "purchase_order_ref", "document_ref", "recipient_bank_ref"):
        _match(action[name], "reference")
    _date(action["invoice_date"])
    _match(action["currency"], "currency")
    _match(action["amount"], "money")
    if action["executor_mode"] == "CREATE_DRAFT":
        if action["action"] != "CREATE_DRAFT_BILL" or "target_move_id" in action:
            _invalid()
    elif action["executor_mode"] == "POST_APPROVED":
        if action["action"] != "POST_VENDOR_BILL" or type(action.get("target_move_id")) is not int or action["target_move_id"] < 1:
            _invalid()
    else:
        _invalid()
    lines = action["lines"]
    if type(lines) is not list or not 1 <= len(lines) <= 50:
        _invalid()
    codes = []
    total = Decimal("0.00")
    with localcontext(Context(prec=32, rounding=ROUND_HALF_UP)):
        for line in lines:
            _closed(line, "canonicalLine")
            _match(line["item_code"], "reference")
            _match(line["quantity"], "quantity")
            _match(line["unit_price"], "money")
            quantity, price = Decimal(line["quantity"]), Decimal(line["unit_price"])
            if quantity <= 0 or price <= 0:
                _invalid()
            codes.append(line["item_code"])
            total += (quantity * price).quantize(_CENT, rounding=ROUND_HALF_UP)
        if Decimal(action["amount"]) <= 0 or Decimal(action["amount"]) != total:
            _invalid()
    if codes != sorted(codes) or len(codes) != len(set(codes)):
        _invalid()


def _bytes(action: dict[str, Any]) -> bytes:
    return json.dumps(action, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def canonical_action_bytes(action: dict[str, Any]) -> bytes:
    """Validate then serialize independent canon/v1; no field is repaired."""
    try:
        snapshot = _snapshot(action)
        _action(snapshot)
        return _bytes(snapshot)
    except ExecutorContractError:
        raise
    except (ValueError, TypeError, OverflowError, RecursionError, RuntimeError, DecimalException):
        raise ExecutorContractError("executor command contract invalid") from None


def _decision(decision: Any, action: dict[str, Any], action_hash: str) -> None:
    _closed(decision, "policyDecision")
    if decision["schema_version"] != DECISION_VERSION:
        _invalid()
    for name in ("proposed_action_hash", "input_sha256"):
        _match(decision[name], "digest")
    _match(decision["policy_version"], "version")
    if decision["proposed_action_hash"] != action_hash or decision["policy_version"] != action["policy_version"]:
        _invalid()
    _lifetime(decision["evaluated_at"], decision["expires_at"])
    if decision["deny_class"] is not None:
        _invalid()
    post = action["executor_mode"] == "POST_APPROVED"
    expected_decision = "REVIEW" if post else "ALLOW"
    expected_executor = "post_bill_executor" if post else "create_bill_executor"
    expected_reason = "CRITICAL_ACTION_REQUIRES_APPROVAL" if post else "DRAFT_CONSISTENT"
    if decision["decision"] != expected_decision or decision["allowed_executor"] != expected_executor:
        _invalid()
    if type(decision["reason_codes"]) is not list or decision["reason_codes"] != [expected_reason]:
        _invalid()


def _approval(approval: Any, action: dict[str, Any], action_hash: str) -> None:
    _closed(approval, "approvalFixture")
    for name in ("fixture_id", "approver_ref"):
        _match(approval[name], "reference")
    _match(approval["scenario_id"], "scenarioId")
    _match(approval["canonical_action_hash"], "digest")
    _match(approval["key_id"], "version")
    if approval["decision"] != "APPROVE" or approval["scenario_id"] != action["scenario_id"] or approval["canonical_action_hash"] != action_hash:
        _invalid()
    nonce, signature = approval["nonce"], approval["signature"]
    if type(nonce) is not str or not 1 <= len(nonce) <= 128 or re.fullmatch(r"[A-Za-z0-9_-]+", nonce) is None:
        _invalid()
    if type(signature) is not str or not 1 <= len(signature) <= 4096:
        _invalid()
    _lifetime(approval["issued_at"], approval["expires_at"])


def validate_command(command: dict[str, Any]) -> ValidatedCommand:
    """Return structural metadata, never executable authority or raw payload."""
    try:
        snapshot = _snapshot(command)
        _closed(snapshot, "capabilityCommand")
        if snapshot["schema_version"] != COMMAND_VERSION:
            _invalid()
        _match(snapshot["idempotency_key"], "digest")
        action = snapshot["action"]
        _action(action)
        action_hash = "sha256:" + hashlib.sha256(_bytes(action)).hexdigest()
        _decision(snapshot["policy_decision"], action, action_hash)
        if action["executor_mode"] == "POST_APPROVED":
            if "approval" not in snapshot:
                _invalid()
            _approval(snapshot["approval"], action, action_hash)
        elif "approval" in snapshot:
            _invalid()
        return ValidatedCommand(
            action_hash, action["executor_mode"], action["scenario_id"],
            action["document_sha256"], action["policy_version"],
        )
    except ExecutorContractError:
        raise
    except (ValueError, TypeError, OverflowError, RecursionError, RuntimeError, DecimalException):
        raise ExecutorContractError("executor command contract invalid") from None
