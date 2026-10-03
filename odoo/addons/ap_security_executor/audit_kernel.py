# SPDX-License-Identifier: LGPL-3.0-or-later
"""Private operational audit boundary over the financial kernels.

No RPC capability, commit, attachment or scientific RunRecord is introduced.
Trusted administrative code supplies provenance. A database administrator can
rewrite SQL and hashes; this ledger does not claim cryptographic authenticity.
"""

from dataclasses import asdict, fields
from datetime import datetime, timezone
import hashlib
import json

from psycopg2 import OperationalError
from psycopg2.errors import DeadlockDetected, SerializationFailure
from psycopg2.extras import Json

from odoo import SUPERUSER_ID, api
from odoo.exceptions import ValidationError
from odoo.tools.misc import Callbacks

from . import draft_kernel, post_kernel
from .approval import ERROR_CODES
from .audit_contracts import AuditContractError, TrustedAuditContext, audit_digest
from .contracts import ExecutorContractError, _match, _snapshot, validate_command
from .draft_contracts import TrustedDraftWorkflow, canonical_command_sha256
from .identity import _admin_environment
from .post_contracts import TrustedPostWorkflow


_CODES = ERROR_CODES | frozenset({
    "ACCOUNTING_PERIOD_CLOSED", "AMOUNT_MISMATCH", "BANK_NOT_ALLOWED",
    "CURRENCY_MISMATCH", "DATE_OUTSIDE_WINDOW", "DUPLICATE_DOCUMENT",
    "EXECUTOR_IDENTITY_INVALID", "IDEMPOTENCY_CONFLICT", "IDEMPOTENCY_KEY_MISMATCH",
    "LINE_MISMATCH", "PERSISTED_STATE_MISMATCH", "PURCHASE_ORDER_MISMATCH",
    "PURCHASE_ORDER_NOT_CONFIRMED", "STATE_INVALID", "TARGET_MISMATCH", "TARGET_NOT_DRAFT",
    "UNEXPECTED_NOTIFICATION", "UNEXPECTED_POST_EFFECT", "UNSUPPORTED_EXECUTOR_MODE",
    "UNSUPPORTED_POST_STATE", "UNTRUSTED_FINANCIAL_DEFAULTS", "VENDOR_MISMATCH",
    "WORKFLOW_MISMATCH", "DRAFT_CONSISTENT", "APPROVED_POST_CONSISTENT",
    "KERNEL_UNAVAILABLE", "AUDIT_UNAVAILABLE",
})
_UNAVAILABLE = frozenset({"DEPENDENCY_UNAVAILABLE", "KERNEL_UNAVAILABLE", "AUDIT_UNAVAILABLE"})
_RULES = {
    "AMOUNT_MISMATCH": "R-POL-02", "CURRENCY_MISMATCH": "R-POL-02",
    "LINE_MISMATCH": "R-POL-02", "VENDOR_MISMATCH": "R-POL-02",
    "PURCHASE_ORDER_MISMATCH": "R-POL-02", "PURCHASE_ORDER_NOT_CONFIRMED": "R-POL-02",
    "BANK_NOT_ALLOWED": "R-POL-03", "DUPLICATE_DOCUMENT": "R-POL-05",
    "IDEMPOTENCY_KEY_MISMATCH": "R-POL-05", "IDEMPOTENCY_CONFLICT": "R-POL-05",
    "DRAFT_CONSISTENT": "R-POL-06", "APPROVED_POST_CONSISTENT": "R-POL-07",
    "DATE_OUTSIDE_WINDOW": "R-POL-11", "ACCOUNTING_PERIOD_CLOSED": "R-POL-11",
    **{code: "R-POL-09" for code in ERROR_CODES if code != "DEPENDENCY_UNAVAILABLE"},
    **{code: "R-POL-10" for code in _UNAVAILABLE},
}


class _AuditUnavailable(Exception):
    pass


class _KernelDenied(Exception):
    def __init__(self, result):
        self.result = result


def _after_financial_kernel(result):
    """Private test seam after the actual kernel, never a registered hook."""
    return None


def _after_audit_append(event):
    """Private test seam after the actual SQL append."""
    return None


def _plain(value):
    # Only reconstructed trusted dataclasses reach this conversion.
    if type(value) is dict:
        return {key: _plain(item) for key, item in value.items()}
    if type(value) in (tuple, list):
        return [_plain(item) for item in value]
    return value


def _reconstruct(value, cls):
    if type(value) is not cls:
        raise ValidationError("Invalid private audit contract.")
    try:
        return cls(**{item.name: getattr(value, item.name) for item in fields(cls)})
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise ValidationError("Invalid private audit contract.") from None


def _workflow_hash(workflow):
    return audit_digest(_plain(asdict(workflow)))


def _financial_snapshot(env, workflow, target_id=None):
    """Hash a scoped operational projection, not an independent full-state oracle.

    Raw financial fields exist transiently only to hash them. The projection
    excludes the serialization guard, audit rows and deferred rank queue.
    """
    env.flush_all()
    receipts = env["ap.security.draft.receipt"].search([
        ("company_id", "=", workflow.company_id),
        ("document_sha256", "=", workflow.document_sha256),
    ], order="id")
    move_ids = set(receipts.move_id.ids)
    move_ids.update(env["account.move.line"].search([
        ("purchase_line_id", "in", list(workflow.purchase_line_ids)),
        ("company_id", "=", workflow.company_id),
    ]).move_id.ids)
    if target_id:
        move_ids.add(target_id)
    moves = env["account.move"].browse(sorted(move_ids)).exists()
    projection = {
        "purchase": env["purchase.order"].browse(workflow.purchase_order_id).exists().read([
            "state", "company_id", "partner_id", "currency_id", "amount_total"]),
        "purchase_lines": env["purchase.order.line"].browse(workflow.purchase_line_ids).exists().read([
            "product_qty", "qty_invoiced", "qty_to_invoice", "price_unit", "discount", "tax_ids"]),
        "moves": moves.read(["state", "name", "posted_before", "company_id", "partner_id",
                             "partner_bank_id", "invoice_date", "date", "ref", "amount_total",
                             "amount_residual", "journal_id", "currency_id"]),
        "lines": moves.line_ids.sorted("id").read([
            "move_id", "account_id", "partner_id", "product_id", "product_uom_id", "quantity",
            "price_unit", "discount", "tax_ids", "balance", "amount_currency", "purchase_line_id",
            "reconciled", "matched_debit_ids", "matched_credit_ids"]),
        "receipts": receipts.read(["executor_mode", "command_sha256", "action_sha256", "receipt_payload"]),
        "nonces": env["ap.security.approval.nonce"].search([
            ("company_id", "=", workflow.company_id),
            ("executor_user_id", "=", workflow.executor_user_id),
        ], order="id").read(["state", "action_sha256", "command_sha256", "approval_sha256"]),
        "auxiliary_counts": {name: env[name].search_count([]) for name in (
            "account.payment", "account.partial.reconcile", "account.full.reconcile",
            "account.analytic.line", "mail.mail", "mail.notification", "ir.attachment")},
    }
    encoded = json.dumps(projection, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(b"tcc-operational-state/v1\0" + encoded).hexdigest()


def _validate_payload_shape(payload):
    # The writer accepts only our closed server-produced shape, never commands.
    required = {"schema_version", "context", "subject", "outcome", "received_policy",
                "provenance", "receipt", "approval", "original_event_id", "observed_at"}
    if type(payload) is not dict or set(payload) != required:
        raise _AuditUnavailable()
    if payload["schema_version"] != "operational-audit/v1":
        raise _AuditUnavailable()
    context = payload["context"]
    try:
        TrustedAuditContext(**context)
        digest = audit_digest(payload)
    except (AuditContractError, TypeError):
        raise _AuditUnavailable() from None
    subject, outcome = payload["subject"], payload["outcome"]
    if set(subject) != {"company_id", "executor_user_id", "scenario_id", "document_sha256",
                        "executor_mode", "policy_version", "workflow_sha256", "command_sha256",
                        "action_sha256", "idempotency_key"} or set(outcome) != {
        "status", "decision", "deny_class", "reason_codes", "rule_ids", "checks_scope",
        "administrative_caller_id", "financial_service_uid", "before_sha256", "after_sha256",
        "effect_applied", "financial_methods",
    }:
        raise _AuditUnavailable()
    for name in ("company_id", "executor_user_id"):
        if type(subject[name]) is not int or subject[name] <= 0:
            raise _AuditUnavailable()
    for name, definition in (("scenario_id", "scenarioId"), ("document_sha256", "rawDigest"),
                             ("policy_version", "version"), ("workflow_sha256", "digest"),
                             ("command_sha256", "digest"), ("action_sha256", "digest"),
                             ("idempotency_key", "digest")):
        _match(subject[name], definition)
    for name in ("before_sha256", "after_sha256"):
        _match(outcome[name], "digest")
    if (type(outcome["administrative_caller_id"]) is not int or outcome["administrative_caller_id"] <= 0
            or type(outcome["financial_service_uid"]) is not int or outcome["financial_service_uid"] != SUPERUSER_ID
            or type(outcome["reason_codes"]) is not list or type(outcome["rule_ids"]) is not list):
        raise _AuditUnavailable()
    status = outcome["status"]
    mode = subject["executor_mode"]
    if (status not in {"CREATED", "POSTED", "REPLAY", "DENIED"}
            or mode not in {"CREATE_DRAFT", "POST_APPROVED"}
            or (status == "CREATED" and mode != "CREATE_DRAFT")
            or (status == "POSTED" and mode != "POST_APPROVED")
            or not outcome["reason_codes"] or any(type(code) is not str or code not in _CODES
                                                   for code in outcome["reason_codes"])):
        raise _AuditUnavailable()
    expected_methods = ["account.move.create"] if status == "CREATED" else (
        ["account.move.action_post"] if status == "POSTED" else [])
    expected_decision = "DENY" if status == "DENIED" else ("ALLOW" if mode == "CREATE_DRAFT" else "REVIEW")
    expected_class = ("FAIL_CLOSED_UNAVAILABILITY" if any(code in _UNAVAILABLE for code in outcome["reason_codes"])
                      else "POLICY_RULE") if status == "DENIED" else None
    if (outcome["decision"] != expected_decision or outcome["deny_class"] != expected_class
            or outcome["financial_methods"] != expected_methods
            or outcome["effect_applied"] is not (status in {"CREATED", "POSTED"})
            or any(type(rule) is not str or rule not in set(_RULES.values()) for rule in outcome["rule_ids"])
            or outcome["checks_scope"] not in {"PERSISTED_REPLAY", "FULL_SERVER_REVALIDATION",
                                                "DENIED_AFTER_KERNEL_ROLLBACK", "POST_ROLLBACK_KERNEL_FAILURE"}):
        raise _AuditUnavailable()
    receipt, original = payload["receipt"], payload["original_event_id"]
    if status == "DENIED":
        if receipt is not None or original is not None or outcome["effect_applied"] is not False:
            raise _AuditUnavailable()
    elif (type(receipt) is not dict or type(receipt.get("receipt_id")) is not int
          or receipt["receipt_id"] <= 0
          or (status == "REPLAY" and (type(original) is not int or original <= 0))
          or (status != "REPLAY" and original is not None)):
        raise _AuditUnavailable()
    if receipt is not None:
        if set(receipt) != {"receipt_id", "move_id", "idempotency_key", "action_hash"} | (
                {"approval_ledger_id"} if mode == "POST_APPROVED" else set()):
            raise _AuditUnavailable()
        for name in ("receipt_id", "move_id") + (("approval_ledger_id",) if mode == "POST_APPROVED" else ()):
            if type(receipt[name]) is not int or receipt[name] <= 0:
                raise _AuditUnavailable()
        if receipt["idempotency_key"] != subject["idempotency_key"] or receipt["action_hash"] != subject["action_sha256"]:
            raise _AuditUnavailable()
    policy, provenance, approval = payload["received_policy"], payload["provenance"], payload["approval"]
    if set(policy) != {"decision", "sha256"} or policy["decision"] not in {"ALLOW", "REVIEW", "DENY"}:
        raise _AuditUnavailable()
    _match(policy["sha256"], "digest")
    expected_provenance = {"document": "UNTRUSTED_HASH_BOUND", "workflow": "TRUSTED_ADMIN_REGISTRATION",
        "command": "UNTRUSTED_STRUCTURALLY_VALIDATED", "document_bytes_verified": False,
        "financial_effect": "SERVER_REVALIDATED" if status in {"CREATED", "POSTED"} else "NONE",
        "field_origins_version": "audit-field-origins/v1",
        "method_trace": "SUCCESSFUL_EFFECT_METHODS_ONLY", "attempted_method_trace_complete": False}
    if provenance != expected_provenance:
        raise _AuditUnavailable()
    if mode == "POST_APPROVED" and status != "DENIED":
        if set(approval) != {"ledger_id", "key_id", "fixture_id", "scenario_id", "approval_sha256",
                             "nonce_sha256", "state"} or approval["ledger_id"] != receipt["approval_ledger_id"]:
            raise _AuditUnavailable()
        for name, definition in (("key_id", "version"), ("fixture_id", "reference"),
                                 ("scenario_id", "scenarioId"), ("approval_sha256", "digest"),
                                 ("nonce_sha256", "digest")):
            _match(approval[name], definition)
        if approval["state"] != "consumed":
            raise _AuditUnavailable()
    elif approval is not None:
        raise _AuditUnavailable()
    _match(payload["observed_at"], "utcTime")
    return digest


def _validate_payload(payload):
    try:
        return _validate_payload_shape(payload)
    except (AuditContractError, ExecutorContractError, TypeError, ValueError, KeyError,
            OverflowError, RecursionError):
        raise _AuditUnavailable() from None


def _verify_event(event):
    if len(event) != 1:
        raise _AuditUnavailable()
    event.invalidate_recordset()
    payload = event.event_payload
    if event.event_sha256 != _validate_payload(payload):
        raise _AuditUnavailable()
    subject, outcome, context = payload["subject"], payload["outcome"], payload["context"]
    receipt_id = payload["receipt"]["receipt_id"] if payload["receipt"] else False
    if (event.company_id.id != subject["company_id"]
            or event.executor_user_id.id != subject["executor_user_id"]
            or event.run_id != context["run_id"] or event.attempt_id != context["attempt_id"]
            or event.executor_mode != subject["executor_mode"] or event.status != outcome["status"]
            or event.receipt_id.id != receipt_id
            or event.success_receipt_id.id != (receipt_id if event.status in {"CREATED", "POSTED"} else False)
            or event.original_event_id.id != (payload["original_event_id"] or False)):
        raise _AuditUnavailable()
    if receipt_id:
        receipt = event.receipt_id
        if (receipt.company_id != event.company_id or receipt.executor_user_id != event.executor_user_id
                or receipt.executor_mode != event.executor_mode
                or receipt.receipt_payload != payload["receipt"]
                or receipt.document_sha256 != subject["document_sha256"]
                or receipt.command_sha256 != subject["command_sha256"]
                or receipt.action_sha256 != subject["action_sha256"]
                or receipt.idempotency_key != subject["idempotency_key"]):
            raise _AuditUnavailable()
    return payload


def _append_event(env, payload):
    digest = _validate_payload(payload)
    subject, context, outcome = payload["subject"], payload["context"], payload["outcome"]
    receipt_id = payload["receipt"]["receipt_id"] if payload["receipt"] else None
    env["ap.security.audit.event"].flush_model()
    env.cr.execute("""
        INSERT INTO ap_security_audit_event
            (company_id, executor_user_id, run_id, attempt_id, executor_mode, status,
             receipt_id, success_receipt_id, original_event_id, event_sha256, event_payload,
             create_uid, write_uid, create_date, write_date)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,timezone('UTC',now()),timezone('UTC',now()))
        RETURNING id
    """, (subject["company_id"], subject["executor_user_id"], context["run_id"], context["attempt_id"],
          subject["executor_mode"], outcome["status"], receipt_id,
          receipt_id if outcome["status"] in {"CREATED", "POSTED"} else None,
          payload["original_event_id"], digest, Json(payload), env.uid, env.uid))
    event = env["ap.security.audit.event"].browse(env.cr.fetchone()[0])
    _verify_event(event)
    return event


def _original_event(env, receipt, *, workflow, audit, action_hash=None, command_hash=None):
    event = env["ap.security.audit.event"].search([("success_receipt_id", "=", receipt.id)])
    payload = _verify_event(event)
    subject, context = payload["subject"], payload["context"]
    config = workflow.draft if type(workflow) is TrustedPostWorkflow else workflow
    if (subject["workflow_sha256"] != _workflow_hash(workflow)
            or subject["company_id"] != config.company_id
            or subject["executor_user_id"] != config.executor_user_id
            or subject["document_sha256"] != config.document_sha256
            or subject["scenario_id"] != config.scenario_id or subject["policy_version"] != config.policy_version
            or (action_hash is not None and subject["action_sha256"] != action_hash)
            or (command_hash is not None and subject["command_sha256"] != command_hash)
            or any(context[name] != getattr(audit, name) for name in (
                "code_commit", "code_sha256", "configuration_sha256"))):
        raise _AuditUnavailable()
    return event


def _draft_origin(env, registered, audit):
    config = registered.draft
    receipt = env["ap.security.draft.receipt"].search([
        ("company_id", "=", config.company_id), ("document_sha256", "=", config.document_sha256),
        ("executor_mode", "=", "CREATE_DRAFT"),
    ])
    if len(receipt) != 1 or receipt.move_id.id != registered.target_move_id:
        raise _AuditUnavailable()
    # An altered proposal is a business denial, not unavailable audit storage.
    # Authenticate the original trusted receipt; let the POST kernel compare
    # candidate fields with its independently reconstructed ERP action.
    return _original_event(env, receipt, workflow=config, audit=audit)


def _payload(admin, private, command, workflow, audit, checked, result, before, after, original=None):
    config = workflow.draft if type(workflow) is TrustedPostWorkflow else workflow
    status = result["status"]
    codes = result["reason_codes"]
    if type(codes) is not list or not codes or any(type(code) is not str or code not in _CODES for code in codes):
        raise _AuditUnavailable()
    deny_class = ("FAIL_CLOSED_UNAVAILABILITY" if any(code in _UNAVAILABLE for code in codes)
                  else "POLICY_RULE") if status == "DENIED" else None
    approval = None
    if result.get("receipt", {}).get("approval_ledger_id"):
        ledger = private["ap.security.approval.nonce"].browse(result["receipt"]["approval_ledger_id"])
        approval = {"ledger_id": ledger.id, "key_id": ledger.key_id, "fixture_id": ledger.fixture_id,
                    "scenario_id": ledger.scenario_id, "approval_sha256": ledger.approval_sha256,
                    "nonce_sha256": ledger.nonce_sha256, "state": ledger.state}
    rules = sorted({_RULES[code] for code in codes if code in _RULES})
    if status == "POSTED":
        rules.append("R-POL-09")
    return {
        "schema_version": "operational-audit/v1", "context": asdict(audit),
        "subject": {"company_id": config.company_id, "executor_user_id": config.executor_user_id,
            "scenario_id": config.scenario_id, "document_sha256": config.document_sha256,
            "executor_mode": checked.executor_mode, "policy_version": config.policy_version,
            "workflow_sha256": _workflow_hash(workflow), "command_sha256": canonical_command_sha256(command),
            "action_sha256": checked.action_hash, "idempotency_key": command["idempotency_key"]},
        "outcome": {"status": status, "decision": "DENY" if status == "DENIED" else (
            "ALLOW" if checked.executor_mode == "CREATE_DRAFT" else "REVIEW"), "deny_class": deny_class,
            "reason_codes": list(codes), "rule_ids": rules,
            "checks_scope": "PERSISTED_REPLAY" if status == "REPLAY" else (
                "POST_ROLLBACK_KERNEL_FAILURE" if "KERNEL_UNAVAILABLE" in codes else (
                    "DENIED_AFTER_KERNEL_ROLLBACK" if status == "DENIED" else "FULL_SERVER_REVALIDATION")),
            "administrative_caller_id": admin.uid, "financial_service_uid": SUPERUSER_ID,
            "before_sha256": before, "after_sha256": after, "effect_applied": result["effect_applied"],
            "financial_methods": ["account.move.create"] if status == "CREATED" else (
                ["account.move.action_post"] if status == "POSTED" else [])},
        "received_policy": {"decision": command["policy_decision"]["decision"],
                            "sha256": audit_digest(command["policy_decision"])},
        "provenance": {"document": "UNTRUSTED_HASH_BOUND", "workflow": "TRUSTED_ADMIN_REGISTRATION",
            "command": "UNTRUSTED_STRUCTURALLY_VALIDATED", "document_bytes_verified": False,
            "financial_effect": "SERVER_REVALIDATED" if status in {"CREATED", "POSTED"} else "NONE",
            "field_origins_version": "audit-field-origins/v1",
            "method_trace": "SUCCESSFUL_EFFECT_METHODS_ONLY", "attempted_method_trace_complete": False},
        "receipt": result.get("receipt"), "approval": approval,
        "original_event_id": original.id if original else None,
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _unavailable(mode):
    return {"schema_version": "draft-kernel-result/v1" if mode == "CREATE_DRAFT" else "post-kernel-result/v1",
            "status": "DENIED", "effect_applied": False, "reason_codes": ["AUDIT_UNAVAILABLE"],
            "deny_class": "FAIL_CLOSED_UNAVAILABILITY", "audit_complete": False}


def _complete(result, event):
    return dict(result, audit_complete=True, audit_event={"event_id": event.id,
        "event_sha256": event.event_sha256, "original_event_id": event.original_event_id.id or None},
        deny_class=event.event_payload["outcome"]["deny_class"])


def _run_committed_audit(registry, pending, event_id, event_hash, company_id):
    # An outer caller may roll back after this helper returned. Do not run even
    # metadata callbacks without the very same committed successful audit row.
    try:
        with registry.cursor() as cursor:
            env = api.Environment(cursor, SUPERUSER_ID, draft_kernel._context(company_id), su=True)
            event = env["ap.security.audit.event"].browse(event_id).exists()
            valid = bool(event and event.event_sha256 == event_hash and event.status == "POSTED")
            if valid:
                _verify_event(event)
        if valid:
            pending.run()
    except (OperationalError, _AuditUnavailable):
        return None
    finally:
        pending.clear()


def _execute(env, *, command, workflow, audit, mode, authority=None, key=None):
    admin = _admin_environment(env)
    audit = _reconstruct(audit, TrustedAuditContext)
    workflow = _reconstruct(workflow, TrustedDraftWorkflow if mode == "CREATE_DRAFT" else TrustedPostWorkflow)
    config = workflow if mode == "CREATE_DRAFT" else workflow.draft
    try:
        command = _snapshot(command)
        checked = validate_command(command)
    except ExecutorContractError:
        raise ValidationError("Invalid private audit command.") from None
    if checked.executor_mode != mode:
        raise ValidationError("Invalid private audit command.")
    if not (admin["res.company"].browse(config.company_id).exists()
            and admin["res.users"].browse(config.executor_user_id).exists()):
        raise ValidationError("Invalid private audit scope.")
    private = api.Environment(admin.cr, SUPERUSER_ID, draft_kernel._context(config.company_id), su=True)
    original_pending, pending = admin.cr.postcommit, Callbacks()
    before = None
    event = None
    result = None
    completed = None
    transferred = False
    admin.cr.postcommit = pending
    try:
        try:
            with admin.cr.savepoint():
                before = _financial_snapshot(private, config, getattr(workflow, "target_move_id", None))
        except (SerializationFailure, DeadlockDetected):
            raise
        except Exception:
            return _unavailable(mode)
        try:
            with admin.cr.savepoint():
                neutral = api.Environment(admin.cr, config.executor_user_id,
                                          draft_kernel._context(config.company_id), su=False)
                if any(neutral["ap.security.audit.event"].browse().has_access(operation)
                       for operation in ("read", "write", "create", "unlink")):
                    raise _KernelDenied({"schema_version": "draft-kernel-result/v1" if mode == "CREATE_DRAFT"
                        else "post-kernel-result/v1", "status": "DENIED", "effect_applied": False,
                        "reason_codes": ["EXECUTOR_IDENTITY_INVALID"]})
                if mode == "POST_APPROVED":
                    _draft_origin(private, workflow, audit)
                try:
                    result = (draft_kernel.create_draft_atomic(admin, command=command, workflow=workflow)
                              if mode == "CREATE_DRAFT" else post_kernel.post_bill_atomic(
                                  admin, command=command, workflow=workflow, authority=authority, key=key))
                    _after_financial_kernel(result)
                except (SerializationFailure, DeadlockDetected):
                    raise
                except Exception:
                    raise _KernelDenied({"schema_version": "draft-kernel-result/v1" if mode == "CREATE_DRAFT"
                        else "post-kernel-result/v1", "status": "DENIED", "effect_applied": False,
                        "reason_codes": ["KERNEL_UNAVAILABLE"]}) from None
                if result["status"] == "DENIED":
                    raise _KernelDenied(result)
                original = None
                if result["status"] == "REPLAY":
                    receipt = private["ap.security.draft.receipt"].browse(result["receipt"]["receipt_id"])
                    original = _original_event(private, receipt, workflow=workflow, audit=audit,
                        action_hash=checked.action_hash, command_hash=canonical_command_sha256(command))
                after = _financial_snapshot(private, config, getattr(workflow, "target_move_id", None))
                event = _append_event(private, _payload(admin, private, command, workflow, audit,
                    checked, result, before, after, original))
                _after_audit_append(event)
                _verify_event(event)
                private.flush_all()
                completed = _complete(result, event)
        except (SerializationFailure, DeadlockDetected):
            raise
        except _KernelDenied as denied:
            pending.clear()
            result = denied.result
            try:
                with admin.cr.savepoint():
                    after = _financial_snapshot(private, config, getattr(workflow, "target_move_id", None))
                    if after != before:
                        raise _AuditUnavailable()
                    event = _append_event(private, _payload(admin, private, command, workflow, audit,
                        checked, result, before, after))
                    _after_audit_append(event)
                    _verify_event(event)
                    completed = _complete(result, event)
            except (SerializationFailure, DeadlockDetected):
                raise
            except Exception:
                return _unavailable(mode)
        except Exception:
            return _unavailable(mode)
        if result["status"] == "POSTED":
            event_id, event_hash = event.id, event.event_sha256
            original_pending.add(lambda: _run_committed_audit(
                admin.registry, pending, event_id, event_hash, config.company_id))
            transferred = True
        else:
            pending.clear()
        return completed
    except BaseException:
        pending.clear()
        raise
    finally:
        admin.cr.postcommit = original_pending
        # On a storage failure the pending native hook must not escape.
        if not transferred:
            pending.clear()


def create_draft_audited(env, *, command, workflow, audit):
    """Private administrative boundary; no commit, RPC or document attachment."""
    return _execute(env, command=command, workflow=workflow, audit=audit, mode="CREATE_DRAFT")


def post_bill_audited(env, *, command, workflow, authority, key, audit):
    """Private reviewed POST boundary; public execute remains fail-closed."""
    return _execute(env, command=command, workflow=workflow, audit=audit,
                    mode="POST_APPROVED", authority=authority, key=key)
