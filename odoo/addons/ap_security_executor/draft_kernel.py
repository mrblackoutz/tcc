# SPDX-License-Identifier: LGPL-3.0-or-later
"""Private administrative C1-06 kernel, never a public/RPC capability.

The public executor remains closed. Trusted workflow registration, approval,
attachments and complete audit/runner integration are separate gates.
"""

from dataclasses import fields as dataclass_fields
from datetime import date
from decimal import Context, Decimal, DecimalException, ROUND_HALF_EVEN, localcontext

from odoo import SUPERUSER_ID, Command, api
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL

from .contracts import ExecutorContractError, _snapshot, validate_command
from .draft_contracts import TrustedDraftWorkflow, bill_idempotency_key, canonical_command_sha256
from .identity import _admin_environment, assert_executor_identity


class _Denied(Exception):
    def __init__(self, *codes):
        self.codes = list(codes)


def _require(condition, code="STATE_INVALID"):
    if not condition:
        raise _Denied(code)


def _decimal(value, scale):
    number = Decimal(str(value))
    _require(number.is_finite() and number >= 0)
    scaled = number.quantize(Decimal(1).scaleb(-scale))
    _require(scaled == number)
    return format(abs(scaled) if scaled == 0 else scaled, f".{scale}f")


def _context(company_id):
    return {
        "allowed_company_ids": [company_id],
        "lang": "en_US", "tz": "UTC", "active_test": True,
        "tracking_disable": True, "mail_create_nolog": True,
        "mail_create_nosubscribe": True, "mail_auto_subscribe_no_notify": True,
        "mail_post_autofollow_author_skip": True, "mail_notify_force_send": False,
    }


def _after_draft_create(move):
    """Private fault-injection seam; production has no flag or plugin hook."""
    return None


def _lock(records):
    records.flush_recordset()
    if records:
        records.env.cr.execute(SQL(
            "SELECT id FROM %s WHERE id = ANY(%s) ORDER BY id FOR UPDATE",
            SQL.identifier(records._table), records.ids,
        ))
        _require(len(records.env.cr.fetchall()) == len(records))
    records.invalidate_recordset()


def _guard(env, workflow):
    # Updating a dedicated row, not merely locking, forces conflicting
    # REPEATABLE READ snapshots to restart rather than reuse old quantities.
    env["ap.security.po.guard"].flush_model()
    env.cr.execute("""
        INSERT INTO ap_security_po_guard
            (company_id, po_id, revision, create_uid, write_uid, create_date, write_date)
        VALUES (%s, %s, 1, %s, %s, timezone('UTC', now()), timezone('UTC', now()))
        ON CONFLICT (company_id, po_id) DO UPDATE
            SET revision = ap_security_po_guard.revision + 1,
                write_uid = EXCLUDED.write_uid, write_date = EXCLUDED.write_date
        RETURNING id
    """, (workflow.company_id, workflow.purchase_order_id, env.uid, env.uid))
    guard_id = env.cr.fetchone()[0]
    env["ap.security.po.guard"].invalidate_model()
    return guard_id


def _reject_service_defaults(env):
    # Personal C1 defaults are excluded by the internal UID. No global/service
    # financial defaults may be consumed implicitly, including conditional ones.
    _require(not env["ir.default"].search_count([
        ("field_id.model", "in", ["account.move", "account.move.line",
                                  "ap.security.draft.receipt", "ap.security.po.guard"]),
        ("user_id", "in", [False, SUPERUSER_ID]),
        ("company_id", "in", [False, env.company.id]),
    ], limit=1), "UNTRUSTED_FINANCIAL_DEFAULTS")


def _bound_records(env, workflow):
    company = env["res.company"].browse(workflow.company_id).exists()
    po = env["purchase.order"].browse(workflow.purchase_order_id).exists()
    vendor = env["res.partner"].browse(workflow.vendor_id).exists()
    journal = env["account.journal"].browse(workflow.journal_id).exists()
    account = env["account.account"].browse(workflow.expense_account_id).exists()
    _require(len(company) == len(po) == len(vendor) == len(journal) == len(account) == 1,
             "WORKFLOW_MISMATCH")
    _require(company.active and vendor.active and po.company_id == company
             and po.partner_id == vendor and vendor.company_id == company
             and vendor.supplier_rank >= 1,
             "WORKFLOW_MISMATCH")
    _require(vendor.autopost_bills == "never")
    _require(journal.active and journal.company_id == company and journal.type == "purchase")
    _require(company in account.company_ids and account.active
             and account.account_type == "expense")
    payable = vendor.with_company(company).property_account_payable_id
    _require(payable and payable.active and company in payable.company_ids
             and payable.account_type == "liability_payable")
    lines = po.order_line.filtered(lambda line: not line.display_type)
    _require(tuple(sorted(lines.ids)) == workflow.purchase_line_ids, "WORKFLOW_MISMATCH")
    return company, po, vendor, journal, account, lines


def _line_facts(lines, scale, *, check_invoiceability=True):
    facts = []
    for line in lines:
        product = line.product_id
        _require(product.active and product.type == "service" and product.purchase_ok
                 and product.company_id in (lines.env.company, lines.env["res.company"])
                 and product.purchase_method == "purchase"
                 and line.product_uom_id == product.uom_id and not line.is_downpayment
                 and not line.tax_ids and not line.discount)
        _require(bool(product.default_code))
        facts.append({
            "item_code": product.default_code,
            "quantity": _decimal(line.product_qty, scale),
            "unit_price": _decimal(line.price_unit, 2),
            "line": line,
        })
        if check_invoiceability:
            facts[-1]["quantity_to_invoice"] = _decimal(line.qty_to_invoice, scale)
    facts.sort(key=lambda item: item["item_code"])
    _require(len({item["item_code"] for item in facts}) == len(facts))
    return facts


def _business(env, workflow, action, company, po, vendor, journal, lines,
              *, check_invoiceability=True, duplicate_exclude_id=None):
    facts = _line_facts(lines, workflow.quantity_scale, check_invoiceability=check_invoiceability)
    banks = env["res.partner.bank"].with_context(active_test=False).browse(workflow.allowed_bank_ids).exists()
    permitted = banks.filtered(lambda bank: bank.active and bank.allow_out_payment
        and bank.partner_id == vendor and bank.company_id == company)
    matches = permitted.filtered(lambda bank: bank.acc_number == action["recipient_bank_ref"])
    expected = [{name: row[name] for name in ("item_code", "quantity", "unit_price")} for row in facts]
    line_mismatch = action["lines"] != expected or (check_invoiceability and any(
        Decimal(proposed["quantity"]) > Decimal(trusted["quantity_to_invoice"])
        for proposed, trusted in zip(action["lines"], facts)
    ))
    expected_total = sum((Decimal(row["quantity"]) * Decimal(row["unit_price"])).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_EVEN) for row in facts)
    _require(Decimal(str(po.amount_total)) == expected_total)
    duplicate = env["account.move"].search_count([
        ("company_id", "=", company.id), ("partner_id", "=", vendor.id),
        ("move_type", "=", "in_invoice"), ("ref", "=", action["document_ref"]),
        ("state", "!=", "cancel"),
        *([("id", "!=", duplicate_exclude_id)] if duplicate_exclude_id is not None else []),
    ], limit=1)
    checks = (
        ("PURCHASE_ORDER_NOT_CONFIRMED", po.state != "purchase"),
        ("VENDOR_MISMATCH", action["vendor_ref"] != vendor.ref),
        ("PURCHASE_ORDER_MISMATCH", action["purchase_order_ref"] != po.name),
        ("CURRENCY_MISMATCH", action["currency"] != po.currency_id.name),
        ("LINE_MISMATCH", line_mismatch),
        ("AMOUNT_MISMATCH", abs(Decimal(action["amount"]) - expected_total) > Decimal(workflow.monetary_tolerance)),
        ("BANK_NOT_ALLOWED", len(matches) != 1),
        ("DUPLICATE_DOCUMENT", bool(duplicate)),
        ("DATE_OUTSIDE_WINDOW", not workflow.invoice_date_min <= action["invoice_date"] <= workflow.invoice_date_max),
        # Internal UID1 may have a lock exception the restricted user does not.
        # sudo grants read access, but deliberately preserves the C1 UID used
        # by Odoo's lock-exception calculation; it is not accounting authority.
        ("ACCOUNTING_PERIOD_CLOSED", bool(company.with_user(workflow.executor_user_id).sudo()._get_violated_lock_dates(
            date.fromisoformat(action["invoice_date"]), False, journal))),
    )
    failures = [code for code, failed in checks if failed]
    if failures:
        raise _Denied(*failures)
    _require(po.currency_id == company.currency_id and po.currency_id.decimal_places == 2
             and Decimal(str(po.currency_id.rounding)) == Decimal("0.01"))
    return facts, matches


def _values(action, company, po, vendor, journal, account, facts, bank):
    # Business order is explicit: vendor precedes beneficiary; never write
    # partner_id again. Product descriptions are obtained only from the PO.
    return {
        "company_id": company.id, "partner_id": vendor.id,
        "currency_id": po.currency_id.id, "invoice_date": action["invoice_date"],
        "ref": action["document_ref"], "invoice_origin": po.name,
        "partner_bank_id": bank.id, "move_type": "in_invoice",
        "journal_id": journal.id, "state": "draft", "auto_post": "no",
        "date": action["invoice_date"], "invoice_payment_term_id": False,
        "fiscal_position_id": False,
        "invoice_line_ids": [Command.create({
            "name": item["line"].name, "product_id": item["line"].product_id.id,
            "product_uom_id": item["line"].product_uom_id.id,
            "account_id": account.id, "quantity": float(item["quantity"]),
            "price_unit": float(item["unit_price"]), "discount": 0.0,
            "tax_ids": [Command.clear()], "purchase_line_id": item["line"].id,
        }) for item in facts],
    }


def _postconditions(move, action, company, po, vendor, journal, account, facts, bank,
                    *, expected_state="draft"):
    _require(move.exists() and move.company_id == company and move.partner_id == vendor
        and move.partner_bank_id == bank and move.journal_id == journal
        and bank.company_id == company and bank.acc_number == action["recipient_bank_ref"]
        and move.currency_id == po.currency_id and move.move_type == "in_invoice"
        and move.state == expected_state and move.auto_post == "no"
        and move.ref == action["document_ref"] and move.invoice_origin == po.name
        and move.invoice_date == date.fromisoformat(action["invoice_date"])
        and move.date == date.fromisoformat(action["invoice_date"])
        and not move.invoice_payment_term_id and not move.fiscal_position_id,
        "PERSISTED_STATE_MISMATCH")
    _require(Decimal(str(move.amount_total)) == Decimal(action["amount"])
             and len(move.invoice_line_ids) == len(facts), "PERSISTED_STATE_MISMATCH")
    by_id = {line.purchase_line_id.id: line for line in move.invoice_line_ids}
    _require(set(by_id) == {item["line"].id for item in facts}, "PERSISTED_STATE_MISMATCH")
    for item in facts:
        line = by_id[item["line"].id]
        _require(line.product_id == item["line"].product_id
            and line.product_uom_id == item["line"].product_uom_id
            and line.account_id == account and not line.tax_ids and not line.discount
            and line.name == item["line"].name
            and Decimal(str(line.quantity)) == Decimal(item["quantity"])
            and Decimal(str(line.price_unit)) == Decimal(item["unit_price"]),
            "PERSISTED_STATE_MISMATCH")
    payable = move.line_ids - move.invoice_line_ids
    total = Decimal(action["amount"])
    _require(len(payable) == 1 and payable.display_type == "payment_term"
        and payable.account_id.account_type == "liability_payable"
        and payable.account_id.active and company in payable.account_id.company_ids
        and payable.account_id == vendor.with_company(company).property_account_payable_id
        and payable.partner_id == vendor.commercial_partner_id
        and Decimal(str(payable.balance)) == -total
        and Decimal(str(payable.amount_currency)) == -total
        and sum(Decimal(str(line.balance)) for line in move.line_ids) == 0
        and not any(line.reconciled or line.matched_debit_ids or line.matched_credit_ids
                    for line in move.line_ids), "PERSISTED_STATE_MISMATCH")
    for item in facts:
        line = by_id[item["line"].id]
        amount = (Decimal(item["quantity"]) * Decimal(item["unit_price"])).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        _require(line.display_type == "product" and line.partner_id == vendor.commercial_partner_id
            and Decimal(str(line.balance)) == amount
            and Decimal(str(line.amount_currency)) == amount,
            "PERSISTED_STATE_MISMATCH")


def _transaction(env, command, workflow, checked):
    _reject_service_defaults(env)
    _bound_records(env, workflow)
    _guard(env, workflow)
    company, po, vendor, journal, account, lines = _bound_records(env, workflow)
    # Deterministic order. Lock all business inputs, not just the PO.
    for records in (company.with_context(active_test=False).parent_ids, po, lines, vendor, journal, account,
                    vendor.commercial_partner_id,
                    vendor.with_company(company).property_account_payable_id,
                    lines.product_id.product_tmpl_id, lines.product_id,
                    lines.product_uom_id, po.currency_id,
                    env["res.partner.bank"].browse(workflow.allowed_bank_ids)):
        _lock(records)
    company, po, vendor, journal, account, lines = _bound_records(env, workflow)
    key = bill_idempotency_key(document_sha256=workflow.document_sha256,
        company_id=company.id, vendor_id=vendor.id, purchase_order_id=po.id,
        purchase_line_ids=tuple(sorted(lines.ids)))
    _require(command["idempotency_key"] == key, "IDEMPOTENCY_KEY_MISMATCH")
    body_hash = canonical_command_sha256(command)
    receipts = env["ap.security.draft.receipt"]
    # A changed vendor/line identity must not mint another receipt for this
    # registered document; scope to the same company and operation.
    previous = receipts.search([
        ("company_id", "=", company.id), ("executor_mode", "=", "CREATE_DRAFT"),
        ("document_sha256", "=", workflow.document_sha256),
    ])
    _require(len(previous) <= 1, "IDEMPOTENCY_CONFLICT")
    if previous:
        _lock(previous)
        _require(previous.idempotency_key == key and previous.po_id == po
            and previous.vendor_id == vendor and set(previous.purchase_line_ids.ids) == set(lines.ids)
            and previous.executor_user_id.id == workflow.executor_user_id
            and previous.command_sha256 == body_hash and previous.action_sha256 == checked.action_hash,
            "IDEMPOTENCY_CONFLICT")
        move = previous.move_id
        _lock(move)
        facts = _line_facts(lines, workflow.quantity_scale, check_invoiceability=False)
        bank = env["res.partner.bank"].browse(move.partner_bank_id.id)
        _require(bank.id in workflow.allowed_bank_ids and bank.active and bank.allow_out_payment
                 and bank.partner_id == vendor, "PERSISTED_STATE_MISMATCH")
        _postconditions(move, command["action"], company, po, vendor, journal, account, facts, bank)
        _require(previous.receipt_payload == {
            "move_id": move.id, "idempotency_key": key,
            "action_hash": checked.action_hash, "receipt_id": previous.id,
        }, "PERSISTED_STATE_MISMATCH")
        return {"schema_version": "draft-kernel-result/v1", "status": "REPLAY",
                "effect_applied": False, "reason_codes": ["DRAFT_CONSISTENT"],
                "receipt": previous.receipt_payload}
    facts, bank = _business(env, workflow, command["action"], company, po, vendor, journal, lines)
    effect_models = ("mail.mail", "mail.notification", "account.payment")
    mail_before = tuple(env[name].search_count([]) for name in effect_models)
    move = env["account.move"].create(_values(command["action"], company, po, vendor, journal, account, facts, bank))
    _after_draft_create(move)
    env.flush_all()
    _postconditions(move, command["action"], company, po, vendor, journal, account, facts, bank)
    _require(mail_before == tuple(env[name].search_count([]) for name in effect_models),
             "UNEXPECTED_NOTIFICATION")
    payload = {"move_id": move.id, "idempotency_key": key, "action_hash": checked.action_hash}
    receipt = receipts.create({
        "company_id": company.id, "executor_mode": "CREATE_DRAFT", "idempotency_key": key,
        "command_sha256": body_hash, "action_sha256": checked.action_hash,
        "document_sha256": workflow.document_sha256, "po_id": po.id,
        "vendor_id": vendor.id, "purchase_line_ids": [Command.set(lines.ids)],
        "move_id": move.id, "executor_user_id": workflow.executor_user_id,
        "receipt_payload": payload,
    })
    # Store a deterministic original receipt, returned unchanged on retry.
    payload = dict(payload, receipt_id=receipt.id)
    # Receipt ACL prohibits ordinary updates. This localized private write
    # completes its payload in the same transaction, not a public edit API.
    receipt.receipt_payload = payload
    env.flush_all()
    return {"schema_version": "draft-kernel-result/v1", "status": "CREATED",
            "effect_applied": True, "reason_codes": ["DRAFT_CONSISTENT"], "receipt": payload}


def create_draft_atomic(env, *, command, workflow):
    """Administrative test/integration entry; no commit and no RPC exposure."""
    admin = _admin_environment(env)
    try:
        _require(type(workflow) is TrustedDraftWorkflow, "WORKFLOW_MISMATCH")
        workflow = TrustedDraftWorkflow(**{field.name: getattr(workflow, field.name)
                                           for field in dataclass_fields(TrustedDraftWorkflow)})
        command = _snapshot(command)
        checked = validate_command(command)
        _require(checked.executor_mode == "CREATE_DRAFT", "UNSUPPORTED_EXECUTOR_MODE")
        _require(checked.scenario_id == workflow.scenario_id
            and checked.document_sha256 == workflow.document_sha256
            and checked.policy_version == workflow.policy_version, "WORKFLOW_MISMATCH")
        company = admin["res.company"].browse(workflow.company_id)
        user = admin["res.users"].browse(workflow.executor_user_id)
        _require(company.exists() and user.exists() and user.company_id == company, "WORKFLOW_MISMATCH")
        try:
            assert_executor_identity(admin, user, company=company)
        except ValidationError:
            raise _Denied("EXECUTOR_IDENTITY_INVALID") from None
        neutral = api.Environment(admin.cr, user.id, _context(company.id), su=False)
        _require(not any(neutral[model].browse().has_access(operation)
            for model in ("ap.security.draft.receipt", "ap.security.po.guard")
            for operation in ("read", "write", "create", "unlink")), "EXECUTOR_IDENTITY_INVALID")
        private = api.Environment(admin.cr, SUPERUSER_ID, _context(company.id), su=True)
        with localcontext(Context(prec=32, rounding=ROUND_HALF_EVEN)):
            # Both explicit denials and unexpected errors escape this savepoint
            # before being caught. PG concurrency errors intentionally propagate.
            with admin.cr.savepoint():
                return _transaction(private, command, workflow, checked)
    except _Denied as error:
        return {"schema_version": "draft-kernel-result/v1", "status": "DENIED",
                "effect_applied": False, "reason_codes": error.codes}
    except ExecutorContractError:
        raise ValidationError("Invalid private draft contract.") from None
    except DecimalException:
        return {"schema_version": "draft-kernel-result/v1", "status": "DENIED",
                "effect_applied": False, "reason_codes": ["STATE_INVALID"]}
