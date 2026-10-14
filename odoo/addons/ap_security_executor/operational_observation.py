# SPDX-License-Identifier: LGPL-3.0-or-later
"""Read-only, candidate-bound administrative observations for policy.

This is advisory state, not transactional authorization, a freshness guarantee
or an oracle. The financial kernel still revalidates under its own locks. No
model, RPC capability, approval, internal commit or retry is introduced.
"""

from dataclasses import asdict
from datetime import date, datetime, timezone
import hashlib

from psycopg2 import Error as DatabaseError

from odoo import SUPERUSER_ID, api
from odoo.exceptions import ValidationError

from . import registered_post, workflow_registry
from .contracts import ExecutorContractError, _bytes, _snapshot, canonical_action_bytes
from .draft_contracts import bill_idempotency_key
from .draft_kernel import _context


SCHEMA_VERSION = "registered-operational-observation/v1"
HASH_DOMAIN = b"tcc-operational-observation/v1\0"
ERROR_CODES = frozenset({
    "ACTION_INVALID", "WORKFLOW_BINDING_MISMATCH", "TARGET_MISMATCH",
    "REGISTRATION_CHANGED", "ORIGIN_CHANGED", "STATE_UNAVAILABLE",
})


class OperationalObservationError(ValidationError):
    """Finite category, never caller values, native SQL or exception details."""

    def __init__(self, code="STATE_UNAVAILABLE"):
        self.code = code if type(code) is str and code in ERROR_CODES else "STATE_UNAVAILABLE"
        super().__init__("Private operational observation rejected.")


class _AuditPreflightUnavailable(Exception):
    pass


def _after_observation_read():
    """Private negative-test seam; no externally supplied hook or clock."""
    return None


def _candidate(value):
    try:
        action = _snapshot(value)
        digest = "sha256:" + hashlib.sha256(canonical_action_bytes(action)).hexdigest()
        return action, digest
    except ExecutorContractError:
        raise OperationalObservationError("ACTION_INVALID") from None


def _duplicates(env, config, action, origin):
    key = bill_idempotency_key(document_sha256=config.document_sha256,
        company_id=config.company_id, vendor_id=config.vendor_id,
        purchase_order_id=config.purchase_order_id, purchase_line_ids=config.purchase_line_ids)
    # Namespace-independent: either a CREATE or a POST receipt makes this a
    # new duplicate evaluation. A retry must preserve the original command.
    receipt_domain = [
        ("company_id", "=", config.company_id), "|",
        ("document_sha256", "=", config.document_sha256), ("idempotency_key", "=", key),
    ]
    move_domain = [
        ("company_id", "=", config.company_id), ("partner_id", "=", config.vendor_id),
        ("move_type", "=", "in_invoice"), ("ref", "=", action["document_ref"]),
        ("state", "!=", "cancel"),
    ]
    if origin is not None:
        # Only the verified origin can be excluded; never the proposed ID.
        receipt_domain.append(("id", "!=", origin["create_receipt_id"]))
        move_domain.append(("id", "!=", origin["target_move_id"]))
    document_duplicate = bool(env["ap.security.draft.receipt"].search_count(receipt_domain, limit=1))
    reference_duplicate = bool(env["account.move"].search_count(move_domain, limit=1))
    return document_duplicate, reference_duplicate


def _accounting_period_open(env, config, action):
    company = env["res.company"].browse(config.company_id).exists()
    journal = env["account.journal"].browse(config.journal_id).exists()
    if len(company) != 1 or len(journal) != 1 or journal.company_id != company:
        raise OperationalObservationError("STATE_UNAVAILABLE")
    # sudo changes access, not the UID used by Odoo's lock-exception semantics.
    violations = company.with_user(config.executor_user_id).sudo()._get_violated_lock_dates(
        date.fromisoformat(action["invoice_date"]), False, journal)
    return not bool(violations)


def _audit_preflight(env, config):
    """Read actual append prerequisites without an INSERT, sequence or repair.

This only checks current prerequisites. Successful SELECT/config reads do not
guarantee a future append, nor establish overall supervisor availability.
"""
    try:
        # A read error is rolled back locally before reporting UNAVAILABLE.
        # Direct PostgreSQL errors propagate, including serialization/deadlock.
        with env.cr.savepoint(flush=False):
            if env["ir.attachment"]._storage() != "db":
                raise _AuditPreflightUnavailable()
            if env["ir.module.module"].search_count([
                    ("name", "=", "attachment_indexation"),
                    ("state", "in", ["installed", "to upgrade", "to remove", "to install"]),
            ], limit=1):
                raise _AuditPreflightUnavailable()
            if env["ir.default"].search_count([
                    ("field_id.model", "in", ["ap.security.audit.event", "ir.attachment"]),
                    ("user_id", "in", [False, SUPERUSER_ID]),
                    ("company_id", "in", [False, config.company_id]),
            ], limit=1):
                raise _AuditPreflightUnavailable()
            neutral = api.Environment(env.cr, config.executor_user_id,
                _context(config.company_id), su=False)
            if any(neutral["ap.security.audit.event"].browse().has_access(operation)
                    for operation in ("read", "write", "create", "unlink")):
                raise _AuditPreflightUnavailable()
            # Fixed table/column names; no proposal value is SQL authority.
            env.cr.execute("SELECT id, event_sha256, event_payload FROM ap_security_audit_event WHERE company_id = %s LIMIT 1",
                (config.company_id,))
            env.cr.fetchone()
        return "AVAILABLE"
    except DatabaseError:
        raise
    except Exception:
        return "UNAVAILABLE"


def observe_registered_policy_state(
    env, *, registration_id, expected_company_id, expected_executor_user_id,
    expected_scenario_id, document, provenance, canonical_action,
):
    """Observe only an exact registration/candidate; caller owns transaction.

Business mismatches (amount/vendor/bank/ref/date) stay in the candidate for
policy to reject. Structural, scope/provenance or POST-target mismatches are
errors, not silently repaired proposals. No favorable state defaults exist.
"""
    workflow_registry._registrar(env)
    action, action_hash = _candidate(canonical_action)
    arguments = dict(registration_id=registration_id, expected_company_id=expected_company_id,
        expected_executor_user_id=expected_executor_user_id, expected_scenario_id=expected_scenario_id,
        document=document, provenance=provenance)
    try:
        with env.cr.savepoint(flush=False):
            resolved = workflow_registry.resolve_draft_workflow(env, **arguments)
            config = resolved.workflow
            if (action["scenario_id"] != config.scenario_id
                    or action["document_sha256"] != config.document_sha256
                    or action["policy_version"] != config.policy_version):
                raise OperationalObservationError("WORKFLOW_BINDING_MISMATCH")
            private = workflow_registry._private(env, config.company_id)
            origin = None
            if action["executor_mode"] == "POST_APPROVED":
                _, origin = registered_post._origin(private, resolved, resolved.provenance)
                if action["target_move_id"] != origin["target_move_id"]:
                    raise OperationalObservationError("TARGET_MISMATCH")
            document_duplicate, reference_duplicate = _duplicates(private, config, action, origin)
            period_open = _accounting_period_open(private, config, action)
            audit_state = _audit_preflight(private, config)
            _after_observation_read()
            if workflow_registry.resolve_draft_workflow(env, **arguments) != resolved:
                raise OperationalObservationError("REGISTRATION_CHANGED")
            if origin is not None and registered_post._origin(private, resolved, resolved.provenance)[1] != origin:
                raise OperationalObservationError("ORIGIN_CHANGED")
            observation = {
                "schema_version": SCHEMA_VERSION,
                "registration": {"registration_id": resolved.registration_id,
                    "registration_sha256": resolved.registration_sha256},
                "provenance": asdict(resolved.provenance),
                "scope": {"company_id": config.company_id, "executor_user_id": config.executor_user_id,
                    "vendor_id": config.vendor_id, "purchase_order_id": config.purchase_order_id,
                    "purchase_line_ids": list(config.purchase_line_ids), "journal_id": config.journal_id,
                    "allowed_bank_ids": list(config.allowed_bank_ids), "scenario_id": config.scenario_id,
                    "document_sha256": config.document_sha256, "policy_version": config.policy_version,
                    "invoice_date_min": config.invoice_date_min, "invoice_date_max": config.invoice_date_max,
                    "monetary_tolerance": config.monetary_tolerance, "quantity_scale": config.quantity_scale,
                    "executor_mode": action["executor_mode"], "action_sha256": action_hash,
                    "document_ref": action["document_ref"], "invoice_date": action["invoice_date"],
                    "target_move_id": origin["target_move_id"] if origin else None},
                "facts": {"document_duplicate": document_duplicate,
                    "reference_duplicate": reference_duplicate,
                    "duplicate_detected": document_duplicate or reference_duplicate,
                    "accounting_period_open": period_open},
                "preflight": {"state": "AVAILABLE", "audit": audit_state},
                "observed_at": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            }
            observation["observation_sha256"] = "sha256:" + hashlib.sha256(HASH_DOMAIN + _bytes(observation)).hexdigest()
            return observation
    except (DatabaseError, OperationalObservationError, workflow_registry.WorkflowRegistryError,
            registered_post.RegisteredPostError):
        raise
    except Exception:
        raise OperationalObservationError("STATE_UNAVAILABLE") from None
