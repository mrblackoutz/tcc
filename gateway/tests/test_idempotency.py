"""Synthetic offline idempotency parity; hashes are not authorization."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from tcc_gateway.idempotency import (
    bill_idempotency_key, idempotency_key_for_resolved,
)
from tcc_gateway.policy_contracts import (
    CanonicalAction, DependencyStatus, TrustedPolicyState, TrustedPurchaseLine,
    TrustedPurchaseOrder,
)
from tcc_gateway.trusted_resolution import ResolvedPurchaseLine, ResolvedTrustedState


ROOT = Path(__file__).resolve().parents[2]
ADDON = ROOT / "odoo" / "addons" / "ap_security_executor"
PACKAGE = "_tcc_draft_contracts_offline"
_package = ModuleType(PACKAGE)
_package.__path__ = [str(ADDON)]
sys.modules[PACKAGE] = _package


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contracts = _load_module(PACKAGE + ".contracts", ADDON / "contracts.py")
draft = _load_module(PACKAGE + ".draft_contracts", ADDON / "draft_contracts.py")


def _identity(**changes) -> dict:
    value = {
        "document_sha256": "a" * 64,
        "company_id": 11,
        "vendor_id": 22,
        "purchase_order_id": 33,
        "purchase_line_ids": (44, 55),
    }
    value.update(changes)
    return value


def _workflow(**changes):
    value = {
        **_identity(), "executor_user_id": 66, "journal_id": 77,
        "expense_account_id": 88, "allowed_bank_ids": (99, 100),
        "scenario_id": "TCC-SCN-001", "policy_version": "policy-v1.0.0",
        "phase": "DRAFT_INTAKE", "invoice_date_min": "2026-09-01",
        "invoice_date_max": "2026-10-31", "quantity_scale": 2,
        "monetary_tolerance": "0.00",
    }
    value.update(changes)
    return draft.TrustedDraftWorkflow(**value)


def _command(*, post: bool = False) -> dict:
    vector = json.loads((ROOT / "gateway/tests/fixtures/canonical_action_v1.vector.json").read_text(encoding="utf-8"))
    action = vector["action"]
    if post:
        action.update(action="POST_VENDOR_BILL", executor_mode="POST_APPROVED", target_move_id=42)
    action_hash = CanonicalAction.from_mapping(action).action_hash
    command = {
        "schema_version": "capability-command/v1", "action": action,
        "idempotency_key": bill_idempotency_key(**_identity()),
        "policy_decision": {
            "schema_version": "policy-decision/v1",
            "decision": "REVIEW" if post else "ALLOW",
            "reason_codes": ["CRITICAL_ACTION_REQUIRES_APPROVAL" if post else "DRAFT_CONSISTENT"],
            "proposed_action_hash": action_hash, "input_sha256": "sha256:" + "c" * 64,
            "policy_version": "policy-v1.0.0",
            "allowed_executor": "post_bill_executor" if post else "create_bill_executor",
            "deny_class": None, "evaluated_at": "2026-09-30T12:00:00Z",
            "expires_at": "2026-09-30T12:10:00Z",
        },
    }
    if post:
        command["approval"] = {
            "fixture_id": "TCC-APR-001", "scenario_id": action["scenario_id"],
            "approver_ref": "TCC-SYNTHETIC-APPROVER", "decision": "APPROVE",
            "canonical_action_hash": action_hash, "nonce": "synthetic-nonce",
            "issued_at": "2026-09-30T12:00:01Z", "expires_at": "2026-09-30T12:10:00Z",
            "key_id": "synthetic-fixture-v1",
            "signature": "SYNTHETIC-UNVERIFIED-NOT-A-CREDENTIAL",
        }
    return command


def _resolved():
    state = TrustedPolicyState(
        company_ref="TCC-COMPANY-001", scenario_id="TCC-SCN-001",
        document_sha256="a" * 64, phase="DRAFT_INTAKE",
        purchase_order=TrustedPurchaseOrder(
            "TCC-PO-001", "TCC-VENDOR-001", "BRL", True, "20.00",
            (TrustedPurchaseLine("TCC-ITEM-001", "1.00", "10.00", "1.00"),
             TrustedPurchaseLine("TCC-ITEM-002", "1.00", "10.00", "1.00")),
        ),
        allowed_bank_refs=("TCC-BANK-001",), duplicate_detected=False,
        invoice_date_min="2026-09-01", invoice_date_max="2026-10-31",
        accounting_period_open=True, monetary_tolerance="0.00", quantity_scale=2,
        dependencies=DependencyStatus("AVAILABLE", "AVAILABLE", "AVAILABLE"), target_bill=None,
    )
    return ResolvedTrustedState(
        state, company_id=11, vendor_id=22, purchase_order_id=33,
        lines=(ResolvedPurchaseLine("TCC-ITEM-001", 44, 1, 1, "SEM VALOR FISCAL"),
               ResolvedPurchaseLine("TCC-ITEM-002", 55, 2, 1, "SEM VALOR FISCAL")),
        bank_ids=(("TCC-BANK-001", 99),),
    )


def test_canonical_idempotency_preimage_and_independent_addon_parity():
    identity = _identity()
    expected_preimage = {
        "schema_version": "bill-idempotency/v1", **identity,
        "purchase_line_ids": list(identity["purchase_line_ids"]),
    }
    encoded = json.dumps(expected_preimage, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    expected = "sha256:" + hashlib.sha256(encoded).hexdigest()
    assert bill_idempotency_key(**identity) == draft.bill_idempotency_key(**identity) == expected
    assert identity == _identity()


@pytest.mark.parametrize("line_ids", [(55, 44), [44, 55], [55, 44]])
def test_key_normalizes_line_order_without_mutating_inputs(line_ids):
    original = deepcopy(line_ids)
    assert bill_idempotency_key(**_identity(purchase_line_ids=line_ids)) == bill_idempotency_key(**_identity())
    assert draft.bill_idempotency_key(**_identity(purchase_line_ids=line_ids)) == bill_idempotency_key(**_identity())
    assert line_ids == original


@pytest.mark.parametrize("field,value", [
    ("document_sha256", "b" * 64), ("company_id", 12), ("vendor_id", 23),
    ("purchase_order_id", 34), ("purchase_line_ids", (44, 56)),
])
def test_each_trusted_identity_component_changes_key(field, value):
    assert bill_idempotency_key(**_identity(**{field: value})) != bill_idempotency_key(**_identity())


@pytest.mark.parametrize("field,value", [
    ("document_sha256", None), ("document_sha256", "A" * 64),
    ("document_sha256", "a" * 63), ("document_sha256", "a" * 64 + "\n"),
    ("company_id", True), ("company_id", 0), ("company_id", -1),
    ("vendor_id", False), ("vendor_id", 1.0), ("vendor_id", "22"),
    ("purchase_order_id", None), ("purchase_order_id", []),
    ("purchase_line_ids", ()), ("purchase_line_ids", (44, 44)),
    ("purchase_line_ids", (True,)), ("purchase_line_ids", (0,)),
    ("purchase_line_ids", (-1,)), ("purchase_line_ids", ("44",)),
    ("purchase_line_ids", (44.0,)), ("purchase_line_ids", {44, 55}),
    ("purchase_line_ids", {"44": 1}), ("purchase_line_ids", tuple(range(1, 52))),
])
def test_bad_identity_rejected_sanitized_by_both_implementations(field, value):
    identity = _identity(**{field: value})
    with pytest.raises(ValueError, match="^invalid trusted idempotency identity$"):
        bill_idempotency_key(**identity)
    with pytest.raises(contracts.ExecutorContractError, match="^executor draft contract invalid$"):
        draft.bill_idempotency_key(**identity)


def test_resolved_adapter_ignores_mutable_business_metadata():
    resolved = _resolved()
    baseline = idempotency_key_for_resolved(resolved)
    changed_lines = tuple(
        replace(line, description="CHANGED SYNTHETIC DESCRIPTION", product_id=999, uom_id=999)
        for line in reversed(resolved.lines)
    )
    changed_po = replace(
        resolved.state.purchase_order, vendor_ref="TCC-OTHER-TEXT-REF",
        lines=tuple(replace(line, quantity_to_invoice="0.00") for line in resolved.state.purchase_order.lines),
    )
    changed_state = replace(
        resolved.state, phase="POST_REVIEW", scenario_id="TCC-OTHER-SCENARIO",
        purchase_order=changed_po, allowed_bank_refs=("TCC-OTHER-BANK",),
        duplicate_detected=True,
    )
    changed = replace(
        resolved, state=changed_state, lines=changed_lines,
        bank_ids=(("TCC-OTHER-BANK", 999),),
    )
    assert idempotency_key_for_resolved(changed) == baseline == bill_idempotency_key(**_identity())


@pytest.mark.parametrize("mutation", [
    {"company_id": True}, {"vendor_id": 0}, {"purchase_order_id": None},
    {"lines": []}, {"lines": ()}, {"lines": (object(),)},
])
def test_resolved_adapter_validates_boundary(mutation):
    with pytest.raises(ValueError, match="^invalid trusted idempotency identity$"):
        idempotency_key_for_resolved(replace(_resolved(), **mutation))


@pytest.mark.parametrize("value", [None, {}, object()])
def test_adapter_rejects_untyped_resolved_values(value):
    with pytest.raises(ValueError, match="^invalid trusted idempotency identity$"):
        idempotency_key_for_resolved(value)


def test_workflow_frozen_slots_closed_required_fields_and_identity():
    workflow = _workflow()
    assert not hasattr(workflow, "__dict__")
    assert {field.name for field in fields(workflow)} == {
        "company_id", "executor_user_id", "purchase_order_id", "vendor_id", "journal_id",
        "expense_account_id", "purchase_line_ids", "allowed_bank_ids", "scenario_id",
        "document_sha256", "policy_version", "phase", "invoice_date_min",
        "invoice_date_max", "quantity_scale", "monetary_tolerance",
    }
    with pytest.raises(FrozenInstanceError):
        workflow.vendor_id = 999
    with pytest.raises(TypeError):
        draft.TrustedDraftWorkflow(company_id=11)
    assert draft.bill_idempotency_key(
        document_sha256=workflow.document_sha256, company_id=workflow.company_id,
        vendor_id=workflow.vendor_id, purchase_order_id=workflow.purchase_order_id,
        purchase_line_ids=workflow.purchase_line_ids,
    ) == bill_idempotency_key(**_identity())


@pytest.mark.parametrize("field,value", [
    ("company_id", True), ("executor_user_id", 0), ("purchase_order_id", -1),
    ("vendor_id", "22"), ("journal_id", 1.0), ("expense_account_id", None),
    ("purchase_line_ids", [44, 55]), ("purchase_line_ids", (55, 44)),
    ("purchase_line_ids", (44, 44)), ("purchase_line_ids", ()),
    ("allowed_bank_ids", [99]), ("allowed_bank_ids", (100, 99)),
    ("allowed_bank_ids", (99, 99)), ("allowed_bank_ids", (False,)),
    ("allowed_bank_ids", ()), ("allowed_bank_ids", tuple(range(1, 52))),
    ("scenario_id", "lowercase"), ("scenario_id", "S" * 65),
    ("scenario_id", None), ("scenario_id", "TCC-SCN-001\n"),
    ("document_sha256", "A" * 64), ("document_sha256", None),
    ("policy_version", "policy-v2"), ("policy_version", None),
    ("phase", "POST_REVIEW"), ("phase", None),
    ("invoice_date_min", "2026-9-01"), ("invoice_date_min", "2026-02-30"),
    ("invoice_date_min", None), ("invoice_date_max", "2026-08-31"),
    ("quantity_scale", True), ("quantity_scale", 1), ("quantity_scale", 5),
    ("monetary_tolerance", "-0.01"), ("monetary_tolerance", "0.000"),
    ("monetary_tolerance", "00.00"), ("monetary_tolerance", "0.00\n"),
    ("monetary_tolerance", "1000000000000.00"), ("monetary_tolerance", None),
])
def test_invalid_workflow_is_sanitized(field, value):
    with pytest.raises(contracts.ExecutorContractError, match="^executor draft contract invalid$"):
        _workflow(**{field: value})


@pytest.mark.parametrize("scale", [2, 3, 4])
def test_workflow_accepts_explicit_scales_and_inclusive_single_day_window(scale):
    assert _workflow(quantity_scale=scale, invoice_date_min="2026-09-30", invoice_date_max="2026-09-30").quantity_scale == scale


@pytest.mark.parametrize("post", [False, True])
def test_whole_command_fingerprint_is_canonical_bounded_and_not_authority(post):
    command = _command(post=post)
    original = deepcopy(command)
    encoded = json.dumps(command, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    expected = "sha256:" + hashlib.sha256(encoded).hexdigest()
    assert draft.canonical_command_sha256(command) == expected
    reordered = dict(reversed(list(command.items())))
    assert draft.canonical_command_sha256(reordered) == expected
    assert command == original


def test_changed_decision_timestamp_conflicts_despite_same_action_and_document_key():
    first = _command()
    second = deepcopy(first)
    second["policy_decision"]["evaluated_at"] = "2026-09-30T12:00:01Z"
    assert first["action"] == second["action"]
    assert first["idempotency_key"] == second["idempotency_key"]
    assert draft.canonical_command_sha256(first) != draft.canonical_command_sha256(second)


def test_changed_proposed_reference_changes_body_not_trusted_document_key():
    first = _command()
    second = deepcopy(first)
    second["action"]["document_ref"] = "TCC-CHANGED-REF-SEM-VALOR-FISCAL"
    second["policy_decision"]["proposed_action_hash"] = CanonicalAction.from_mapping(second["action"]).action_hash
    assert first["idempotency_key"] == second["idempotency_key"]
    assert draft.canonical_command_sha256(first) != draft.canonical_command_sha256(second)


@pytest.mark.parametrize("field", ["context", "model", "method", "fixture_label"])
def test_whole_command_rejects_extra_fields_before_hashing(field):
    command = _command()
    command[field] = "SENSITIVE-MARKER-NOT-TO-ECHO"
    with pytest.raises(contracts.ExecutorContractError) as captured:
        draft.canonical_command_sha256(command)
    assert "SENSITIVE-MARKER" not in str(captured.value)


def test_whole_command_rejects_hash_mismatch_and_oversize_payload():
    mismatched = _command()
    mismatched["policy_decision"]["proposed_action_hash"] = "sha256:" + "f" * 64
    with pytest.raises(contracts.ExecutorContractError):
        draft.canonical_command_sha256(mismatched)
    oversized = _command()
    oversized["action"]["document_ref"] = "X" * 65_537
    with pytest.raises(contracts.ExecutorContractError):
        draft.canonical_command_sha256(oversized)


def test_whole_command_rejects_cycles_without_echo():
    cyclic = _command()
    cyclic["loop"] = cyclic
    with pytest.raises(contracts.ExecutorContractError):
        draft.canonical_command_sha256(cyclic)


def test_addon_stays_stdlib_only_without_runtime_odoo_or_gateway_imports():
    import ast

    tree = ast.parse((ADDON / "draft_contracts.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] not in {"odoo", "tcc_gateway", "jsonschema"} for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            assert node.module.split(".")[0] not in {"odoo", "tcc_gateway", "jsonschema"}
