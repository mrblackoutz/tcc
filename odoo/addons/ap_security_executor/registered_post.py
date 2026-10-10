# SPDX-License-Identifier: LGPL-3.0-or-later
"""Private POST derived from a registered workflow and its audited CREATE.

The origin proves an audited equivalent workflow, not which CREATE entrypoint
was historically called. No model, RPC, internal commit, retry, implicit clock,
or target selected from a proposed reference is introduced.
"""

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib

from psycopg2 import Error as DatabaseError

from odoo.exceptions import ValidationError

from . import audit_kernel, registered_execution, workflow_registry
from .approval import verify_approval
from .contracts import ExecutorContractError, _bytes, _snapshot, validate_command
from .draft_contracts import bill_idempotency_key, canonical_command_sha256
from .post_contracts import TrustedPostWorkflow
from .workflow_contracts import WorkflowProvenance


SCHEMA_VERSION = "registered-post-execution/v1"
ERROR_CODES = frozenset({
    "CONTRACT_INVALID", "COMMAND_INVALID", "UNSUPPORTED_EXECUTOR_MODE",
    "WORKFLOW_BINDING_MISMATCH", "REGISTRATION_CHANGED", "ORIGIN_NOT_FOUND",
    "ORIGIN_INVALID", "ORIGIN_CHANGED", "EXECUTION_RESULT_INVALID",
    "EXECUTION_UNAVAILABLE",
})


class RegisteredPostError(ValidationError):
    """Finite diagnostic without command, document, SQL, token or key."""

    def __init__(self, code="CONTRACT_INVALID"):
        self.code = code if type(code) is str and code in ERROR_CODES else "CONTRACT_INVALID"
        super().__init__("Private registered post execution rejected.")


def _after_registered_post(result):
    """Private fault seam after real audited POST; never a caller hook."""
    return None


def _command(value):
    try:
        command = _snapshot(value)
        checked = validate_command(command)
    except ExecutorContractError:
        raise RegisteredPostError("COMMAND_INVALID") from None
    if checked.executor_mode != "POST_APPROVED":
        raise RegisteredPostError("UNSUPPORTED_EXECUTOR_MODE")
    return command, checked


def _receipt_fields(receipt):
    receipt.invalidate_recordset()
    return {
        "receipt_id": receipt.id, "company_id": receipt.company_id.id,
        "executor_mode": receipt.executor_mode, "idempotency_key": receipt.idempotency_key,
        "command_sha256": receipt.command_sha256, "action_sha256": receipt.action_sha256,
        "document_sha256": receipt.document_sha256, "po_id": receipt.po_id.id,
        "vendor_id": receipt.vendor_id.id,
        "purchase_line_ids": sorted(receipt.purchase_line_ids.ids),
        "move_id": receipt.move_id.id, "executor_user_id": receipt.executor_user_id.id,
        "receipt_payload": _snapshot(receipt.receipt_payload),
    }


def _receipt_binding(values, config, *, mode, target):
    key = bill_idempotency_key(document_sha256=config.document_sha256,
        company_id=config.company_id, vendor_id=config.vendor_id,
        purchase_order_id=config.purchase_order_id, purchase_line_ids=config.purchase_line_ids)
    return (values["company_id"] == config.company_id
        and values["executor_user_id"] == config.executor_user_id
        and values["executor_mode"] == mode and values["document_sha256"] == config.document_sha256
        and values["po_id"] == config.purchase_order_id and values["vendor_id"] == config.vendor_id
        and values["purchase_line_ids"] == list(config.purchase_line_ids)
        and values["idempotency_key"] == key and values["move_id"] == target)


def _origin(env, resolved, audit):
    """Read exact CREATE origin without reversing the kernel's lock order.

The financial kernel locks this receipt only after its vendor/PO guards. A
second origin check occurs before returning, while those locks remain held.
Current bill state is deliberately excluded so legitimate POST replay works.
"""
    try:
        config = resolved.workflow
        receipt = env["ap.security.draft.receipt"].search([
            ("company_id", "=", config.company_id),
            ("document_sha256", "=", config.document_sha256),
            ("executor_mode", "=", "CREATE_DRAFT"),
        ])
        if len(receipt) != 1:
            raise RegisteredPostError("ORIGIN_NOT_FOUND")
        values = _receipt_fields(receipt)
        workflow = TrustedPostWorkflow(draft=config, target_move_id=receipt.move_id.id)
        if (not _receipt_binding(values, config, mode="CREATE_DRAFT", target=workflow.target_move_id)
                or not receipt.move_id.exists()
                or receipt.move_id.company_id.id != config.company_id):
            raise RegisteredPostError("ORIGIN_INVALID")
        event = audit_kernel._original_event(env, receipt, workflow=config, audit=audit)
        payload = audit_kernel._verify_event(event)
        if (event.status != "CREATED" or event.executor_mode != "CREATE_DRAFT"
                or event.success_receipt_id != receipt
                or payload["outcome"]["effect_applied"] is not True
                or values["receipt_payload"] != {"receipt_id": receipt.id,
                    "move_id": workflow.target_move_id, "idempotency_key": values["idempotency_key"],
                    "action_hash": values["action_sha256"]}):
            raise RegisteredPostError("ORIGIN_INVALID")
        digest = "sha256:" + hashlib.sha256(b"tcc-registered-post-origin/v1\0" + _bytes({
            "registration_id": resolved.registration_id,
            "registration_sha256": resolved.registration_sha256,
            "receipt": values, "create_event_id": event.id,
            "create_event_sha256": event.event_sha256,
        })).hexdigest()
        return workflow, {"create_receipt_id": receipt.id, "create_event_id": event.id,
            "create_event_sha256": event.event_sha256,
            "target_move_id": workflow.target_move_id, "origin_sha256": digest}
    except (DatabaseError, RegisteredPostError):
        raise
    except Exception:
        raise RegisteredPostError("ORIGIN_INVALID") from None


def _verified_approval(env, *, receipt, payload, workflow, command, authority, key):
    """Verify persisted nonce metadata; this grants no new authorization."""
    ledger = env["ap.security.approval.nonce"].browse(receipt["approval_ledger_id"]).exists()
    if len(ledger) != 1:
        raise RegisteredPostError("EXECUTION_RESULT_INVALID")
    ledger.invalidate_recordset()
    if not ledger.verified_at or not ledger.consumed_at:
        raise RegisteredPostError("EXECUTION_RESULT_INVALID")
    verified = verify_approval(command, trusted_action=command["action"], authority=authority,
        key=key, now=ledger.verified_at.replace(tzinfo=timezone.utc))
    config = workflow.draft
    expiry = datetime.fromisoformat(verified.expires_at.replace("Z", "+00:00")).replace(tzinfo=None)
    if (authority.company_id != config.company_id or authority.executor_user_id != config.executor_user_id
            or authority.scenario_id != config.scenario_id
            or ledger.company_id.id != config.company_id
            or ledger.executor_user_id.id != config.executor_user_id
            or ledger.state != "consumed" or ledger.consumed_at != ledger.verified_at
            or ledger.expires_at != expiry or ledger.key_id != verified.key_id
            or ledger.fixture_id != verified.fixture_id or ledger.scenario_id != verified.scenario_id
            or ledger.approver_ref != verified.approver_ref or ledger.nonce_sha256 != verified.nonce_sha256
            or ledger.action_sha256 != verified.action_hash
            or ledger.command_sha256 != verified.command_sha256
            or ledger.approval_sha256 != verified.approval_sha256
            or payload["approval"] != {"ledger_id": ledger.id, "key_id": verified.key_id,
                "fixture_id": verified.fixture_id, "scenario_id": verified.scenario_id,
                "approval_sha256": verified.approval_sha256,
                "nonce_sha256": verified.nonce_sha256, "state": "consumed"}):
        raise RegisteredPostError("EXECUTION_RESULT_INVALID")


def _verified_result(env, result, *, workflow, origin, audit, command, checked, before, authority, key):
    try:
        result = _snapshot(result)
        required = {"schema_version", "status", "effect_applied", "reason_codes", "audit_complete", "deny_class"}
        if (not required <= set(result) or set(result) - required - {"receipt", "audit_event"}
                or result["schema_version"] != "post-kernel-result/v1"
                or result["status"] not in {"POSTED", "REPLAY", "DENIED"}
                or type(result["effect_applied"]) is not bool
                or result["effect_applied"] is not (result["status"] == "POSTED")
                or type(result["audit_complete"]) is not bool):
            raise RegisteredPostError("EXECUTION_RESULT_INVALID")
        config = workflow.draft
        private = workflow_registry._private(env, config.company_id)
        after = audit_kernel._financial_snapshot(private, config, workflow.target_move_id)
        if not result["audit_complete"]:
            if (result["status"] != "DENIED" or result["reason_codes"] != ["AUDIT_UNAVAILABLE"]
                    or result["deny_class"] != "FAIL_CLOSED_UNAVAILABILITY"
                    or "receipt" in result or "audit_event" in result or before != after):
                raise RegisteredPostError("EXECUTION_RESULT_INVALID")
            return result
        info = result.get("audit_event")
        if (type(info) is not dict or set(info) != {"event_id", "event_sha256", "original_event_id"}
                or type(info["event_id"]) is not int or info["event_id"] <= 0
                or (info["original_event_id"] is not None and (
                    type(info["original_event_id"]) is not int or info["original_event_id"] <= 0))):
            raise RegisteredPostError("EXECUTION_RESULT_INVALID")
        event = private["ap.security.audit.event"].browse(info["event_id"]).exists()
        payload = audit_kernel._verify_event(event)
        expected_subject = {
            "company_id": config.company_id, "executor_user_id": config.executor_user_id,
            "scenario_id": config.scenario_id, "document_sha256": config.document_sha256,
            "executor_mode": "POST_APPROVED", "policy_version": config.policy_version,
            "workflow_sha256": audit_kernel._workflow_hash(workflow),
            "command_sha256": canonical_command_sha256(command),
            "action_sha256": checked.action_hash, "idempotency_key": command["idempotency_key"],
        }
        if (payload["subject"] != expected_subject or payload["context"] != asdict(audit)
                or info != {"event_id": event.id, "event_sha256": event.event_sha256,
                            "original_event_id": event.original_event_id.id or None}
                or payload["outcome"]["status"] != result["status"]
                or payload["outcome"]["effect_applied"] is not result["effect_applied"]
                or payload["outcome"]["reason_codes"] != result["reason_codes"]
                or payload["outcome"]["deny_class"] != result["deny_class"]
                or payload["outcome"]["before_sha256"] != before
                or payload["outcome"]["after_sha256"] != after
                or _bytes(payload["receipt"]) != _bytes(result.get("receipt"))
                or (result["status"] != "POSTED" and after != before)):
            raise RegisteredPostError("EXECUTION_RESULT_INVALID")
        if result["status"] != "DENIED":
            receipt = result["receipt"]
            record = private["ap.security.draft.receipt"].browse(receipt["receipt_id"]).exists()
            if len(record) != 1:
                raise RegisteredPostError("EXECUTION_RESULT_INVALID")
            values = _receipt_fields(record)
            if (not _receipt_binding(values, config, mode="POST_APPROVED", target=origin["target_move_id"])
                    or values["command_sha256"] != expected_subject["command_sha256"]
                    or values["action_sha256"] != checked.action_hash
                    or values["receipt_payload"] != receipt or record.move_id.state != "posted"):
                raise RegisteredPostError("EXECUTION_RESULT_INVALID")
            create_event = private["ap.security.audit.event"].browse(origin["create_event_id"]).exists()
            audit_kernel._verify_event(create_event)
            if (create_event.event_sha256 != origin["create_event_sha256"]
                    or event.attachment_id != create_event.attachment_id):
                raise RegisteredPostError("EXECUTION_RESULT_INVALID")
            if result["status"] == "REPLAY":
                original = audit_kernel._original_event(private, record, workflow=workflow, audit=audit,
                    action_hash=checked.action_hash, command_hash=expected_subject["command_sha256"])
                if (original.status != "POSTED" or event.original_event_id != original
                        or original.attachment_id != create_event.attachment_id):
                    raise RegisteredPostError("EXECUTION_RESULT_INVALID")
            _verified_approval(private, receipt=receipt, payload=payload, workflow=workflow,
                command=command, authority=authority, key=key)
        return result
    except (DatabaseError, RegisteredPostError):
        raise
    except Exception:
        raise RegisteredPostError("EXECUTION_RESULT_INVALID") from None


def post_registered_bill_audited(
    env, *, registration_id, expected_company_id, expected_executor_user_id,
    expected_scenario_id, command, audit, document, authority, key,
):
    """Derive the only permitted POST target; caller owns commit and retry."""
    workflow_registry._registrar(env)
    try:
        try:
            audit = registered_execution._audit_context(audit)
        except registered_execution.RegisteredExecutionError:
            raise RegisteredPostError("CONTRACT_INVALID") from None
        provenance = WorkflowProvenance(code_commit=audit.code_commit,
            code_sha256=audit.code_sha256, configuration_sha256=audit.configuration_sha256)
        command, checked = _command(command)
        arguments = dict(registration_id=registration_id, expected_company_id=expected_company_id,
            expected_executor_user_id=expected_executor_user_id, expected_scenario_id=expected_scenario_id,
            document=document, provenance=provenance)
        with env.cr.savepoint():
            resolved = workflow_registry.resolve_draft_workflow(env, **arguments)
            registered_execution._lock_registration(env, resolved.registration_id)
            locked = workflow_registry.resolve_draft_workflow(env, **arguments)
            if locked != resolved:
                raise RegisteredPostError("REGISTRATION_CHANGED")
            config = locked.workflow
            if (checked.scenario_id != config.scenario_id or checked.document_sha256 != config.document_sha256
                    or checked.policy_version != config.policy_version):
                raise RegisteredPostError("WORKFLOW_BINDING_MISMATCH")
            private = workflow_registry._private(env, config.company_id)
            workflow, origin = _origin(private, locked, audit)
            before = audit_kernel._financial_snapshot(private, config, workflow.target_move_id)
            result = audit_kernel.post_bill_audited(env, command=command, workflow=workflow,
                authority=authority, key=key, audit=audit, document=document)
            _after_registered_post(result)
            if workflow_registry.resolve_draft_workflow(env, **arguments) != locked:
                raise RegisteredPostError("REGISTRATION_CHANGED")
            if _origin(private, locked, audit) != (workflow, origin):
                raise RegisteredPostError("ORIGIN_CHANGED")
            result = _verified_result(env, result, workflow=workflow, origin=origin, audit=audit,
                command=command, checked=checked, before=before, authority=authority, key=key)
            return {"schema_version": SCHEMA_VERSION,
                "registration": {"registration_id": locked.registration_id,
                                 "registration_sha256": locked.registration_sha256},
                "origin": origin, "result": result, "caller_transaction_pending": True}
    except (DatabaseError, RegisteredPostError, workflow_registry.WorkflowRegistryError):
        raise
    except registered_execution.RegisteredExecutionError:
        raise RegisteredPostError("REGISTRATION_CHANGED") from None
    except Exception:
        raise RegisteredPostError("EXECUTION_UNAVAILABLE") from None
