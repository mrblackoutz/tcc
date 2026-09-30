# SPDX-License-Identifier: LGPL-3.0-or-later
"""Synthetic offline compatibility checks; not policy/approval authorization."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, fields
from decimal import Decimal, ROUND_DOWN, localcontext
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from tcc_gateway.policy_contracts import (
    ACTION_PROPOSAL_SCHEMA_VERSION, CAPABILITY_COMMAND_VERSION,
    POLICY_DECISION_VERSION, CanonicalAction, CapabilityCommand,
    PolicyContractError, contract_schema,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "odoo" / "addons" / "ap_security_executor" / "contracts.py"
_SPEC = importlib.util.spec_from_file_location("tcc_executor_contract_offline", CONTRACT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
contracts = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = contracts
_SPEC.loader.exec_module(contracts)


def command_mapping(post: bool = False) -> dict:
    vector = json.loads((ROOT / "gateway" / "tests" / "fixtures" / "canonical_action_v1.vector.json").read_text(encoding="utf-8"))
    action = vector["action"]
    if post:
        action.update(action="POST_VENDOR_BILL", executor_mode="POST_APPROVED", target_move_id=42)
    action_hash = CanonicalAction.from_mapping(action).action_hash
    command = {
        "schema_version": CAPABILITY_COMMAND_VERSION,
        "action": action,
        "policy_decision": {
            "schema_version": POLICY_DECISION_VERSION,
            "decision": "REVIEW" if post else "ALLOW",
            "reason_codes": ["CRITICAL_ACTION_REQUIRES_APPROVAL" if post else "DRAFT_CONSISTENT"],
            "proposed_action_hash": action_hash, "input_sha256": "sha256:" + "c" * 64,
            "policy_version": action["policy_version"],
            "allowed_executor": "post_bill_executor" if post else "create_bill_executor",
            "deny_class": None, "evaluated_at": "2026-09-30T12:00:00Z",
            "expires_at": "2026-09-30T12:10:00Z",
        },
        "idempotency_key": "sha256:" + "b" * 64,
    }
    if post:
        command["approval"] = {
            "fixture_id": "TCC-APR-001", "scenario_id": action["scenario_id"],
            "approver_ref": "TCC-APPROVER-FIXTURE-001", "decision": "APPROVE",
            "canonical_action_hash": action_hash,
            "nonce": "synthetic-nonce-not-a-credential",
            "issued_at": "2026-09-30T12:00:01Z", "expires_at": "2026-09-30T12:10:00Z",
            "key_id": "synthetic-fixture-v1", "signature": "SYNTHETIC-UNVERIFIED-NOT-A-CREDENTIAL",
        }
    return command


def rebind(command: dict) -> None:
    digest = "sha256:" + hashlib.sha256(json.dumps(command["action"], ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()
    command["policy_decision"]["proposed_action_hash"] = digest
    if "approval" in command:
        command["approval"]["canonical_action_hash"] = digest


def at_path(command: dict, path: tuple):
    value = command
    for part in path:
        value = value[part]
    return value


def assert_invalid(command: dict) -> None:
    with pytest.raises(contracts.ExecutorContractError, match="^executor command contract invalid$"):
        contracts.validate_command(command)


@pytest.mark.parametrize("post", [False, True])
def test_both_modes_match_gateway_without_mutating_command(post: bool) -> None:
    command = command_mapping(post)
    snapshot = deepcopy(command)
    gateway = CapabilityCommand.from_mapping(command)
    result = contracts.validate_command(command)
    assert result.action_hash == gateway.action.action_hash
    assert result.executor_mode == gateway.action.executor_mode
    assert result.scenario_id == gateway.action.scenario_id
    assert result.document_sha256 == gateway.action.document_sha256
    assert result.policy_version == gateway.action.policy_version
    assert command == snapshot
    assert {field.name for field in fields(result)} == {
        "action_hash", "executor_mode", "scenario_id", "document_sha256", "policy_version",
    }
    with pytest.raises(FrozenInstanceError):
        result.action_hash = "different"
    if post:
        assert command["approval"]["signature"] not in repr(result)
        assert command["approval"]["nonce"] not in repr(result)
    command["action"]["scenario_id"] = "CHANGED"
    assert result.scenario_id == snapshot["action"]["scenario_id"]


def test_independent_canonical_bytes_match_shared_candidate_vector() -> None:
    vector = json.loads((ROOT / "gateway" / "tests" / "fixtures" / "canonical_action_v1.vector.json").read_text(encoding="utf-8"))
    encoded = contracts.canonical_action_bytes(vector["action"])
    assert encoded == vector["canonical_utf8"].encode("utf-8")
    assert "sha256:" + hashlib.sha256(encoded).hexdigest() == vector["canonical_action_hash"]


def test_schema_constants_field_sets_and_patterns_cannot_drift() -> None:
    definitions = contract_schema(CAPABILITY_COMMAND_VERSION)["$defs"]
    assert contracts.COMMAND_VERSION == CAPABILITY_COMMAND_VERSION
    assert contracts.DECISION_VERSION == POLICY_DECISION_VERSION
    assert contracts.ACTION_SCHEMA_VERSION == ACTION_PROPOSAL_SCHEMA_VERSION
    assert contracts.CANONICALIZATION_VERSION == definitions["canonicalAction"]["properties"]["canonicalization_version"]["const"]
    for name, required in contracts.REQUIRED_FIELDS.items():
        assert definitions[name]["additionalProperties"] is False
        assert required == frozenset(definitions[name]["required"])
        assert required | contracts.OPTIONAL_FIELDS[name] == frozenset(definitions[name]["properties"])
    for name, pattern in contracts.TEXT_PATTERNS.items():
        assert pattern == definitions[name]["pattern"]
    assert definitions["canonicalAction"]["properties"]["lines"]["maxItems"] == 50
    assert definitions["approvalFixture"]["properties"]["signature"]["maxLength"] == 4096
    assert definitions["approvalFixture"]["properties"]["nonce"]["maxLength"] == 128
    assert contracts.MAX_COMMAND_BYTES == 65536
    assert contracts.MAX_COMMAND_DEPTH == 8


_LEVELS = [
    ((), "capabilityCommand"), (("action",), "canonicalAction"),
    (("action", "lines", 0), "canonicalLine"), (("policy_decision",), "policyDecision"),
    (("approval",), "approvalFixture"),
]


@pytest.mark.parametrize("path,definition", _LEVELS)
@pytest.mark.parametrize("extra", ["context", "model", "method", "company_id", "write_values", "evidence"])
def test_extra_fields_fail_at_every_level(path: tuple, definition: str, extra: str) -> None:
    command = command_mapping(True)
    at_path(command, path)[extra] = "SYNTHETIC-HOSTILE-VALUE"
    assert_invalid(command)
    with pytest.raises(PolicyContractError):
        CapabilityCommand.from_mapping(command)


@pytest.mark.parametrize("path,key", [
    (path, key) for path, definition in _LEVELS
    for key in sorted(contracts.REQUIRED_FIELDS[definition])
])
def test_missing_fields_fail_at_every_level(path: tuple, key: str) -> None:
    command = command_mapping(True)
    del at_path(command, path)[key]
    assert_invalid(command)
    with pytest.raises(PolicyContractError):
        CapabilityCommand.from_mapping(command)


@pytest.mark.parametrize("target", [None, True, False, 0, -1, 42.0, "42", [], {}, Decimal("42")])
def test_target_id_is_positive_strict_integer(target) -> None:
    command = command_mapping(True)
    command["action"]["target_move_id"] = target
    assert_invalid(command)


@pytest.mark.parametrize("path,key,value", [
    ((), "schema_version", "capability-command/v2"),
    (("action",), "canonicalization_version", "canon/v2"),
    (("action",), "action_schema_version", "vendor-bill-proposal/v1"),
    (("action",), "action", "CREATE_DRAFT_BILL"),
    (("action",), "executor_mode", "CREATE_DRAFT"),
    (("action",), "invoice_date", "2026-02-30"),
    (("action",), "invoice_date", "20260930"),
    (("action",), "invoice_date", "0000-01-01"),
    (("action",), "currency", "brl"),
    (("action",), "vendor_ref", "TCC-" + "X" * 93),
    (("action",), "purchase_order_ref", "TCC:PO"),
    (("action",), "scenario_id", "TCC/SCN"),
    (("action",), "document_sha256", "A" * 64),
    (("action",), "policy_version", "POLICY-v1"),
    (("action",), "amount", "0125.50"),
    (("action",), "amount", "125.5"),
    (("action",), "amount", "0.00"),
    (("action",), "amount", "125.51"),
    (("action", "lines", 0), "quantity", "0.00"),
    (("action", "lines", 0), "quantity", "1.00000"),
    (("action", "lines", 0), "quantity", "1000000.00"),
    (("action", "lines", 0), "unit_price", "0.00"),
    (("action", "lines", 0), "unit_price", "-1.00"),
    (("action", "lines", 0), "unit_price", "1000000000000.00"),
    (("action", "lines", 0), "item_code", "ITEM\n"),
    (("policy_decision",), "schema_version", "policy-decision/v2"),
    (("policy_decision",), "decision", "ALLOW"),
    (("policy_decision",), "decision", "DENY"),
    (("policy_decision",), "reason_codes", ["DRAFT_CONSISTENT"]),
    (("policy_decision",), "reason_codes", ["CRITICAL_ACTION_REQUIRES_APPROVAL"] * 2),
    (("policy_decision",), "allowed_executor", "create_bill_executor"),
    (("policy_decision",), "deny_class", "POLICY_RULE"),
    (("policy_decision",), "proposed_action_hash", "sha256:" + "d" * 64),
    (("policy_decision",), "input_sha256", "d" * 64),
    (("policy_decision",), "policy_version", "policy-v2"),
    (("policy_decision",), "evaluated_at", "2026-09-30T12:00:00+00:00"),
    (("policy_decision",), "expires_at", "2026-09-30T12:00:00Z"),
    (("policy_decision",), "expires_at", "2026-09-30T11:59:59Z"),
    (("policy_decision",), "expires_at", "2026-09-30T24:00:00Z"),
    (("policy_decision",), "expires_at", "2026-09-30T12:10:00.1234567Z"),
    (("approval",), "canonical_action_hash", "sha256:" + "d" * 64),
    (("approval",), "scenario_id", "ANOTHER-SCENARIO"),
    (("approval",), "decision", "REJECT"),
    (("approval",), "nonce", "bad/nonce"),
    (("approval",), "nonce", "X" * 129),
    (("approval",), "nonce", ""),
    (("approval",), "signature", ""),
    (("approval",), "signature", "X" * 4097),
    (("approval",), "key_id", "BAD-KEY-ID"),
    (("approval",), "expires_at", "2026-09-30T12:00:01Z"),
    (("approval",), "issued_at", "2026-09-31T12:00:01Z"),
    ((), "idempotency_key", "b" * 64),
])
def test_invalid_fields_semantics_and_bindings_are_sanitized(path: tuple, key: str, value) -> None:
    command = command_mapping(True)
    at_path(command, path)[key] = value
    assert_invalid(command)


@pytest.mark.parametrize("post", [False, True])
def test_approval_is_forbidden_on_create_and_mandatory_on_post(post: bool) -> None:
    command = command_mapping(post)
    if post:
        del command["approval"]
    else:
        command["approval"] = command_mapping(True)["approval"]
    assert_invalid(command)


def test_target_id_is_forbidden_on_create() -> None:
    command = command_mapping()
    command["action"]["target_move_id"] = 42
    assert_invalid(command)


@pytest.mark.parametrize("lines", [[], {}, [None], tuple(), ["not-an-object"]])
def test_line_collection_invalid_types(lines) -> None:
    command = command_mapping()
    command["action"]["lines"] = lines
    assert_invalid(command)


@pytest.mark.parametrize("kind", ["duplicate", "unsorted", "too-many"])
def test_line_uniqueness_order_and_bounds(kind: str) -> None:
    command = command_mapping()
    line = command["action"]["lines"][0]
    if kind == "duplicate":
        command["action"]["lines"] = [line, deepcopy(line)]
        command["action"]["amount"] = "251.00"
    elif kind == "unsorted":
        command["action"]["lines"] = [{**line, "item_code": "ITEM-Z"}, {**line, "item_code": "ITEM-A"}]
        command["action"]["amount"] = "251.00"
    else:
        command["action"]["lines"] = [{**line, "item_code": f"ITEM-{index:03d}"} for index in range(51)]
        command["action"]["amount"] = "6400.50"
    rebind(command)
    assert_invalid(command)


@pytest.mark.parametrize("quantity", ["1.00", "1.000", "1.0000", "0.01", "999999.00"])
def test_supported_quantities_and_exact_gateway_hash(quantity: str) -> None:
    command = command_mapping()
    command["action"]["lines"][0]["quantity"] = quantity
    with localcontext() as context:
        context.prec = 32
        command["action"]["amount"] = format((Decimal(quantity) * Decimal("125.50")).quantize(Decimal("0.01")), ".2f")
    rebind(command)
    assert contracts.validate_command(command).action_hash == CapabilityCommand.from_mapping(command).action.action_hash


@pytest.mark.parametrize("quantity,price,amount", [("0.50", "0.05", "0.02"), ("0.70", "0.05", "0.04")])
def test_round_half_even_and_low_ambient_decimal_precision(quantity: str, price: str, amount: str) -> None:
    command = command_mapping()
    command["action"]["lines"][0].update(quantity=quantity, unit_price=price)
    command["action"]["amount"] = amount
    rebind(command)
    with localcontext() as context:
        context.prec = 1
        context.rounding = ROUND_DOWN
        validated = contracts.validate_command(command)
    assert validated.action_hash == CanonicalAction.from_mapping(command["action"]).action_hash


@pytest.mark.parametrize("text", [" leading", "trailing ", "\x00", "\x1f", "\n", "\t", "\u200b", "\u200d", "\u202e", "\u2066", "\ud800", "e\u0301"])
def test_noncanonical_signature_text_rejected_without_echo(text: str) -> None:
    command = command_mapping(True)
    command["approval"]["signature"] = text
    assert_invalid(command)


def test_nfc_unicode_signature_is_not_a_credential_verification() -> None:
    command = command_mapping(True)
    command["approval"]["signature"] = "ASSINATURA-SINTÉTICA-NÃO-VERIFICADA"
    result = contracts.validate_command(command)
    assert result.executor_mode == "POST_APPROVED"
    assert "ASSINATURA" not in repr(result)


@pytest.mark.parametrize("value", [None, [], (), "{}", 0, True, {1: "not-json-key"}, {"unknown": float("nan")}, {"unknown": float("inf")}, {"unknown": 1.0}, {"unknown": object()}])
def test_non_json_types_and_nonfinite_values_rejected(value) -> None:
    assert_invalid(value)


def test_cycle_depth_and_transport_size_are_bounded() -> None:
    cyclic = {}
    cyclic["action"] = cyclic
    assert_invalid(cyclic)
    deeply_nested = command_mapping()
    value = deeply_nested
    for _ in range(contracts.MAX_COMMAND_DEPTH + 1):
        value["nested"] = {}
        value = value["nested"]
    assert_invalid(deeply_nested)
    oversized = command_mapping()
    oversized["oversized"] = "X" * (contracts.MAX_COMMAND_BYTES + 1)
    assert_invalid(oversized)
    multi_byte = command_mapping(True)
    multi_byte["oversized"] = "É" * contracts.MAX_COMMAND_BYTES
    assert_invalid(multi_byte)


def test_shared_large_strings_cannot_amplify_snapshot_allocation(monkeypatch) -> None:
    command = command_mapping()
    shared = "X" * 16_000
    command["unknown"] = [shared] * 100

    def forbidden_serialization(*args, **kwargs):
        raise AssertionError("size gate must run before whole-payload serialization")

    monkeypatch.setattr(contracts.json, "dumps", forbidden_serialization)
    assert_invalid(command)


def test_giant_python_integer_is_rejected_before_snapshot(monkeypatch) -> None:
    command = command_mapping(True)
    command["action"]["target_move_id"] = 1 << (contracts.MAX_COMMAND_BYTES * 4 + 1)

    def forbidden_serialization(*args, **kwargs):
        raise AssertionError("integer size gate must run before serialization")

    monkeypatch.setattr(contracts.json, "dumps", forbidden_serialization)
    assert_invalid(command)


def test_checks_are_structural_not_time_of_use_or_signature_authorization() -> None:
    command = command_mapping(True)
    command["policy_decision"].update(evaluated_at="2000-01-01T00:00:00Z", expires_at="2000-01-01T00:00:01Z")
    command["approval"].update(issued_at="2000-01-01T00:00:00Z", expires_at="2000-01-01T00:00:01Z")
    assert contracts.validate_command(command).executor_mode == "POST_APPROVED"
    # The Odoo boundary must still deny effects; this module has no clock/key/state.


@pytest.mark.parametrize("bad", [{}, {"document_ref": "SYNTHETIC-PRIVATE-CONTENT"}, {"lines": [float("nan")]}])
def test_independent_hash_builder_rejects_unvalidated_action(bad: dict) -> None:
    with pytest.raises(contracts.ExecutorContractError, match="^executor command contract invalid$"):
        contracts.canonical_action_bytes(bad)
