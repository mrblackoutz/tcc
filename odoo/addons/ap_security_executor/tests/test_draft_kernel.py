# SPDX-License-Identifier: LGPL-3.0-or-later
"""Administrative, real ORM proof of the private C1-06 draft kernel.

Synthetic fixtures only, without fiscal value. The public executor stays
closed. This class does not prove multi-process concurrency or a pilot.
"""

import copy
from dataclasses import replace
from datetime import date
import hashlib
import json
import unittest
from unittest.mock import patch

from psycopg2.errors import UniqueViolation

from odoo import SUPERUSER_ID, Command, api
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from .. import draft_kernel
from ..draft_contracts import TrustedDraftWorkflow, bill_idempotency_key
from ..draft_kernel import create_draft_atomic
from ..identity import provision_executor_identity
from .test_executor import _action_hash, _command


@tagged("post_install", "-at_install", "c1_draft_kernel")
class TestDraftKernel(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        if not cls.company.chart_template:
            cls.env["account.chart.template"].try_loading(
                "generic_coa", company=cls.company, install_demo=False,
            )
        cls.other_company = cls.env["res.company"].create({
            "name": "TCC C1-06 OTHER COMPANY - SEM VALOR FISCAL",
        })
        cls.executor_user = provision_executor_identity(
            cls.env, login="tcc-c106-draft-kernel", company=cls.company,
        )
        cls.vendor = cls.env["res.partner"].create({
            "name": "TCC C1-06 SUPPLIER - SEM VALOR FISCAL",
            "ref": "TCC-C106-VENDOR", "is_company": True,
            "company_id": cls.company.id, "supplier_rank": 1, "autopost_bills": "never",
        })
        cls.other_vendor = cls.env["res.partner"].create({
            "name": "TCC C1-06 OTHER SUPPLIER - SEM VALOR FISCAL",
            "ref": "TCC-C106-OTHER-VENDOR", "is_company": True,
            "company_id": cls.company.id, "supplier_rank": 1,
        })
        cls.bank = cls.env["res.partner.bank"].create({
            "acc_number": "TCC-C106-SYNTHETIC-BANK",
            "partner_id": cls.vendor.id, "company_id": cls.company.id,
            "allow_out_payment": True,
        })
        cls.other_bank = cls.env["res.partner.bank"].create({
            "acc_number": "TCC-C106-OTHER-SYNTHETIC-BANK",
            "partner_id": cls.other_vendor.id, "company_id": cls.company.id,
            "allow_out_payment": True,
        })
        cls.product = cls.env["product.product"].create({
            "name": "TCC C1-06 SERVICE - SEM VALOR FISCAL",
            "default_code": "TCC-C106-SERVICE", "type": "service",
            "purchase_ok": True, "sale_ok": False,
            "purchase_method": "purchase", "supplier_taxes_id": [Command.clear()],
        })
        cls.purchase = cls.env["purchase.order"].create({
            "name": "TCC-C106-PO-CONFIRMED", "partner_id": cls.vendor.id,
            "company_id": cls.company.id, "currency_id": cls.company.currency_id.id,
            "order_line": [Command.create({
                "name": "TRUSTED C106 PO LINE - SEM VALOR FISCAL",
                "product_id": cls.product.id, "product_qty": 1.0,
                "product_uom_id": cls.product.uom_id.id, "price_unit": 125.50,
                "date_planned": "2026-09-30 12:00:00", "tax_ids": [Command.clear()],
            })],
        })
        cls.purchase.button_confirm()
        cls.purchase_line = cls.purchase.order_line.filtered(lambda row: not row.display_type)
        cls.expense = cls.env["account.account"].search([
            *cls.env["account.account"]._check_company_domain(cls.company),
            ("account_type", "=", "expense"),
        ], limit=1)
        cls.journal = cls.env["account.journal"].search([
            ("company_id", "=", cls.company.id), ("type", "=", "purchase"),
        ], limit=1)
        if not cls.expense or not cls.journal or len(cls.purchase_line) != 1:
            raise AssertionError("Synthetic kernel accounting fixtures are incomplete.")
        if cls.purchase.state != "purchase" or cls.purchase_line.qty_to_invoice != 1.0:
            raise AssertionError("Synthetic kernel purchase is not invoiceable.")
        cls.workflow = TrustedDraftWorkflow(
            company_id=cls.company.id, executor_user_id=cls.executor_user.id,
            purchase_order_id=cls.purchase.id, vendor_id=cls.vendor.id,
            journal_id=cls.journal.id, expense_account_id=cls.expense.id,
            purchase_line_ids=tuple(cls.purchase_line.ids), allowed_bank_ids=(cls.bank.id,),
            scenario_id="TCC-SCN-001", document_sha256="a" * 64,
            policy_version="policy-v1.0.0", phase="DRAFT_INTAKE",
            invoice_date_min="2026-09-01", invoice_date_max="2026-09-30",
            quantity_scale=2, monetary_tolerance="0.00",
        )

    def _key(self, workflow=None):
        workflow = workflow or self.workflow
        return bill_idempotency_key(
            document_sha256=workflow.document_sha256,
            company_id=workflow.company_id, vendor_id=workflow.vendor_id,
            purchase_order_id=workflow.purchase_order_id,
            purchase_line_ids=workflow.purchase_line_ids,
        )

    def _command(self, *, action_changes=None):
        command = _command()
        command["action"].update({
            "vendor_ref": self.vendor.ref, "purchase_order_ref": self.purchase.name,
            "currency": self.company.currency_id.name, "recipient_bank_ref": self.bank.acc_number,
            "document_ref": "TCC-C106-NF-SEM-VALOR-FISCAL",
            "lines": [{"item_code": self.product.default_code, "quantity": "1.00", "unit_price": "125.50"}],
        })
        if action_changes:
            command["action"].update(action_changes)
        command["policy_decision"]["proposed_action_hash"] = _action_hash(command["action"])
        command["idempotency_key"] = self._key()
        return command

    def _state_hash(self, *, include_guard=True):
        """Hash-only error output; not the frozen scientific reset oracle."""
        self.env.invalidate_all()
        projection = {}
        for model, fields in {
            "account.move": ["state", "move_type", "company_id", "partner_id", "partner_bank_id", "ref", "amount_total", "auto_post"],
            "account.move.line": ["move_id", "purchase_line_id", "product_id", "product_uom_id", "quantity", "price_unit", "account_id", "discount", "tax_ids", "debit", "credit"],
            "ap.security.draft.receipt": ["company_id", "executor_mode", "idempotency_key", "command_sha256", "action_sha256", "document_sha256", "po_id", "vendor_id", "purchase_line_ids", "move_id", "executor_user_id", "receipt_payload"],
            "ap.security.po.guard": ["company_id", "po_id", "revision"],
            "ap.security.vendor.guard": ["company_id", "vendor_id", "revision"],
        }.items():
            projection[model] = self.env[model].with_context(active_test=False).search([], order="id").read(fields)
        if not include_guard:
            projection.pop("ap.security.po.guard")
            projection.pop("ap.security.vendor.guard")
        projection["purchase"] = self.purchase.read(["state", "partner_id", "currency_id", "company_id", "amount_total"])
        projection["purchase_line"] = self.purchase_line.read(["product_qty", "qty_invoiced", "qty_to_invoice", "price_unit", "discount", "tax_ids"])
        projection["attachment_count"] = self.env["ir.attachment"].search_count([])
        projection["payment_count"] = self.env["account.payment"].search_count([])
        encoded = json.dumps(projection, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _execute(self, command=None, *, workflow=None, env=None):
        return create_draft_atomic(
            env or self.env, command=command if command is not None else self._command(),
            workflow=workflow or self.workflow,
        )

    def _denied(self, command=None, *, workflow=None, env=None, reason=None):
        before = self._state_hash()
        result = self._execute(command, workflow=workflow, env=env)
        self.assertEqual(result.get("status"), "DENIED", "Kernel did not deny a negative case.")
        self.assertIs(result.get("effect_applied"), False)
        self.assertTrue(result.get("reason_codes"), "Kernel denial lacks a reason.")
        if reason is not None:
            self.assertIn(reason, result["reason_codes"])
        self.assertEqual(before, self._state_hash(), "Denied call changed the critical projection.")
        return result

    def _created(self, command=None, *, workflow=None, env=None):
        result = self._execute(command, workflow=workflow, env=env)
        self.assertEqual(result.get("status"), "CREATED", "Kernel did not create a valid draft.")
        self.assertIs(result.get("effect_applied"), True)
        self.assertEqual(result["receipt"]["idempotency_key"], self._key(workflow))
        move = self.env["account.move"].browse(result["receipt"]["move_id"]).exists()
        self.assertEqual(len(move), 1)
        self.assertEqual(move.state, "draft")
        return result, move

    def test_valid_draft_has_trusted_fields_and_no_other_effects(self):
        moves_before = self.env["account.move"].search_count([])
        receipts_before = self.env["ap.security.draft.receipt"].search_count([])
        attachments_before = self.env["ir.attachment"].search_count([])
        payments_before = self.env["account.payment"].search_count([])
        command = self._command()
        result, move = self._created(command)
        self.assertEqual(self.env["account.move"].search_count([]), moves_before + 1)
        self.assertEqual(self.env["ap.security.draft.receipt"].search_count([]), receipts_before + 1)
        self.assertEqual(self.env["ir.attachment"].search_count([]), attachments_before)
        self.assertEqual(self.env["account.payment"].search_count([]), payments_before)
        self.assertEqual(move.company_id, self.company)
        self.assertEqual(move.partner_id, self.vendor)
        self.assertEqual(move.partner_bank_id, self.bank)
        self.assertEqual(move.journal_id, self.journal)
        self.assertEqual(move.currency_id, self.company.currency_id)
        self.assertEqual(move.move_type, "in_invoice")
        self.assertEqual(move.auto_post, "no")
        self.assertEqual(move.ref, command["action"]["document_ref"])
        self.assertEqual(move.invoice_origin, self.purchase.name)
        self.assertEqual(move.amount_total, 125.50)
        self.assertFalse(move.invoice_payment_term_id or move.fiscal_position_id)
        self.assertEqual(len(move.invoice_line_ids), 1)
        line = move.invoice_line_ids
        self.assertEqual(line.purchase_line_id, self.purchase_line)
        self.assertEqual(line.name, self.purchase_line.name)
        self.assertEqual(line.product_id, self.product)
        self.assertEqual(line.product_uom_id, self.product.uom_id)
        self.assertEqual(line.account_id, self.expense)
        self.assertEqual(line.quantity, 1.0)
        self.assertEqual(line.price_unit, 125.50)
        self.assertFalse(line.tax_ids)
        self.assertEqual(line.discount, 0.0)
        self.assertEqual(result["receipt"]["action_hash"], _action_hash(command["action"]))

    def test_exact_replay_returns_original_receipt_without_writes(self):
        command = self._command()
        first, move = self._created(command)
        before = self._state_hash(include_guard=False)
        replay = self._execute(copy.deepcopy(command))
        self.assertEqual(replay["status"], "REPLAY")
        self.assertIs(replay["effect_applied"], False)
        self.assertEqual(replay["receipt"], first["receipt"])
        self.assertEqual(replay["receipt"]["move_id"], move.id)
        self.assertEqual(before, self._state_hash(include_guard=False))

    def test_replay_precedes_qty_consumption_and_duplicate_checks(self):
        command = self._command()
        first, _ = self._created(command)
        self.env.invalidate_all()
        self.assertEqual(self.purchase_line.qty_to_invoice, 0.0)
        self.assertEqual(self._execute(command)["receipt"], first["receipt"])

    def test_changed_reference_with_same_identity_conflicts(self):
        self._created()
        self._denied(self._command(action_changes={"document_ref": "TCC-C106-CHANGED-REF"}), reason="IDEMPOTENCY_CONFLICT")

    def test_changed_date_with_same_identity_conflicts(self):
        self._created()
        self._denied(self._command(action_changes={"invoice_date": "2026-09-29"}), reason="IDEMPOTENCY_CONFLICT")

    def test_changed_amount_with_same_identity_conflicts(self):
        self._created()
        changed = self._command(action_changes={"amount": "124.50", "lines": [{
            "item_code": self.product.default_code, "quantity": "1.00", "unit_price": "124.50",
        }]})
        self._denied(changed, reason="IDEMPOTENCY_CONFLICT")

    def test_changed_decision_timestamps_with_same_body_identity_conflicts(self):
        command = self._command()
        self._created(command)
        changed = copy.deepcopy(command)
        changed["policy_decision"].update({"evaluated_at": "2020-01-02T00:00:00Z", "expires_at": "2020-01-02T00:05:00Z"})
        self._denied(changed, reason="IDEMPOTENCY_CONFLICT")

    def test_forged_idempotency_key_is_denied(self):
        command = self._command()
        command["idempotency_key"] = "sha256:" + "e" * 64
        self._denied(command, reason="IDEMPOTENCY_KEY_MISMATCH")

    def test_bad_action_hash_is_denied(self):
        command = self._command()
        command["policy_decision"]["proposed_action_hash"] = "sha256:" + "e" * 64
        before = self._state_hash()
        with self.assertRaises(ValidationError):
            self._execute(command)
        self.assertEqual(before, self._state_hash())

    def test_private_kernel_does_not_accept_post(self):
        command = _command(post=True)
        command["idempotency_key"] = self._key()
        self._denied(command)

    def test_command_is_not_mutated(self):
        command = self._command()
        original = copy.deepcopy(command)
        self._created(command)
        self.assertEqual(command, original)

    def test_unprivileged_identity_cannot_call_administrative_kernel(self):
        before = self._state_hash()
        restricted = api.Environment(self.env.cr, self.executor_user.id, {}, su=False)
        with self.assertRaises(AccessError):
            self._execute(env=restricted)
        self.assertEqual(before, self._state_hash())

    def test_workflow_bindings_are_not_selected_by_proposal(self):
        for changes in ({"scenario_id": "TCC-WRONG-SCENARIO"}, {"document_sha256": "e" * 64},
                        {"vendor_ref": self.other_vendor.ref}, {"purchase_order_ref": "TCC-WRONG-PO"}):
            with self.subTest(field=next(iter(changes))):
                self._denied(self._command(action_changes=changes))

    def test_workflow_company_mismatch_is_denied(self):
        self._denied(workflow=replace(self.workflow, company_id=self.other_company.id))

    def test_unconfirmed_purchase_is_denied(self):
        self.purchase.button_cancel()
        self._denied(reason="PURCHASE_ORDER_NOT_CONFIRMED")

    def test_purchase_supplier_change_is_denied(self):
        self.purchase.partner_id = self.other_vendor
        self._denied()

    def test_purchase_currency_change_is_denied(self):
        currency = self.env["res.currency"].with_context(active_test=False).search([
            ("id", "!=", self.company.currency_id.id),
        ], limit=1)
        self.assertTrue(currency, "A distinct synthetic test currency is required.")
        currency.active = True
        self.purchase.currency_id = currency
        self._denied()

    def test_line_price_change_is_denied(self):
        self.purchase_line.price_unit = 124.50
        self._denied()

    def test_insufficient_invoiceable_quantity_is_denied(self):
        self.purchase_line.product_qty = 0.50
        self._denied()

    def test_product_invoice_policy_change_is_denied(self):
        self.product.purchase_method = "receive"
        self._denied()

    def test_discount_outside_fixed_scope_is_denied(self):
        self.purchase_line.discount = 1.0
        self._denied()

    def test_tax_outside_fixed_scope_is_denied(self):
        tax = self.env["account.tax"].create({
            "name": "TCC C1-06 TAX - SEM VALOR FISCAL", "company_id": self.company.id,
            "amount_type": "percent", "amount": 1.0, "type_tax_use": "purchase",
        })
        self.purchase_line.tax_ids = [Command.set(tax.ids)]
        self._denied()

    def test_inactive_bank_is_denied(self):
        self.bank.active = False
        self._denied(reason="BANK_NOT_ALLOWED")

    def test_untrusted_bank_is_denied(self):
        self.bank.allow_out_payment = False
        self._denied(reason="BANK_NOT_ALLOWED")

    def test_bank_with_other_supplier_is_denied(self):
        self.bank.partner_id = self.other_vendor
        self._denied()

    def test_proposed_nonallowlisted_bank_is_denied(self):
        self._denied(self._command(action_changes={"recipient_bank_ref": self.other_bank.acc_number}), reason="BANK_NOT_ALLOWED")

    def test_duplicate_reference_is_denied(self):
        self.env["account.move"].create({
            "move_type": "in_invoice", "company_id": self.company.id,
            "partner_id": self.vendor.id, "currency_id": self.company.currency_id.id,
            "journal_id": self.journal.id, "invoice_date": "2026-09-30",
            "ref": self._command()["action"]["document_ref"], "auto_post": "no",
        })
        self._denied(reason="DUPLICATE_DOCUMENT")

    def test_invoice_date_window_is_enforced(self):
        for value in ("2026-08-31", "2026-10-01"):
            with self.subTest(boundary=value):
                self._denied(self._command(action_changes={"invoice_date": value}), reason="DATE_OUTSIDE_WINDOW")

    def test_hostile_context_does_not_choose_financial_state(self):
        hostile = api.Environment(self.env.cr, self.env.uid, {
            "allowed_company_ids": [self.other_company.id], "force_company": self.other_company.id,
            "default_company_id": self.other_company.id, "default_partner_id": self.other_vendor.id,
            "default_partner_bank_id": self.other_bank.id, "default_move_type": "out_invoice",
            "default_auto_post": "at_date", "lang": "hostile_LANG", "tz": "hostile_TZ",
            "check_move_validity": False, "skip_invoice_sync": True, "active_test": False,
        }, su=True)
        _, move = self._created(env=hostile)
        self.assertEqual(move.company_id, self.company)
        self.assertEqual(move.partner_id, self.vendor)
        self.assertEqual(move.partner_bank_id, self.bank)
        self.assertEqual(move.move_type, "in_invoice")
        self.assertEqual(move.auto_post, "no")

    def test_c1_personal_financial_defaults_are_not_consumed(self):
        defaults = self.env["ir.default"].with_user(self.executor_user)
        for name, value in {
            "partner_id": self.other_vendor.id, "partner_bank_id": self.other_bank.id,
            "move_type": "out_invoice", "auto_post": "at_date",
        }.items():
            defaults.set("account.move", name, value, user_id=True, company_id=True)
        _, move = self._created()
        self.assertEqual(move.partner_id, self.vendor)
        self.assertEqual(move.partner_bank_id, self.bank)
        self.assertEqual(move.move_type, "in_invoice")
        self.assertEqual(move.auto_post, "no")

    def test_global_financial_defaults_are_denied_without_repair(self):
        defaults = self.env["ir.default"]
        defaults.set("account.move", "auto_post", "at_date", company_id=self.company.id)
        before_defaults = defaults.search_count([])
        self._denied()
        self.assertEqual(defaults.search_count([]), before_defaults)
        self.assertEqual(defaults._get("account.move", "auto_post", company_id=self.company.id), "at_date")

    def test_receipt_uniqueness_is_enforced_in_database(self):
        result, _ = self._created()
        receipt = self.env["ap.security.draft.receipt"].browse(result["receipt"]["receipt_id"])
        values = receipt.copy_data()[0]
        with self.assertRaises(UniqueViolation) as caught:
            with self.env.cr.savepoint():
                self.env["ap.security.draft.receipt"].create(values)
                self.env.flush_all()
        self.assertEqual(caught.exception.pgcode, "23505")
        self.assertEqual(self.env["ap.security.draft.receipt"].search_count([
            ("company_id", "=", self.company.id), ("executor_mode", "=", "CREATE_DRAFT"),
            ("idempotency_key", "=", self._key()),
        ]), 1)

    def test_receipt_and_guard_have_no_direct_c1_permissions(self):
        for model in ("ap.security.draft.receipt", "ap.security.po.guard",
                      "ap.security.vendor.guard"):
            records = self.env[model].with_user(self.executor_user)
            for operation in ("read", "write", "create", "unlink"):
                with self.subTest(model=model, operation=operation):
                    self.assertFalse(records.has_access(operation))

    def test_vendor_guard_uniqueness_is_enforced_in_database(self):
        guards = self.env["ap.security.vendor.guard"]
        values = {"company_id": self.company.id, "vendor_id": self.vendor.id, "revision": 0}
        guards.create(values)
        self.env.flush_all()
        with self.assertRaises(UniqueViolation) as caught:
            with self.env.cr.savepoint():
                guards.create(values)
                self.env.flush_all()
        self.assertEqual(caught.exception.pgcode, "23505")
        self.assertEqual(guards.search_count([
            ("company_id", "=", self.company.id), ("vendor_id", "=", self.vendor.id),
        ]), 1)

    def test_vendor_guard_is_scoped_to_trusted_company_and_vendor(self):
        guards = self.env["ap.security.vendor.guard"]
        first = guards.create({"company_id": self.company.id, "vendor_id": self.vendor.id})
        second = guards.create({"company_id": self.company.id, "vendor_id": self.other_vendor.id})
        other_vendor = self.env["res.partner"].create({
            "name": "TCC GUARD OTHER COMPANY SUPPLIER - SEM VALOR FISCAL",
            "company_id": self.other_company.id, "supplier_rank": 1,
        })
        third = guards.create({"company_id": self.other_company.id, "vendor_id": other_vendor.id})
        self.env.flush_all()
        self.assertEqual(len(first | second | third), 3)
        with self.assertRaises(UserError):
            with self.env.cr.savepoint():
                guards.create({"company_id": self.other_company.id, "vendor_id": self.vendor.id})
                self.env.flush_all()

    def test_vendor_guard_system_acl_has_no_unlink_authority(self):
        administrator = self.env.ref("base.user_admin")
        self.assertNotEqual(administrator.id, SUPERUSER_ID)
        self.assertTrue(administrator.has_group("base.group_system"))
        guards = self.env["ap.security.vendor.guard"].with_user(administrator)
        for operation in ("read", "write", "create"):
            with self.subTest(operation=operation):
                self.assertTrue(guards.has_access(operation))
        self.assertFalse(guards.has_access("unlink"))

    def test_shared_guard_revisions_do_not_write_master_or_financial_state(self):
        from .. import post_kernel

        self.assertIs(post_kernel._guard, draft_kernel._guard)
        vendor_before = self.vendor.read([
            "name", "ref", "company_id", "supplier_rank", "autopost_bills", "write_date",
        ])
        company_before = self.company.read(["name", "currency_id", "write_date"])
        financial_before = self._state_hash(include_guard=False)
        first_po_guard_id = draft_kernel._guard(self.env, self.workflow)
        second_po_guard_id = draft_kernel._guard(self.env, self.workflow)
        self.assertEqual(first_po_guard_id, second_po_guard_id)
        vendor_guard = self.env["ap.security.vendor.guard"].search([
            ("company_id", "=", self.company.id), ("vendor_id", "=", self.vendor.id),
        ])
        po_guard = self.env["ap.security.po.guard"].browse(first_po_guard_id)
        self.assertEqual(len(vendor_guard), 1)
        self.assertEqual(vendor_guard.revision, 2)
        self.assertEqual(po_guard.revision, 2)
        self.assertEqual(financial_before, self._state_hash(include_guard=False))
        self.assertEqual(vendor_before, self.vendor.read([
            "name", "ref", "company_id", "supplier_rank", "autopost_bills", "write_date",
        ]))
        self.assertEqual(company_before, self.company.read(["name", "currency_id", "write_date"]))

    def test_guard_creation_rolls_back_before_any_financial_write(self):
        before = self._state_hash()
        with unittest.TestCase.assertRaises(self, RuntimeError):
            with self.env.cr.savepoint():
                draft_kernel._guard(self.env, self.workflow)
                raise RuntimeError("TCC-INJECTED-GUARD-FAULT")
        self.assertEqual(before, self._state_hash())

    def test_existing_guard_revision_rolls_back_on_business_denial(self):
        po_guard_id = draft_kernel._guard(self.env, self.workflow)
        vendor_guard = self.env["ap.security.vendor.guard"].search([
            ("company_id", "=", self.company.id), ("vendor_id", "=", self.vendor.id),
        ])
        self.assertEqual(vendor_guard.revision, 1)
        self._denied(self._command(action_changes={
            "recipient_bank_ref": self.other_bank.acc_number,
        }), reason="BANK_NOT_ALLOWED")
        self.assertEqual(vendor_guard.revision, 1)
        self.assertEqual(self.env["ap.security.po.guard"].browse(po_guard_id).revision, 1)

    def test_vendor_guard_privilege_drift_denies_before_guard_write(self):
        self.env["ir.model.access"].create({
            "name": "TCC SYNTHETIC GUARD ACL DRIFT - SEM VALOR FISCAL",
            "model_id": self.env["ir.model"]._get_id("ap.security.vendor.guard"),
            "group_id": self.env.ref("ap_security_executor.group_executor").id,
            "perm_read": True, "perm_write": False,
            "perm_create": False, "perm_unlink": False,
        })
        self.assertTrue(self.env["ap.security.vendor.guard"].with_user(self.executor_user).has_access("read"))
        self._denied(reason="EXECUTOR_IDENTITY_INVALID")

    def test_global_vendor_guard_default_is_denied_without_repair(self):
        defaults = self.env["ir.default"]
        defaults.set("ap.security.vendor.guard", "revision", 100, company_id=self.company.id)
        self._denied(reason="UNTRUSTED_FINANCIAL_DEFAULTS")
        self.assertEqual(defaults._get(
            "ap.security.vendor.guard", "revision", company_id=self.company.id,
        ), 100)

    def test_failure_after_draft_creation_rolls_back_and_retry_works(self):
        before = self._state_hash()
        with patch.object(draft_kernel, "_after_draft_create", side_effect=RuntimeError("TCC-INJECTED-FAULT")):
            # Odoo's assertRaises adds a savepoint. Bypass that wrapper so only
            # the kernel can roll back the injected financial side effects.
            with unittest.TestCase.assertRaises(self, RuntimeError):
                self._execute()
        self.assertEqual(before, self._state_hash(), "Fault after draft creation left residue.")
        self._created()

    def test_failure_after_receipt_insert_rolls_back_draft_and_receipt(self):
        receipt_class = type(self.env["ap.security.draft.receipt"])
        original_create = receipt_class.create

        @api.model_create_multi
        def failing_create(records, vals_list):
            original_create(records, vals_list)
            raise RuntimeError("TCC-INJECTED-RECEIPT-FAULT")

        before = self._state_hash()
        with patch.object(receipt_class, "create", failing_create):
            with unittest.TestCase.assertRaises(self, RuntimeError):
                self._execute()
        self.assertEqual(before, self._state_hash(), "Fault after receipt insertion left residue.")
        self._created()

    def test_public_execute_remains_closed_after_kernel_exists(self):
        before = self._state_hash()
        result = self.env["ap.security.executor"].with_user(self.executor_user).execute(self._command())
        self.assertEqual(result["decision"], "DENY")
        self.assertEqual(result["executor_status"], "SCAFFOLD_NOT_READY")
        self.assertIs(result["effect_applied"], False)
        self.assertEqual(before, self._state_hash())

    def test_document_uniqueness_rejects_a_different_idempotency_key(self):
        result, _ = self._created()
        receipt = self.env["ap.security.draft.receipt"].browse(result["receipt"]["receipt_id"])
        values = receipt.copy_data()[0]
        values["idempotency_key"] = "sha256:" + "e" * 64
        with self.assertRaises(UniqueViolation) as caught:
            with self.env.cr.savepoint():
                self.env["ap.security.draft.receipt"].create(values)
                self.env.flush_all()
        self.assertEqual(caught.exception.pgcode, "23505")
        self.assertEqual(self.env["ap.security.draft.receipt"].search_count([
            ("company_id", "=", self.company.id), ("executor_mode", "=", "CREATE_DRAFT"),
            ("document_sha256", "=", self.workflow.document_sha256),
        ]), 1)

    def test_missing_vendor_payable_account_is_denied_without_repair(self):
        self.vendor.with_company(self.company).property_account_payable_id = False
        self._denied()
        self.assertFalse(self.vendor.with_company(self.company).property_account_payable_id)

    def test_inactive_vendor_payable_account_is_denied_without_repair(self):
        payable = self.vendor.with_company(self.company).property_account_payable_id
        self.assertTrue(payable, "The synthetic fixture lacks its payable account.")
        payable.active = False
        self._denied()
        self.assertFalse(payable.active)

    def test_replay_does_not_consume_negative_current_invoiceable_quantity(self):
        command = self._command()
        original, first_move = self._created(command)
        self.env["account.move"].create({
            "move_type": "in_invoice", "company_id": self.company.id,
            "partner_id": self.vendor.id, "currency_id": self.company.currency_id.id,
            "journal_id": self.journal.id, "invoice_date": "2026-09-30", "auto_post": "no",
            "ref": "TCC-C106-SEPARATE-ADMINISTRATIVE-DRAFT-SEM-VALOR-FISCAL",
            "invoice_line_ids": [Command.create({
                "name": self.purchase_line.name, "product_id": self.product.id,
                "product_uom_id": self.product.uom_id.id, "account_id": self.expense.id,
                "quantity": 1.0, "price_unit": 125.50, "discount": 0.0,
                "purchase_line_id": self.purchase_line.id, "tax_ids": [Command.clear()],
            })],
        })
        self.env.invalidate_all()
        self.assertEqual(self.purchase_line.qty_to_invoice, -1.0)
        before = self._state_hash(include_guard=False)
        replay = self._execute(command)
        self.assertEqual(replay["status"], "REPLAY")
        self.assertEqual(replay["receipt"], original["receipt"])
        self.assertEqual(replay["receipt"]["move_id"], first_move.id)
        self.assertEqual(before, self._state_hash(include_guard=False))

    def test_closed_accounting_period_denies_without_adjusting_invoice_date(self):
        self.company.fiscalyear_lock_date = "2026-09-30"
        command = self._command()
        original = copy.deepcopy(command)
        self._denied(command, reason="ACCOUNTING_PERIOD_CLOSED")
        self.assertEqual(command, original)

    def test_two_trusted_lines_with_fractional_quantity_create_correct_draft(self):
        product = self.env["product.product"].create({
            "name": "TCC C1-06 SECOND SERVICE - SEM VALOR FISCAL",
            "default_code": "TCC-C106-SERVICE-B", "type": "service",
            "purchase_ok": True, "sale_ok": False, "purchase_method": "purchase",
            "supplier_taxes_id": [Command.clear()],
        })
        second_line = self.env["purchase.order.line"].create({
            "order_id": self.purchase.id, "name": "TRUSTED SECOND PO LINE - SEM VALOR FISCAL",
            "product_id": product.id, "product_qty": 0.50, "price_unit": 10.50,
            "product_uom_id": product.uom_id.id, "date_planned": "2026-09-30 12:00:00",
            "tax_ids": [Command.clear()],
        })
        workflow = replace(self.workflow, purchase_line_ids=tuple(sorted(
            (self.purchase_line | second_line).ids,
        )))
        command = self._command(action_changes={
            "amount": "130.75", "lines": sorted([
                {"item_code": self.product.default_code, "quantity": "1.00", "unit_price": "125.50"},
                {"item_code": product.default_code, "quantity": "0.50", "unit_price": "10.50"},
            ], key=lambda row: row["item_code"]),
        })
        command["idempotency_key"] = self._key(workflow)
        _, move = self._created(command, workflow=workflow)
        self.assertEqual(move.amount_total, 130.75)
        self.assertEqual(len(move.invoice_line_ids), 2)
        self.assertEqual(set(move.invoice_line_ids.purchase_line_id.ids), set(workflow.purchase_line_ids))
        fractional = move.invoice_line_ids.filtered(lambda row: row.purchase_line_id == second_line)
        self.assertEqual(len(fractional), 1)
        self.assertEqual(fractional.quantity, 0.50)
        self.assertEqual(fractional.price_unit, 10.50)
        self.assertEqual(fractional.name, second_line.name)
        self.assertEqual(fractional.account_id, self.expense)

    def test_adulterated_persisted_beneficiary_is_denied_and_rolled_back(self):
        def corrupt_beneficiary(move):
            # Alter the real newly-created record, not the authorization checks.
            move.write({"partner_bank_id": self.other_bank.id})

        with patch.object(draft_kernel, "_after_draft_create", corrupt_beneficiary):
            self._denied(reason="PERSISTED_STATE_MISMATCH")
        self._created()

    def test_shared_or_rank_zero_supplier_is_not_trusted(self):
        for values in ({"company_id": False}, {"supplier_rank": 0}):
            with self.subTest(field=next(iter(values))):
                self.vendor.write(values)
                self._denied(reason="WORKFLOW_MISMATCH")
                self.vendor.write({"company_id": self.company.id, "supplier_rank": 1})

    def test_vendor_autopost_is_denied_without_disabling_it(self):
        self.vendor.autopost_bills = "always"
        self._denied(reason="STATE_INVALID")
        self.assertEqual(self.vendor.autopost_bills, "always")

    def test_service_user_accounting_exception_does_not_authorize_c1(self):
        self.company.fiscalyear_lock_date = "2026-09-30"
        exception = self.env["account.lock_exception"].create({
            "company_id": self.company.id, "user_id": SUPERUSER_ID,
            "fiscalyear_lock_date": False,
            "reason": "TCC C1-06 SERVICE-ONLY EXCEPTION - SEM VALOR FISCAL",
        })
        self.assertEqual(exception.state, "active")
        invoice_date = date(2026, 9, 30)
        service_company = self.company.with_user(SUPERUSER_ID).sudo()
        self.assertFalse(service_company._get_violated_lock_dates(
            invoice_date, False, self.journal,
        ), "The synthetic exception must really open the service user's period.")
        c1_company = self.company.with_user(self.executor_user).sudo()
        self.assertTrue(c1_company._get_violated_lock_dates(
            invoice_date, False, self.journal,
        ), "The service-only exception must not open C1's accounting period.")
        self._denied(reason="ACCOUNTING_PERIOD_CLOSED")
