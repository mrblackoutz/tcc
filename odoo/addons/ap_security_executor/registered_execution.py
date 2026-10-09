# SPDX-License-Identifier: LGPL-3.0-or-later
"""Private CREATE handoff bound to the documentary registration.

The caller owns commit/rollback and whole-transaction retry. This is not an RPC
endpoint, a POST registration, a scientific runner, or a complete state oracle.
Declared code/configuration hashes are not cryptographic caller attestation.
"""

from dataclasses import asdict, fields

from psycopg2 import Error as DatabaseError

from odoo.exceptions import ValidationError

from . import audit_kernel, workflow_registry
from .audit_contracts import TrustedAuditContext
from .contracts import ExecutorContractError, _bytes, _snapshot, validate_command
from .draft_contracts import canonical_command_sha256
from .workflow_contracts import WorkflowProvenance


SCHEMA_VERSION = "registered-draft-execution/v1"
ERROR_CODES = frozenset({
    "CONTRACT_INVALID", "COMMAND_INVALID", "UNSUPPORTED_EXECUTOR_MODE",
    "WORKFLOW_BINDING_MISMATCH", "REGISTRATION_CHANGED",
    "EXECUTION_RESULT_INVALID", "EXECUTION_UNAVAILABLE",
})


class RegisteredExecutionError(ValidationError):
    """Finite operational failure without command, document, SQL or secret."""

    def __init__(self, code="CONTRACT_INVALID"):
        self.code = code if type(code) is str and code in ERROR_CODES else "CONTRACT_INVALID"
        super().__init__("Private registered draft execution rejected.")


def _after_registered_draft(result):
    """Private fault seam after real audited execution, never a caller hook."""
    return None


def _audit_context(value):
    if type(value) is not TrustedAuditContext:
        raise RegisteredExecutionError("CONTRACT_INVALID")
    try:
        return TrustedAuditContext(**{field.name: getattr(value, field.name)
                                      for field in fields(TrustedAuditContext)})
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise RegisteredExecutionError("CONTRACT_INVALID") from None


def _command(value):
    try:
        detached = _snapshot(value)
        checked = validate_command(detached)
    except ExecutorContractError:
        raise RegisteredExecutionError("COMMAND_INVALID") from None
    if checked.executor_mode != "CREATE_DRAFT":
        raise RegisteredExecutionError("UNSUPPORTED_EXECUTOR_MODE")
    return detached, checked


def _lock_registration(env, registration_id):
    # Consistent order: registration before the financial vendor/PO guards.
    # No write or internal commit; a stale RR snapshot causes a PG failure.
    env.cr.execute("SELECT id FROM ap_security_workflow_registration WHERE id = %s FOR UPDATE",
                   (registration_id,))
    row = env.cr.fetchone()
    if row != (registration_id,):
        raise RegisteredExecutionError("REGISTRATION_CHANGED")


def _verified_result(env, result, *, resolved, audit, command, checked, before):
    try:
        result = _snapshot(result)
        required = {"schema_version", "status", "effect_applied", "reason_codes",
                    "audit_complete", "deny_class"}
        if (not required <= set(result) or set(result) - required - {"receipt", "audit_event"}
                or result["schema_version"] != "draft-kernel-result/v1"
                or result["status"] not in {"CREATED", "REPLAY", "DENIED"}
                or type(result["effect_applied"]) is not bool
                or result["effect_applied"] is not (result["status"] == "CREATED")
                or type(result["audit_complete"]) is not bool):
            raise RegisteredExecutionError("EXECUTION_RESULT_INVALID")
        private = workflow_registry._private(env, resolved.workflow.company_id)
        after = audit_kernel._financial_snapshot(private, resolved.workflow)
        if not result["audit_complete"]:
            if (result["status"] != "DENIED" or result["reason_codes"] != ["AUDIT_UNAVAILABLE"]
                    or result["deny_class"] != "FAIL_CLOSED_UNAVAILABILITY"
                    or "receipt" in result or "audit_event" in result or after != before):
                raise RegisteredExecutionError("EXECUTION_RESULT_INVALID")
            return result
        event_info = result.get("audit_event")
        if (type(event_info) is not dict
                or set(event_info) != {"event_id", "event_sha256", "original_event_id"}
                or type(event_info["event_id"]) is not int or event_info["event_id"] <= 0
                or (event_info["original_event_id"] is not None and (
                    type(event_info["original_event_id"]) is not int
                    or event_info["original_event_id"] <= 0))):
            raise RegisteredExecutionError("EXECUTION_RESULT_INVALID")
        event = private["ap.security.audit.event"].browse(event_info["event_id"]).exists()
        payload = audit_kernel._verify_event(event)
        config = resolved.workflow
        expected_subject = {
            "company_id": config.company_id, "executor_user_id": config.executor_user_id,
            "scenario_id": config.scenario_id, "document_sha256": config.document_sha256,
            "executor_mode": "CREATE_DRAFT", "policy_version": config.policy_version,
            "workflow_sha256": audit_kernel._workflow_hash(config),
            "command_sha256": canonical_command_sha256(command),
            "action_sha256": checked.action_hash, "idempotency_key": command["idempotency_key"],
        }
        if (payload["context"] != asdict(audit) or payload["subject"] != expected_subject
                or event_info != {"event_id": event.id, "event_sha256": event.event_sha256,
                                  "original_event_id": event.original_event_id.id or None}
                or payload["outcome"]["status"] != result["status"]
                or payload["outcome"]["effect_applied"] is not result["effect_applied"]
                or payload["outcome"]["reason_codes"] != result["reason_codes"]
                or payload["outcome"]["deny_class"] != result["deny_class"]
                or payload["outcome"]["before_sha256"] != before
                or payload["outcome"]["after_sha256"] != after
                or _bytes(payload["receipt"]) != _bytes(result.get("receipt"))):
            raise RegisteredExecutionError("EXECUTION_RESULT_INVALID")
        return result
    except (DatabaseError, RegisteredExecutionError):
        raise
    except Exception:
        raise RegisteredExecutionError("EXECUTION_RESULT_INVALID") from None


def create_registered_draft_audited(
    env, *, registration_id, expected_company_id, expected_executor_user_id,
    expected_scenario_id, command, audit, document,
):
    """Consume only a registered CREATE workflow; the caller still must commit.

    Inputs are supplied by trusted administrative integration, not exposed as
    RPC fields. The complete v2 capability command remains untrusted and the
    financial kernel independently revalidates it under its existing locks.
    """
    workflow_registry._registrar(env)
    try:
        audit = _audit_context(audit)
        provenance = WorkflowProvenance(code_commit=audit.code_commit,
            code_sha256=audit.code_sha256, configuration_sha256=audit.configuration_sha256)
        command, checked = _command(command)
        arguments = dict(registration_id=registration_id,
            expected_company_id=expected_company_id,
            expected_executor_user_id=expected_executor_user_id,
            expected_scenario_id=expected_scenario_id, document=document, provenance=provenance)
        with env.cr.savepoint():
            resolved = workflow_registry.resolve_draft_workflow(env, **arguments)
            _lock_registration(env, resolved.registration_id)
            locked = workflow_registry.resolve_draft_workflow(env, **arguments)
            if locked != resolved:
                raise RegisteredExecutionError("REGISTRATION_CHANGED")
            config = locked.workflow
            if (checked.scenario_id != config.scenario_id
                    or checked.document_sha256 != config.document_sha256
                    or checked.policy_version != config.policy_version):
                raise RegisteredExecutionError("WORKFLOW_BINDING_MISMATCH")
            private = workflow_registry._private(env, config.company_id)
            before = audit_kernel._financial_snapshot(private, config)
            result = audit_kernel.create_draft_audited(env, command=command,
                workflow=config, audit=audit, document=document)
            _after_registered_draft(result)
            if workflow_registry.resolve_draft_workflow(env, **arguments) != locked:
                raise RegisteredExecutionError("REGISTRATION_CHANGED")
            result = _verified_result(env, result, resolved=locked, audit=audit,
                command=command, checked=checked, before=before)
            return {"schema_version": SCHEMA_VERSION,
                "registration": {"registration_id": locked.registration_id,
                                 "registration_sha256": locked.registration_sha256},
                "result": result, "caller_transaction_pending": True}
    except (DatabaseError, RegisteredExecutionError, workflow_registry.WorkflowRegistryError):
        raise
    except Exception:
        # Any effect inside the external savepoint was already rolled back.
        raise RegisteredExecutionError("EXECUTION_UNAVAILABLE") from None
