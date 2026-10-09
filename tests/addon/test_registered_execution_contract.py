# SPDX-License-Identifier: LGPL-3.0-or-later
"""Structural regression gates, not Odoo execution or proof of authority.

These tests inspect the private entry's source. Native ORM and ordinary-cursor
commit/rollback tests remain necessary; AST shape does not prove their effects.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ADDON = ROOT / "odoo/addons/ap_security_executor"
SOURCE = ADDON / "registered_execution.py"


def tree() -> ast.Module:
    return ast.parse(SOURCE.read_text(encoding="utf-8"))


def function(name: str) -> ast.FunctionDef:
    matches = [node for node in tree().body if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(matches) == 1
    return matches[0]


def called_name(call: ast.Call) -> str:
    return ast.unparse(call.func)


def calls(node: ast.AST, name: str) -> list[ast.Call]:
    return sorted(
        [child for child in ast.walk(node) if isinstance(child, ast.Call) and called_name(child) == name],
        key=lambda child: child.lineno,
    )


def test_registered_entry_is_a_closed_module_function_not_a_public_model():
    entry = function("create_registered_draft_audited")
    assert [argument.arg for argument in entry.args.args] == ["env"]
    assert [argument.arg for argument in entry.args.kwonlyargs] == [
        "registration_id", "expected_company_id", "expected_executor_user_id",
        "expected_scenario_id", "command", "audit", "document",
    ]
    assert entry.args.vararg is None and entry.args.kwarg is None
    assert all(default is None for default in entry.args.kw_defaults)
    classes = [node for node in tree().body if isinstance(node, ast.ClassDef)]
    assert [node.name for node in classes] == ["RegisteredExecutionError"]


def test_real_registrar_authority_is_checked_before_the_operational_savepoint():
    entry = function("create_registered_draft_audited")
    assert isinstance(entry.body[0], ast.Expr) and isinstance(entry.body[0].value, ast.Constant)
    authority = entry.body[1]
    assert isinstance(authority, ast.Expr) and isinstance(authority.value, ast.Call)
    assert called_name(authority.value) == "workflow_registry._registrar"
    assert [ast.unparse(value) for value in authority.value.args] == ["env"]
    assert not any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"sudo", "with_user"}
        for node in ast.walk(entry)
    )


def test_savepoint_contains_lock_revalidation_effect_fault_and_return_verification():
    entry = function("create_registered_draft_audited")
    points = [node for node in ast.walk(entry) if isinstance(node, ast.With)
              and any(isinstance(item.context_expr, ast.Call)
                      and called_name(item.context_expr) == "env.cr.savepoint" for item in node.items)]
    assert len(points) == 1
    point = points[0]
    resolved = calls(point, "workflow_registry.resolve_draft_workflow")
    locked = calls(point, "_lock_registration")
    effect = calls(point, "audit_kernel.create_draft_audited")
    fault = calls(point, "_after_registered_draft")
    verified = calls(point, "_verified_result")
    assert len(resolved) == 3
    assert len(locked) == len(effect) == len(fault) == len(verified) == 1
    assert resolved[0].lineno < locked[0].lineno < resolved[1].lineno < effect[0].lineno
    assert effect[0].lineno < fault[0].lineno < resolved[2].lineno < verified[0].lineno
    returns = [node for node in ast.walk(point) if isinstance(node, ast.Return)]
    assert len(returns) == 1 and verified[0].lineno < returns[0].lineno


def test_financial_kernel_receives_only_the_locked_registered_workflow():
    entry = function("create_registered_draft_audited")
    assignments = [node for node in ast.walk(entry) if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "config" for target in node.targets)]
    assert len(assignments) == 1 and ast.unparse(assignments[0].value) == "locked.workflow"
    effect, = calls(entry, "audit_kernel.create_draft_audited")
    assert [ast.unparse(value) for value in effect.args] == ["env"]
    assert {keyword.arg: ast.unparse(keyword.value) for keyword in effect.keywords} == {
        "command": "command", "workflow": "config", "audit": "audit", "document": "document",
    }
    assert not calls(entry, "audit_kernel.post_bill_audited")


def test_create_mode_is_checked_without_inventing_a_different_model_action():
    command = function("_command")
    comparisons = [node for node in ast.walk(command) if isinstance(node, ast.Compare)]
    assert any(ast.unparse(node.left) == "checked.executor_mode" and len(node.ops) == 1
               and isinstance(node.ops[0], ast.NotEq)
               and ast.literal_eval(node.comparators[0]) == "CREATE_DRAFT" for node in comparisons)
    assert len(calls(command, "validate_command")) == 1
    assert len(calls(command, "_snapshot")) == 1
    assert not any(isinstance(node, ast.Assign) and any(isinstance(target, ast.Subscript)
                   for target in node.targets) for node in ast.walk(command))


def test_registration_provenance_is_rebuilt_from_the_checked_audit_context():
    entry = function("create_registered_draft_audited")
    provenance, = calls(entry, "WorkflowProvenance")
    assert {keyword.arg: ast.unparse(keyword.value) for keyword in provenance.keywords} == {
        "code_commit": "audit.code_commit", "code_sha256": "audit.code_sha256",
        "configuration_sha256": "audit.configuration_sha256",
    }
    assert calls(entry, "_audit_context")[0].lineno < provenance.lineno
    resolution = calls(entry, "workflow_registry.resolve_draft_workflow")
    assert len(resolution) == 3 and all(
        any(keyword.arg is None and ast.unparse(keyword.value) == "arguments"
            for keyword in operation.keywords) for operation in resolution)


def test_result_is_bound_to_the_real_event_and_canonical_receipt_not_only_a_return_status():
    verified = function("_verified_result")
    assert len(calls(verified, "audit_kernel._verify_event")) == 1
    assert len(calls(verified, "canonical_command_sha256")) == 1
    assert len(calls(verified, "audit_kernel._financial_snapshot")) == 1
    receipt_calls = calls(verified, "_bytes")
    assert [ast.unparse(call.args[0]) for call in receipt_calls] == [
        "payload['receipt']", "result.get('receipt')",
    ]
    assert not calls(verified, "evaluate_oracle")


def test_registration_lock_is_a_parameterized_read_without_internal_commit_or_retry():
    lock = function("_lock_registration")
    query, = calls(lock, "env.cr.execute")
    assert ast.literal_eval(query.args[0]) == (
        "SELECT id FROM ap_security_workflow_registration WHERE id = %s FOR UPDATE")
    assert ast.unparse(query.args[1]) == "(registration_id,)"
    forbidden = {"commit", "rollback", "create", "write", "unlink", "action_post", "sleep", "post", "request"}
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr in forbidden for node in ast.walk(tree()))
    assert not any(isinstance(node, (ast.For, ast.While)) for node in ast.walk(
        function("create_registered_draft_audited")))


def test_database_failure_is_propagated_instead_of_disguised_as_a_normal_denial():
    for name in ("create_registered_draft_audited", "_verified_result"):
        handlers = [node for node in ast.walk(function(name)) if isinstance(node, ast.ExceptHandler)
                    and node.type is not None and "DatabaseError" in ast.unparse(node.type)]
        assert len(handlers) == 1
        assert len(handlers[0].body) == 1
        assert isinstance(handlers[0].body[0], ast.Raise)
        assert handlers[0].body[0].exc is None


def test_envelope_reports_pending_caller_transaction_without_claiming_a_committed_effect():
    entry = function("create_registered_draft_audited")
    returned, = [node.value for node in ast.walk(entry) if isinstance(node, ast.Return)]
    assert isinstance(returned, ast.Dict)
    keys = [ast.literal_eval(key) for key in returned.keys]
    assert set(keys) == {"schema_version", "registration", "result", "caller_transaction_pending"}
    values = dict(zip(keys, returned.values, strict=True))
    assert ast.literal_eval(values["caller_transaction_pending"]) is True
    assert ast.unparse(values["result"]) == "result"
