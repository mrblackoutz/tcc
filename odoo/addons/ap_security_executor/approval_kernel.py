# SPDX-License-Identifier: LGPL-3.0-or-later
"""Private approval transaction, not a public financial capability.

Crypto verification alone never consumes a nonce. The administrative caller
must place its future operation inside this savepoint; only successful exit
consumes the reservation. This helper neither posts a bill nor commits.
"""

from contextlib import contextmanager
from dataclasses import dataclass, fields as dataclass_fields
from datetime import datetime

from odoo import SUPERUSER_ID, api
from odoo.exceptions import ValidationError

from .approval import ApprovalAuthority, ApprovalKey, ApprovalVerificationError, verify_approval
from .contracts import ExecutorContractError, _snapshot
from .draft_kernel import _context
from .identity import _admin_environment, assert_executor_identity


@dataclass(frozen=True, slots=True)
class ApprovalReservation:
    """Safe diagnostic metadata, not external or independently usable authority."""

    ledger_id: int
    action_hash: str
    approval_sha256: str
    command_sha256: str


def _after_nonce_consume(record):
    """Private test seam; no runtime flag or callback registration exists."""
    return None


def _trusted_environment(admin, authority):
    company = admin["res.company"].browse(authority.company_id).exists()
    user = admin["res.users"].browse(authority.executor_user_id).exists()
    if not company or not company.active or not user or user.company_id != company:
        raise ApprovalVerificationError("IDENTITY_INVALID")
    try:
        assert_executor_identity(admin, user, company=company)
    except ValidationError:
        raise ApprovalVerificationError("IDENTITY_INVALID") from None
    neutral = api.Environment(admin.cr, user.id, _context(company.id), su=False)
    if any(neutral["ap.security.approval.nonce"].browse().has_access(operation)
           for operation in ("read", "write", "create", "unlink")):
        raise ApprovalVerificationError("IDENTITY_INVALID")
    private = api.Environment(admin.cr, SUPERUSER_ID, _context(company.id), su=True)
    if private["ir.default"].search_count([
        ("field_id.model", "=", "ap.security.approval.nonce"),
        ("user_id", "in", [False, SUPERUSER_ID]),
        ("company_id", "in", [False, company.id]),
    ], limit=1):
        raise ApprovalVerificationError("DEPENDENCY_UNAVAILABLE")
    return private


def _reserve_nonce(env, authority, verified, now):
    ledger = env["ap.security.approval.nonce"]
    ledger.flush_model()
    # Global uniqueness also blocks a replay under another key/scenario/company.
    # A concurrent RR serialization failure deliberately reaches the caller.
    env.cr.execute("""
        INSERT INTO ap_security_approval_nonce
            (company_id, executor_user_id, key_id, fixture_id, scenario_id, approver_ref,
             nonce_sha256, action_sha256, approval_sha256, command_sha256, state,
             verified_at, expires_at, consumed_at, create_uid, write_uid, create_date, write_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'reserved',
                %s, %s, NULL, %s, %s, timezone('UTC', now()), timezone('UTC', now()))
        ON CONFLICT (nonce_sha256) DO NOTHING RETURNING id
    """, (authority.company_id, authority.executor_user_id, verified.key_id,
          verified.fixture_id, verified.scenario_id, verified.approver_ref,
          verified.nonce_sha256, verified.action_hash, verified.approval_sha256,
          verified.command_sha256, now.replace(tzinfo=None),
          datetime.fromisoformat(verified.expires_at.replace("Z", "+00:00")).replace(tzinfo=None),
          env.uid, env.uid))
    row = env.cr.fetchone()
    if not row:
        raise ApprovalVerificationError("NONCE_REUSED")
    ledger.invalidate_model()
    return ApprovalReservation(row[0], verified.action_hash,
                               verified.approval_sha256, verified.command_sha256)


def _consume_nonce(env, reservation, authority, verified, now):
    env["ap.security.approval.nonce"].flush_model()
    # The body cannot change the reservation's binding and still consume it.
    env.cr.execute("""
        UPDATE ap_security_approval_nonce SET state='consumed', consumed_at=%s,
            write_uid=%s, write_date=timezone('UTC', now())
        WHERE id=%s AND state='reserved' AND company_id=%s AND executor_user_id=%s
            AND key_id=%s AND fixture_id=%s AND scenario_id=%s AND approver_ref=%s
            AND nonce_sha256=%s AND action_sha256=%s AND approval_sha256=%s
            AND command_sha256=%s AND verified_at=%s AND expires_at=%s
        RETURNING id
    """, (now.replace(tzinfo=None), env.uid, reservation.ledger_id,
          authority.company_id, authority.executor_user_id, verified.key_id,
          verified.fixture_id, verified.scenario_id, verified.approver_ref,
          verified.nonce_sha256, verified.action_hash, verified.approval_sha256,
          verified.command_sha256, now.replace(tzinfo=None),
          datetime.fromisoformat(verified.expires_at.replace("Z", "+00:00")).replace(tzinfo=None)))
    if env.cr.fetchone() is None:
        raise ApprovalVerificationError("RESERVATION_INVALID")
    env["ap.security.approval.nonce"].invalidate_model()
    _after_nonce_consume(env["ap.security.approval.nonce"].browse(reservation.ledger_id))


@contextmanager
def approval_transaction(env, *, command, trusted_action, authority, key, now):
    """Administrative primitive: verify, reserve, operation body, consume.

No RPC entry, financial effect, implicit clock/key provider or commit. Full
ERP/policy revalidation and idempotent POST replay are responsibilities of the
future C1-08 caller. A returned dataclass is never accepted as approval proof.
    """
    admin = _admin_environment(env)
    if type(authority) is not ApprovalAuthority or type(key) is not ApprovalKey:
        raise ApprovalVerificationError("DEPENDENCY_UNAVAILABLE")
    try:
        authority = ApprovalAuthority(**{field.name: getattr(authority, field.name)
                                        for field in dataclass_fields(ApprovalAuthority)})
        key = ApprovalKey(**{field.name: getattr(key, field.name)
                            for field in dataclass_fields(ApprovalKey)})
    except ApprovalVerificationError:
        raise
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise ApprovalVerificationError("DEPENDENCY_UNAVAILABLE") from None
    try:
        command = _snapshot(command)
        trusted_action = _snapshot(trusted_action)
    except ExecutorContractError:
        raise ApprovalVerificationError("CONTRACT_INVALID") from None
    verified = verify_approval(command, trusted_action=trusted_action,
                               authority=authority, key=key, now=now)
    private = _trusted_environment(admin, authority)
    # Exceptions are not converted inside the savepoint: all writes, including
    # the caller's future operation, are rolled back before leaving this helper.
    with admin.cr.savepoint():
        reservation = _reserve_nonce(private, authority, verified, now)
        yield reservation
        _consume_nonce(private, reservation, authority, verified, now)
