# SPDX-License-Identifier: LGPL-3.0-or-later
"""Private administrative binding of a document to an immutable draft workflow.

No RPC endpoint, financial authorization, internal commit or dataset oracle is
introduced. SQL concurrency errors propagate for whole-transaction retry.
"""

from decimal import Decimal, DecimalException
import re

from psycopg2 import Error as DatabaseError
from psycopg2.extras import Json

from odoo import SUPERUSER_ID, api
from odoo.exceptions import AccessError, ValidationError

from .document_contracts import DocumentContractError, validate_source_document
from .draft_contracts import TrustedDraftWorkflow
from .draft_kernel import _Denied, _bound_records, _context, _line_facts
from .identity import assert_executor_identity
from .workflow_contracts import (
    REGISTRATION_SCHEMA_VERSION, ResolvedDraftRegistration, WorkflowContractError,
    WorkflowProvenance, reconstruct, registration_payload, registration_sha256,
    validate_registration_payload,
)


_MODEL = "ap.security.workflow.registration"
ERROR_CODES = frozenset({
    "CONTRACT_INVALID", "REGISTRATION_NOT_FOUND", "REGISTRATION_CONFLICT",
    "REGISTRATION_INTEGRITY_INVALID", "REGISTRATION_BINDING_MISMATCH",
    "REGISTRATION_PROVENANCE_MISMATCH", "REGISTRATION_DEFAULTS_INVALID",
    "REGISTRATION_UNAVAILABLE",
    "EXECUTOR_IDENTITY_INVALID", "WORKFLOW_STATE_INVALID", "BANK_NOT_ALLOWED",
    "DOCUMENT_INVALID", "DOCUMENT_EMPTY", "DOCUMENT_TOO_LARGE",
    "DOCUMENT_MIME_INVALID", "DOCUMENT_HASH_MISMATCH",
})


class WorkflowRegistryError(ValidationError):
    """Known category without exposing caller values or persisted JSON."""

    def __init__(self, code="CONTRACT_INVALID"):
        self.code = code if type(code) is str and code in ERROR_CODES else "CONTRACT_INVALID"
        super().__init__("Private workflow registration rejected.")


def _registrar(env):
    # sudo grants access, not origin. Rebuild the real user's environment to
    # check groups independently of the caller's su flag and hostile context.
    if type(env.uid) is not int or env.uid <= 0:
        raise AccessError("Administrative workflow registration required.")
    if env.uid == SUPERUSER_ID:
        return SUPERUSER_ID
    real = api.Environment(env.cr, env.uid, {}, su=False)
    user = real.user
    if (not user.exists() or not user.active or user.share
            or user.has_group("ap_security_executor.group_executor")
            or not user.has_group("base.group_system")):
        raise AccessError("Administrative workflow registration required.")
    return user.id


def _after_registration_insert(registration):
    """Private fault seam after real insertion; no public switch or plugin."""
    return None


def _contract(value, cls):
    try:
        return reconstruct(value, cls)
    except WorkflowContractError:
        raise WorkflowRegistryError("CONTRACT_INVALID") from None


def _document(document, document_sha256):
    try:
        return validate_source_document(document, document_sha256=document_sha256)
    except DocumentContractError as error:
        raise WorkflowRegistryError(error.code) from None


def _private(env, company_id):
    return api.Environment(env.cr, SUPERUSER_ID, _context(company_id), su=True)


def _defaults(env, company_id):
    if env["ir.default"].search_count([
        ("field_id.model", "=", _MODEL),
        ("user_id", "in", [False, SUPERUSER_ID]),
        ("company_id", "in", [False, company_id]),
    ], limit=1):
        raise WorkflowRegistryError("REGISTRATION_DEFAULTS_INVALID")


def _configuration(env, workflow):
    """Recheck current configuration without consuming quantity or writing it.

The financial kernel independently revalidates under its locks. Resolving a
registration after a successful draft must not treat consumed quantity as
loss of its immutable identity or silently mint a replacement configuration.
"""
    company = env["res.company"].browse(workflow.company_id)
    user = env["res.users"].browse(workflow.executor_user_id)
    try:
        assert_executor_identity(env, user, company=company)
        neutral = api.Environment(env.cr, user.id, _context(workflow.company_id), su=False)
        if any(neutral[_MODEL].browse().has_access(operation)
                for operation in ("read", "write", "create", "unlink")):
            raise WorkflowRegistryError("EXECUTOR_IDENTITY_INVALID")
    except (AccessError, ValidationError):
        raise WorkflowRegistryError("EXECUTOR_IDENTITY_INVALID") from None
    try:
        company, po, vendor, journal, account, lines = _bound_records(env, workflow)
        if po.state != "purchase":
            raise WorkflowRegistryError("WORKFLOW_STATE_INVALID")
        _line_facts(lines, workflow.quantity_scale, check_invoiceability=False)
        if (po.currency_id != company.currency_id or po.currency_id.decimal_places != 2
                or Decimal(str(po.currency_id.rounding)) != Decimal("0.01")):
            raise WorkflowRegistryError("WORKFLOW_STATE_INVALID")
        banks = env["res.partner.bank"].with_context(active_test=False).browse(
            workflow.allowed_bank_ids,
        ).exists()
        if (len(banks) != len(workflow.allowed_bank_ids)
                or any(not bank.active or not bank.allow_out_payment
                       or bank.partner_id != vendor or bank.company_id != company
                       for bank in banks)):
            raise WorkflowRegistryError("BANK_NOT_ALLOWED")
    except _Denied:
        raise WorkflowRegistryError("WORKFLOW_STATE_INVALID") from None
    except DecimalException:
        raise WorkflowRegistryError("WORKFLOW_STATE_INVALID") from None


def _checked_record(env, registration_id):
    records = env[_MODEL]
    records.invalidate_model(flush=False)
    registration = records.browse(registration_id).exists()
    if len(registration) != 1:
        raise WorkflowRegistryError("REGISTRATION_NOT_FOUND")
    try:
        payload = registration.registration_payload
        workflow, metadata, provenance, registrar = validate_registration_payload(payload)
        digest = registration_sha256(payload)
        if (type(registration.registration_sha256) is not str
                or registration.registration_sha256 != digest
                or registration.schema_version != REGISTRATION_SCHEMA_VERSION
                or registration.company_id.id != workflow.company_id
                or registration.executor_user_id.id != workflow.executor_user_id
                or registration.registrar_user_id.id != registrar
                or registration.create_uid.id != registrar or registration.write_uid.id != registrar
                or registration.po_id.id != workflow.purchase_order_id
                or registration.vendor_id.id != workflow.vendor_id
                or registration.journal_id.id != workflow.journal_id
                or registration.expense_account_id.id != workflow.expense_account_id
                or registration.scenario_id != workflow.scenario_id
                or registration.document_sha256 != workflow.document_sha256):
            raise WorkflowRegistryError("REGISTRATION_INTEGRITY_INVALID")
    except (WorkflowContractError, AttributeError, TypeError, ValueError, OverflowError):
        raise WorkflowRegistryError("REGISTRATION_INTEGRITY_INVALID") from None
    return registration, workflow, metadata, provenance


def _resolved(env, registration_id, *, expected_company_id, expected_executor_user_id,
              expected_scenario_id, document, provenance):
    registration, workflow, stored_document, stored_provenance = _checked_record(
        env, registration_id,
    )
    if (workflow.company_id != expected_company_id
            or workflow.executor_user_id != expected_executor_user_id
            or workflow.scenario_id != expected_scenario_id):
        raise WorkflowRegistryError("REGISTRATION_BINDING_MISMATCH")
    if stored_provenance != provenance:
        raise WorkflowRegistryError("REGISTRATION_PROVENANCE_MISMATCH")
    metadata = _document(document, workflow.document_sha256)
    if metadata != stored_document:
        raise WorkflowRegistryError("REGISTRATION_INTEGRITY_INVALID")
    _defaults(env, workflow.company_id)
    _configuration(env, workflow)
    return ResolvedDraftRegistration(
        registration.id, registration.registration_sha256, workflow, stored_provenance, stored_document,
    )


def _register_draft_workflow(env, *, workflow, document, provenance, registrar):
    """Insert or replay an exact trusted declaration in the caller's transaction.

The real registering identity is part of the immutable body. Another
administrator may resolve it, but cannot re-register/rebind it as their own.
"""
    workflow = _contract(workflow, TrustedDraftWorkflow)
    provenance = _contract(provenance, WorkflowProvenance)
    metadata = _document(document, workflow.document_sha256)
    private = _private(env, workflow.company_id)
    _defaults(private, workflow.company_id)
    _configuration(private, workflow)
    payload = registration_payload(workflow=workflow, document_metadata=metadata,
        provenance=provenance, registrar_user_id=registrar)
    digest = registration_sha256(payload)
    with env.cr.savepoint():
        private[_MODEL].flush_model()
        env.cr.execute("""
            INSERT INTO ap_security_workflow_registration
                (company_id, executor_user_id, registrar_user_id, po_id, vendor_id,
                 journal_id, expense_account_id, scenario_id, document_sha256,
                 schema_version, registration_sha256, registration_payload,
                 create_uid, write_uid, create_date, write_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, timezone('UTC', now()), timezone('UTC', now()))
            ON CONFLICT (company_id, scenario_id) DO NOTHING
            RETURNING id
        """, (workflow.company_id, workflow.executor_user_id, registrar,
            workflow.purchase_order_id, workflow.vendor_id, workflow.journal_id,
            workflow.expense_account_id, workflow.scenario_id, workflow.document_sha256,
            REGISTRATION_SCHEMA_VERSION, digest, Json(payload), registrar, registrar))
        inserted = env.cr.fetchone()
        if inserted:
            registration_id = inserted[0]
            private[_MODEL].invalidate_model(flush=False)
            _after_registration_insert(private[_MODEL].browse(registration_id))
        else:
            env.cr.execute("""
                SELECT id FROM ap_security_workflow_registration
                WHERE company_id = %s AND scenario_id = %s
            """, (workflow.company_id, workflow.scenario_id))
            previous = env.cr.fetchone()
            if not previous:
                raise WorkflowRegistryError("REGISTRATION_NOT_FOUND")
            registration_id = previous[0]
        registration, _, _, _ = _checked_record(private, registration_id)
        if registration.registration_sha256 != digest or registration.registration_payload != payload:
            raise WorkflowRegistryError("REGISTRATION_CONFLICT")
        return _resolved(private, registration_id,
            expected_company_id=workflow.company_id,
            expected_executor_user_id=workflow.executor_user_id,
            expected_scenario_id=workflow.scenario_id, document=document, provenance=provenance)


def _resolve_draft_workflow(env, *, registration_id, expected_company_id,
                           expected_executor_user_id, expected_scenario_id, document, provenance):
    """Resolve only exact expected bindings supplied by trusted administrative code."""
    provenance = _contract(provenance, WorkflowProvenance)
    if (any(type(value) is not int or value <= 0
            for value in (registration_id, expected_company_id, expected_executor_user_id))
            or type(expected_scenario_id) is not str
            or re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,63}", expected_scenario_id) is None):
        raise WorkflowRegistryError("CONTRACT_INVALID")
    private = _private(env, expected_company_id)
    return _resolved(private, registration_id,
        expected_company_id=expected_company_id,
        expected_executor_user_id=expected_executor_user_id,
        expected_scenario_id=expected_scenario_id, document=document, provenance=provenance)


def _runtime_call(function, env, **arguments):
    try:
        return function(env, **arguments)
    except (DatabaseError, WorkflowRegistryError):
        # Full transaction retry belongs to the caller; never reuse a failed
        # snapshot or conceal a database exception as a normal denial.
        raise
    except Exception:
        # The insertion savepoint has already unwound before this translation.
        # Unknown plugin/fault messages must not leak into an operational log.
        raise WorkflowRegistryError("REGISTRATION_UNAVAILABLE") from None


def register_draft_workflow(env, *, workflow, document, provenance):
    """Register or replay only an explicitly authenticated administrative caller."""
    registrar = _registrar(env)
    return _runtime_call(_register_draft_workflow, env, workflow=workflow,
        document=document, provenance=provenance, registrar=registrar)


def resolve_draft_workflow(env, *, registration_id, expected_company_id,
                           expected_executor_user_id, expected_scenario_id, document, provenance):
    """Resolve trusted expected bindings; this does not authorize a financial effect."""
    _registrar(env)
    return _runtime_call(_resolve_draft_workflow, env, registration_id=registration_id,
        expected_company_id=expected_company_id, expected_executor_user_id=expected_executor_user_id,
        expected_scenario_id=expected_scenario_id, document=document, provenance=provenance)
