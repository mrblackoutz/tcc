# SPDX-License-Identifier: LGPL-3.0-or-later
"""Private atomic approved POST, not an enabled public financial capability.

The caller controls the outer transaction. Only the registered C1 draft may
be posted. Public execute, audit/attachments and runner integration stay closed.
"""

from dataclasses import fields
from datetime import datetime, timezone
from decimal import Context, Decimal, DecimalException, ROUND_HALF_UP, localcontext
import hashlib

from psycopg2 import OperationalError

from odoo import SUPERUSER_ID, Command, api
from odoo.exceptions import ValidationError
from odoo.tools.misc import Callbacks

from .approval import (
    ApprovalAuthority, ApprovalKey, ApprovalVerificationError, verify_approval,
)
from .approval_kernel import approval_transaction
from .contracts import ExecutorContractError, _snapshot, canonical_action_bytes, validate_command
from .draft_contracts import bill_idempotency_key, canonical_command_sha256
from .draft_kernel import (
    _Denied, _bound_records, _business, _context, _guard, _line_facts, _lock,
    _postconditions, _reject_service_defaults, _require,
)
from .identity import _admin_environment, assert_executor_identity
from .post_contracts import TrustedPostWorkflow


def _utc_now():
    """Server clock; no client field, callback registration or runtime flag."""
    return datetime.now(timezone.utc)


def _after_post(move):
    """Private fault-injection seam, after the real native action_post."""
    return None


def _after_post_receipt(receipt):
    """Private fault-injection seam; not a public plugin or runtime option."""
    return None


def _hash_action(action):
    try:
        return "sha256:" + hashlib.sha256(canonical_action_bytes(action)).hexdigest()
    except ExecutorContractError:
        # The command was already structurally checked. An invalid action
        # reconstructed from ERP facts is state drift, not a malformed client.
        raise _Denied("PERSISTED_STATE_MISMATCH") from None


def _identity(admin, workflow):
    company = admin["res.company"].browse(workflow.company_id).exists()
    user = admin["res.users"].browse(workflow.executor_user_id).exists()
    _require(company and company.active and user and user.company_id == company,
             "EXECUTOR_IDENTITY_INVALID")
    try:
        assert_executor_identity(admin, user, company=company)
    except ValidationError:
        raise _Denied("EXECUTOR_IDENTITY_INVALID") from None
    neutral = api.Environment(admin.cr, user.id, _context(company.id), su=False)
    _require(not any(neutral[model].browse().has_access(operation)
        for model in ("ap.security.draft.receipt", "ap.security.vendor.guard",
                      "ap.security.po.guard", "ap.security.approval.nonce")
        for operation in ("read", "write", "create", "unlink")), "EXECUTOR_IDENTITY_INVALID")


def _receipt_binding(receipt, workflow, key, move, po, vendor, lines):
    _require(len(receipt) == 1 and receipt.company_id.id == workflow.company_id
        and receipt.document_sha256 == workflow.document_sha256
        and receipt.idempotency_key == key and receipt.po_id == po and receipt.vendor_id == vendor
        and set(receipt.purchase_line_ids.ids) == set(lines.ids)
        and receipt.move_id == move and receipt.executor_user_id.id == workflow.executor_user_id,
        "IDEMPOTENCY_CONFLICT")


def _restricted_post_state(move, journal, *, posted):
    # Native POST can otherwise reconcile other moves, create analytic entries,
    # activate user groups or hash prior entries. Do not repair/adopt that state.
    _require(move.currency_id.active and not journal.restrict_mode_hash_table and not move.reversed_entry_id
        and not move.reversal_move_ids and not move.origin_payment_id
        and not move.statement_line_id and not move.matched_payment_ids
        and not move.invoice_cash_rounding_id and not move.auto_post_origin_id
        and not move.tax_cash_basis_rec_id and not move.tax_cash_basis_origin_move_id
        and not move.tax_cash_basis_created_move_ids,
        "UNSUPPORTED_POST_STATE")
    _require(not any(line.analytic_distribution or line.analytic_line_ids
        or line.matching_number or line.full_reconcile_id or line.tax_line_id
        or line.tax_ids or line.tax_tag_ids or line.tax_repartition_line_id
        or line.is_imported or line.matched_debit_ids or line.matched_credit_ids
        or line.deductible_amount != 100 for line in move.line_ids), "UNSUPPORTED_POST_STATE")
    if posted:
        _require(move.posted_before and move.name and move.name != "/"
            and Decimal(str(move.amount_residual)) == Decimal(str(move.amount_total)),
            "PERSISTED_STATE_MISMATCH")
    else:
        _require(not move.posted_before and move.name in (False, "/"), "UNSUPPORTED_POST_STATE")


def _resolved_action(move, workflow, po, vendor, facts):
    return {
        "canonicalization_version": "canon/v1", "action_schema_version": "vendor-bill-action-proposal/v2",
        "policy_version": workflow.policy_version, "action": "POST_VENDOR_BILL",
        "executor_mode": "POST_APPROVED", "scenario_id": workflow.scenario_id,
        "document_sha256": workflow.document_sha256, "vendor_ref": vendor.ref,
        "purchase_order_ref": po.name, "document_ref": move.ref,
        "invoice_date": move.invoice_date.isoformat() if move.invoice_date else "",
        "currency": po.currency_id.name, "amount": format(Decimal(str(move.amount_total)), ".2f"),
        "recipient_bank_ref": move.partner_bank_id.acc_number,
        "lines": [{name: item[name] for name in ("item_code", "quantity", "unit_price")} for item in facts],
        "target_move_id": move.id,
    }


def _side_effects(env):
    return tuple(env[model].search_count([]) for model in (
        "account.move", "account.move.line", "account.payment", "account.partial.reconcile",
        "account.full.reconcile", "account.analytic.line", "mail.mail", "mail.notification", "ir.attachment",
    ))


def _validate_pending_rank(pending, vendor):
    """Only the known native metadata hook, never mail/payment callbacks."""
    expected = {partner_id: 1 for partner_id in (vendor | vendor.commercial_partner_id).ids}
    _require(len(pending) == 1 and set(pending.data) == {"account.res.partner.increase_rank.supplier_rank"}
        and dict(pending.data["account.res.partner.increase_rank.supplier_rank"]) == expected,
        "UNEXPECTED_POST_EFFECT")


def _run_committed_rank(registry, pending, payload, company_id, command_hash):
    """Guard native deferred metadata even against a caller's later savepoint rollback.

    No key/token is captured; receipt identity cannot be silently replaced by a
    subsequent POST. This production commit lifecycle still needs C1-11 proof.
    """
    try:
        with registry.cursor() as cursor:
            env = api.Environment(cursor, SUPERUSER_ID, _context(company_id), su=True)
            receipt = env["ap.security.draft.receipt"].browse(payload["receipt_id"]).exists()
            nonce = env["ap.security.approval.nonce"].browse(payload["approval_ledger_id"]).exists()
            valid = bool(receipt and receipt.executor_mode == "POST_APPROVED"
                and receipt.company_id.id == company_id and receipt.command_sha256 == command_hash
                and receipt.receipt_payload == payload and receipt.move_id.id == payload["move_id"]
                and receipt.move_id.state == "posted" and nonce and nonce.state == "consumed"
                and nonce.company_id.id == company_id and nonce.command_sha256 == command_hash)
        if valid:
            pending.run()
    except OperationalError:
        # Native rank is best-effort metadata. An unavailable post-commit
        # guard must not abort unrelated callbacks after financial commit.
        return None
    finally:
        pending.clear()


def _result(status, payload):
    return {"schema_version": "post-kernel-result/v1", "status": status,
            "effect_applied": status == "POSTED", "reason_codes": ["APPROVED_POST_CONSISTENT"],
            "receipt": payload}


def _transaction(admin, env, command, registered, authority, key, checked):
    workflow = registered.draft
    _reject_service_defaults(env)
    _bound_records(env, workflow)
    _guard(env, workflow)
    company, po, vendor, journal, account, lines = _bound_records(env, workflow)
    move = env["account.move"].browse(registered.target_move_id).exists()
    _require(len(move) == 1 and move.company_id == company, "TARGET_MISMATCH")
    for records in (company.with_context(active_test=False).parent_ids, po, lines, vendor, journal, account,
                    vendor.commercial_partner_id, vendor.with_company(company).property_account_payable_id,
                    lines.product_id.product_tmpl_id, lines.product_id, lines.product_uom_id, po.currency_id,
                    env["res.partner.bank"].browse(workflow.allowed_bank_ids), move, move.line_ids,
                    env["res.users"].browse(workflow.executor_user_id)):
        _lock(records)
    # This is not a proof of concurrent administrative ACL/group modifications.
    # Final identity revalidation plus actual cross-cursor tests remain C1-11.
    admin.invalidate_all()
    _identity(admin, workflow)
    company, po, vendor, journal, account, lines = _bound_records(env, workflow)
    move.invalidate_recordset()
    key_hash = bill_idempotency_key(document_sha256=workflow.document_sha256,
        company_id=company.id, vendor_id=vendor.id, purchase_order_id=po.id,
        purchase_line_ids=tuple(sorted(lines.ids)))
    _require(command["idempotency_key"] == key_hash, "IDEMPOTENCY_KEY_MISMATCH")
    _require(command["action"]["target_move_id"] == move.id, "TARGET_MISMATCH")
    receipts = env["ap.security.draft.receipt"]
    origin = receipts.search([
        ("company_id", "=", company.id), ("executor_mode", "=", "CREATE_DRAFT"),
        ("document_sha256", "=", workflow.document_sha256),
    ])
    _lock(origin)
    _receipt_binding(origin, workflow, key_hash, move, po, vendor, lines)
    facts = _line_facts(lines, workflow.quantity_scale, check_invoiceability=False)
    action = _resolved_action(move, workflow, po, vendor, facts)
    action_hash = _hash_action(action)
    draft_action = dict(action, action="CREATE_DRAFT_BILL", executor_mode="CREATE_DRAFT")
    draft_action.pop("target_move_id")
    # DEC-061: integrity of the stored draft first (technical), then the
    # command against that intact draft (an altered POST action, R-POL-02).
    _require(origin.action_sha256 == _hash_action(draft_action) and origin.receipt_payload == {
        "move_id": move.id, "idempotency_key": key_hash, "action_hash": origin.action_sha256,
        "receipt_id": origin.id,
    }, "PERSISTED_STATE_MISMATCH")
    _require(action == command["action"] and action_hash == checked.action_hash, "TARGET_BILL_MISMATCH")
    body_hash = canonical_command_sha256(command)
    previous = receipts.search([
        ("company_id", "=", company.id), ("executor_mode", "=", "POST_APPROVED"),
        ("document_sha256", "=", workflow.document_sha256),
    ])
    _require(len(previous) <= 1, "IDEMPOTENCY_CONFLICT")
    if previous:
        _lock(previous)
        _receipt_binding(previous, workflow, key_hash, move, po, vendor, lines)
        _require(previous.command_sha256 == body_hash and previous.action_sha256 == action_hash,
                 "IDEMPOTENCY_CONFLICT")
        payload = previous.receipt_payload
        _require(type(payload) is dict and type(payload.get("approval_ledger_id")) is int
                 and payload["approval_ledger_id"] > 0, "PERSISTED_STATE_MISMATCH")
        nonce = env["ap.security.approval.nonce"].browse(payload["approval_ledger_id"]).exists()
        _lock(nonce)
        _require(len(nonce) == 1 and nonce.state == "consumed" and nonce.consumed_at,
                 "PERSISTED_STATE_MISMATCH")
        # Authenticate original registration at its stored verification instant,
        # not current time: replay is not a second financial authorization.
        verified = verify_approval(command, trusted_action=action, authority=authority, key=key,
                                   now=nonce.verified_at.replace(tzinfo=timezone.utc))
        _require(nonce.company_id == company and nonce.executor_user_id.id == workflow.executor_user_id
            and nonce.key_id == verified.key_id and nonce.fixture_id == verified.fixture_id
            and nonce.scenario_id == verified.scenario_id and nonce.approver_ref == verified.approver_ref
            and nonce.nonce_sha256 == verified.nonce_sha256 and nonce.action_sha256 == action_hash
            and nonce.approval_sha256 == verified.approval_sha256 and nonce.command_sha256 == body_hash
            and nonce.expires_at == datetime.fromisoformat(verified.expires_at.replace("Z", "+00:00")).replace(tzinfo=None),
            "PERSISTED_STATE_MISMATCH")
        bank = move.partner_bank_id
        _require(bank.id in workflow.allowed_bank_ids and bank.active and bank.allow_out_payment
                 and bank.partner_id == vendor, "PERSISTED_STATE_MISMATCH")
        _postconditions(move, action, company, po, vendor, journal, account, facts, bank, expected_state="posted")
        _restricted_post_state(move, journal, posted=True)
        _require(payload == {"move_id": move.id, "idempotency_key": key_hash,
            "action_hash": action_hash, "receipt_id": previous.id, "approval_ledger_id": nonce.id},
            "PERSISTED_STATE_MISMATCH")
        return _result("REPLAY", payload)
    _require(move.state == "draft", "TARGET_NOT_DRAFT")
    facts, bank = _business(env, workflow, action, company, po, vendor, journal, lines,
                           check_invoiceability=False, duplicate_exclude_id=move.id)
    _postconditions(move, action, company, po, vendor, journal, account, facts, bank)
    _restricted_post_state(move, journal, posted=False)
    before = _side_effects(env)
    with approval_transaction(admin, command=command, trusted_action=action, authority=authority,
                              key=key, now=_utc_now()) as reservation:
        # The INSERT may wait. A stale pre-reservation instant is not authority.
        verify_approval(command, trusted_action=action, authority=authority, key=key, now=_utc_now())
        move.action_post()
        _after_post(move)
        env.flush_all()
        _postconditions(move, action, company, po, vendor, journal, account, facts, bank, expected_state="posted")
        _restricted_post_state(move, journal, posted=True)
        _require(_side_effects(env) == before, "UNEXPECTED_POST_EFFECT")
        _validate_pending_rank(env.cr.postcommit, vendor)
        payload = {"move_id": move.id, "idempotency_key": key_hash,
                   "action_hash": action_hash, "approval_ledger_id": reservation.ledger_id}
        receipt = receipts.create({
            "company_id": company.id, "executor_mode": "POST_APPROVED", "idempotency_key": key_hash,
            "command_sha256": body_hash, "action_sha256": action_hash,
            "document_sha256": workflow.document_sha256, "po_id": po.id, "vendor_id": vendor.id,
            "purchase_line_ids": [Command.set(lines.ids)], "move_id": move.id,
            "executor_user_id": workflow.executor_user_id, "receipt_payload": payload,
        })
        payload = dict(payload, receipt_id=receipt.id)
        receipt.receipt_payload = payload
        env.flush_all()
        _after_post_receipt(receipt)
    env.flush_all()
    _postconditions(move, action, company, po, vendor, journal, account, facts, bank, expected_state="posted")
    _restricted_post_state(move, journal, posted=True)
    _validate_pending_rank(env.cr.postcommit, vendor)
    _require(_side_effects(env) == before, "UNEXPECTED_POST_EFFECT")
    return _result("POSTED", payload)


def post_bill_atomic(env, *, command, workflow, authority, key):
    """Administrative entry only. No commit, RPC entry or caller-supplied clock."""
    admin = _admin_environment(env)
    try:
        _require(type(workflow) is TrustedPostWorkflow, "WORKFLOW_MISMATCH")
        try:
            registered = TrustedPostWorkflow(**{item.name: getattr(workflow, item.name)
                                                 for item in fields(TrustedPostWorkflow)})
        except (AttributeError, TypeError, ValueError, OverflowError):
            raise _Denied("WORKFLOW_MISMATCH") from None
        config = registered.draft
        _require(type(authority) is ApprovalAuthority and type(key) is ApprovalKey,
                 "WORKFLOW_MISMATCH")
        try:
            authority = ApprovalAuthority(**{item.name: getattr(authority, item.name) for item in fields(ApprovalAuthority)})
            key = ApprovalKey(**{item.name: getattr(key, item.name) for item in fields(ApprovalKey)})
        except ApprovalVerificationError:
            raise
        except (AttributeError, TypeError, ValueError, OverflowError):
            raise ApprovalVerificationError("DEPENDENCY_UNAVAILABLE") from None
        _require(authority.company_id == config.company_id and authority.executor_user_id == config.executor_user_id
            and authority.scenario_id == config.scenario_id and key.company_id == config.company_id
            and key.key_id == authority.key_id, "WORKFLOW_MISMATCH")
        command = _snapshot(command)
        checked = validate_command(command)
        _require(checked.executor_mode == "POST_APPROVED", "UNSUPPORTED_EXECUTOR_MODE")
        _require(checked.scenario_id == config.scenario_id and checked.document_sha256 == config.document_sha256
                 and checked.policy_version == config.policy_version, "WORKFLOW_MISMATCH")
        _identity(admin, config)
        private = api.Environment(admin.cr, SUPERUSER_ID, _context(config.company_id), su=True)
        # Odoo clears precommit, not postcommit, on savepoint rollback. Never
        # mutate the original queue or its shared data while the kernel runs.
        original_pending = admin.cr.postcommit
        pending = Callbacks()
        admin.cr.postcommit = pending
        try:
            with localcontext(Context(prec=32, rounding=ROUND_HALF_UP)):
                with admin.cr.savepoint():
                    result = _transaction(admin, private, command, registered, authority, key, checked)
            if result["status"] == "POSTED":
                payload = dict(result["receipt"])
                body_hash = canonical_command_sha256(command)
                original_pending.add(lambda: _run_committed_rank(
                    admin.registry, pending, payload, config.company_id, body_hash))
            else:
                pending.clear()
            return result
        except BaseException:
            pending.clear()
            raise
        finally:
            admin.cr.postcommit = original_pending
    except _Denied as error:
        codes = error.codes
    except ApprovalVerificationError as error:
        codes = [error.code]
    except ExecutorContractError:
        raise ValidationError("Invalid private POST contract.") from None
    except DecimalException:
        codes = ["STATE_INVALID"]
    return {"schema_version": "post-kernel-result/v1", "status": "DENIED",
            "effect_applied": False, "reason_codes": codes}
