# SPDX-License-Identifier: LGPL-3.0-or-later
"""Real, disposable ORM proof of private C1-08 posting.

All accounting fixtures are synthetic and without fiscal value. Genuine
runtime MACs protect the private flow; the public endpoint stays closed.
This suite does not attest independent-cursor concurrency or a pilot.
"""

import copy
from collections import defaultdict
from dataclasses import replace
from datetime import date, datetime, timezone
import hashlib
import hmac
import json
import secrets
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from psycopg2 import OperationalError

from odoo import Command, api
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged
from odoo.tools.misc import Callbacks

from .. import approval_kernel, post_kernel
from ..approval import APPROVAL_DOMAIN, ApprovalAuthority, ApprovalKey
from ..approval_kernel import approval_transaction
from ..draft_contracts import TrustedDraftWorkflow, bill_idempotency_key
from ..draft_kernel import create_draft_atomic
from ..identity import provision_executor_identity
from ..post_contracts import TrustedPostWorkflow
from ..post_kernel import post_bill_atomic
from .test_executor import _action_hash, _command


def _bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False, default=str,
    ).encode("utf-8")


@tagged("post_install", "-at_install", "c1_post_kernel")
class TestPostKernel(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({
            "name": "TCC C1-08 COMPANY - SEM VALOR FISCAL",
        })
        cls.env = cls.env(context={**cls.env.context, "allowed_company_ids": [cls.company.id]})
        cls.env["account.chart.template"].try_loading(
            "generic_coa", company=cls.company, install_demo=False,
        )
        cls.other_company = cls.env["res.company"].create({
            "name": "TCC C1-08 OTHER COMPANY - SEM VALOR FISCAL",
        })
        cls.executor_user = provision_executor_identity(
            cls.env, login="tcc-c108-post-kernel", company=cls.company,
        )
        cls.vendor = cls.env["res.partner"].create({
            "name": "TCC C1-08 SUPPLIER - SEM VALOR FISCAL",
            "ref": "TCC-C108-VENDOR", "is_company": True,
            "company_id": cls.company.id, "supplier_rank": 1, "autopost_bills": "never",
        })
        cls.other_vendor = cls.env["res.partner"].create({
            "name": "TCC C1-08 OTHER SUPPLIER - SEM VALOR FISCAL",
            "ref": "TCC-C108-OTHER-VENDOR", "is_company": True,
            "company_id": cls.company.id, "supplier_rank": 1, "autopost_bills": "never",
        })
        cls.bank = cls.env["res.partner.bank"].create({
            "acc_number": "TCC-C108-SYNTHETIC-BANK", "partner_id": cls.vendor.id,
            "company_id": cls.company.id, "allow_out_payment": True,
        })
        cls.other_bank = cls.env["res.partner.bank"].create({
            "acc_number": "TCC-C108-OTHER-SYNTHETIC-BANK", "partner_id": cls.other_vendor.id,
            "company_id": cls.company.id, "allow_out_payment": True,
        })
        cls.product = cls.env["product.product"].create({
            "name": "TCC C1-08 SERVICE - SEM VALOR FISCAL", "default_code": "TCC-C108-SERVICE",
            "type": "service", "purchase_ok": True, "sale_ok": False,
            "purchase_method": "purchase", "supplier_taxes_id": [Command.clear()],
        })
        cls.purchase = cls.env["purchase.order"].create({
            "name": "TCC-C108-PO-CONFIRMED", "partner_id": cls.vendor.id,
            "company_id": cls.company.id, "currency_id": cls.company.currency_id.id,
            "order_line": [Command.create({
                "name": "TRUSTED C108 PO LINE - SEM VALOR FISCAL",
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
            raise AssertionError("Synthetic POST accounting fixtures are incomplete.")
        cls.draft_workflow = TrustedDraftWorkflow(
            company_id=cls.company.id, executor_user_id=cls.executor_user.id,
            purchase_order_id=cls.purchase.id, vendor_id=cls.vendor.id,
            journal_id=cls.journal.id, expense_account_id=cls.expense.id,
            purchase_line_ids=tuple(cls.purchase_line.ids), allowed_bank_ids=(cls.bank.id,),
            scenario_id="TCC-SCN-001", document_sha256="a" * 64,
            policy_version="policy-v1.0.0", phase="DRAFT_INTAKE",
            invoice_date_min="2026-09-01", invoice_date_max="2026-09-30",
            quantity_scale=2, monetary_tolerance="0.00",
        )

    def setUp(self):
        super().setUp()
        self.now = datetime(2026, 10, 3, 12, 5, tzinfo=timezone.utc)
        draft_command = _command()
        draft_command["action"].update({
            "vendor_ref": self.vendor.ref, "purchase_order_ref": self.purchase.name,
            "currency": self.company.currency_id.name, "recipient_bank_ref": self.bank.acc_number,
            "document_ref": "TCC-C108-NF-SEM-VALOR-FISCAL",
            "lines": [{"item_code": self.product.default_code, "quantity": "1.00", "unit_price": "125.50"}],
        })
        draft_command["policy_decision"]["proposed_action_hash"] = _action_hash(draft_command["action"])
        draft_command["idempotency_key"] = bill_idempotency_key(
            document_sha256=self.draft_workflow.document_sha256,
            company_id=self.company.id, vendor_id=self.vendor.id,
            purchase_order_id=self.purchase.id, purchase_line_ids=tuple(self.purchase_line.ids),
        )
        result = create_draft_atomic(self.env, command=draft_command, workflow=self.draft_workflow)
        if result.get("status") != "CREATED":
            raise AssertionError("Synthetic POST fixture could not create its original draft.")
        self.move = self.env["account.move"].browse(result["receipt"]["move_id"])
        self.draft_receipt = self.env["ap.security.draft.receipt"].browse(result["receipt"]["receipt_id"])
        self.workflow = TrustedPostWorkflow(draft=self.draft_workflow, target_move_id=self.move.id)
        self.key = ApprovalKey(
            company_id=self.company.id, key_id="tcc-c108-key-v1", material=secrets.token_bytes(32),
        )
        self.authority = ApprovalAuthority(
            company_id=self.company.id, executor_user_id=self.executor_user.id,
            fixture_id="TCC-C108-APR-001", scenario_id="TCC-SCN-001",
            approver_ref="TCC-C108-SYNTHETIC-APPROVER", nonce=secrets.token_urlsafe(24),
            issued_at="2026-10-03T12:00:00Z", expires_at="2026-10-03T12:10:00Z",
            key_id=self.key.key_id,
        )
        self.registered_action = {
            **copy.deepcopy(draft_command["action"]), "action": "POST_VENDOR_BILL",
            "executor_mode": "POST_APPROVED", "target_move_id": self.move.id,
        }
        self.idempotency_key = draft_command["idempotency_key"]
        self.command = self._signed_command()

    def _signed_command(self, *, authority=None, key=None, action_changes=None):
        registered = authority or self.authority
        selected = key or self.key
        command = _command(post=True)
        command["action"] = copy.deepcopy(self.registered_action)
        if action_changes:
            command["action"].update(action_changes)
        command["idempotency_key"] = self.idempotency_key
        digest = _action_hash(command["action"])
        command["policy_decision"].update({
            "proposed_action_hash": digest, "evaluated_at": registered.issued_at,
            "expires_at": registered.expires_at,
        })
        unsigned = {
            "fixture_id": registered.fixture_id, "scenario_id": registered.scenario_id,
            "approver_ref": registered.approver_ref, "decision": "APPROVE",
            "canonical_action_hash": digest, "nonce": registered.nonce,
            "issued_at": registered.issued_at, "expires_at": registered.expires_at,
            "key_id": registered.key_id,
        }
        signature = "hmac-sha256/v1:" + hmac.new(
            selected.material, APPROVAL_DOMAIN + _bytes({"company_id": registered.company_id, "approval": unsigned}),
            hashlib.sha256,
        ).hexdigest()
        command["approval"] = {**unsigned, "signature": signature}
        return command

    def _ledger(self):
        return self.env["ap.security.approval.nonce"].sudo().with_context(active_test=False)

    def _post_receipts(self):
        return self.env["ap.security.draft.receipt"].sudo().search([
            ("company_id", "=", self.company.id), ("executor_mode", "=", "POST_APPROVED"),
        ])

    def _effects(self):
        return {
            model: self.env[model].sudo().with_context(active_test=False).search_count([])
            for model in (
                "account.move", "account.move.line", "account.payment", "account.partial.reconcile",
                "account.full.reconcile", "account.analytic.line", "ir.attachment", "mail.mail", "mail.notification",
            )
        }

    def _state_hash(self, *, include_guard=True):
        """Hash-only test projection; not the final frozen experiment oracle."""
        self.env.flush_all()
        self.env.invalidate_all()
        projection = {}
        for model, names in {
            "account.move": ["state", "posted_before", "name", "sequence_number", "sequence_prefix", "company_id", "partner_id", "partner_bank_id", "journal_id", "currency_id", "move_type", "ref", "invoice_origin", "invoice_date", "date", "amount_total", "auto_post", "reversed_entry_id", "reversal_move_ids"],
            "account.move.line": ["move_id", "purchase_line_id", "product_id", "product_uom_id", "quantity", "price_unit", "account_id", "discount", "tax_ids", "debit", "credit", "amount_currency", "reconciled", "matched_debit_ids", "matched_credit_ids", "analytic_distribution", "is_imported", "matching_number", "deductible_amount"],
            "ap.security.draft.receipt": ["company_id", "executor_mode", "idempotency_key", "command_sha256", "action_sha256", "document_sha256", "po_id", "vendor_id", "purchase_line_ids", "move_id", "executor_user_id", "receipt_payload"],
            "ap.security.approval.nonce": ["company_id", "executor_user_id", "key_id", "fixture_id", "scenario_id", "approver_ref", "nonce_sha256", "action_sha256", "approval_sha256", "command_sha256", "state", "verified_at", "expires_at", "consumed_at"],
            "ap.security.po.guard": ["company_id", "po_id", "revision"],
            "ap.security.vendor.guard": ["company_id", "vendor_id", "revision"],
        }.items():
            projection[model] = self.env[model].sudo().with_context(active_test=False).search([], order="id").read(names)
        if not include_guard:
            projection.pop("ap.security.po.guard")
            projection.pop("ap.security.vendor.guard")
        projection["purchase"] = self.purchase.read(["state", "partner_id", "currency_id", "company_id", "amount_total"])
        projection["purchase_line"] = self.purchase_line.read(["product_qty", "qty_invoiced", "qty_to_invoice", "price_unit", "discount", "tax_ids"])
        projection["vendor"] = self.vendor.read(["supplier_rank", "autopost_bills"])
        projection["journal"] = self.journal.read(["restrict_mode_hash_table"])
        projection["effects"] = self._effects()
        projection["deferred_effects"] = {
            "callback_count": len(self.env.cr.postcommit),
            "data_sha256": hashlib.sha256(_bytes(self.env.cr.postcommit.data)).hexdigest(),
        }
        return hashlib.sha256(_bytes(projection)).hexdigest()

    def _execute(self, command=None, *, workflow=None, authority=None, key=None, env=None, clock=None):
        with patch.object(post_kernel, "_utc_now", side_effect=clock or (lambda: self.now)):
            return post_bill_atomic(
                self.env if env is None else env,
                command=self.command if command is None else command,
                workflow=self.workflow if workflow is None else workflow,
                authority=self.authority if authority is None else authority,
                key=self.key if key is None else key,
            )

    def _denied(self, command=None, *, reason=None, **changes):
        before = self._state_hash()
        result = self._execute(command, **changes)
        self.assertEqual(result.get("schema_version"), "post-kernel-result/v1")
        self.assertEqual(result.get("status"), "DENIED", "Private POST accepted a negative case.")
        self.assertIs(result.get("effect_applied"), False)
        self.assertTrue(result.get("reason_codes"), "POST denial lacks a safe reason.")
        if reason is not None:
            self.assertIn(reason, result["reason_codes"])
        self.assertEqual(self._state_hash(), before, "Denied POST changed the critical projection.")
        return result

    def _posted(self, **changes):
        result = self._execute(**changes)
        self.assertEqual(result.get("schema_version"), "post-kernel-result/v1")
        self.assertEqual(result.get("status"), "POSTED", "Valid private POST did not post.")
        self.assertIs(result.get("effect_applied"), True)
        self.move.invalidate_recordset()
        self.assertEqual(self.move.state, "posted")
        return result

    def test_valid_post_uses_native_accounting_without_extra_effects(self):
        before = self._effects()
        rank = self.vendor.supplier_rank
        original_callbacks = self.env.cr.postcommit
        callback_count = len(original_callbacks)
        deferred_data = hashlib.sha256(_bytes(original_callbacks.data)).hexdigest()
        result = self._posted()
        self.assertEqual(self._effects(), before)
        self.assertTrue(self.move.posted_before)
        self.assertTrue(self.move.name and self.move.name != "/")
        self.assertEqual(self.move.partner_id, self.vendor)
        self.assertEqual(self.move.partner_bank_id, self.bank)
        self.assertEqual(self.move.amount_total, 125.50)
        self.assertEqual(self.move.invoice_date, date(2026, 9, 30))
        self.assertEqual(self.move.date, date(2026, 9, 30))
        self.assertEqual(self.move.auto_post, "no")
        self.assertEqual(self.move.invoice_line_ids.purchase_line_id, self.purchase_line)
        self.assertFalse(self.move.line_ids.matched_debit_ids or self.move.line_ids.matched_credit_ids)
        self.vendor.invalidate_recordset()
        # Native rank updates are deferred; this test never commits or runs
        # callbacks against a second cursor. Production lifecycle is C1-11.
        self.assertEqual(self.vendor.supplier_rank, rank)
        self.assertIs(self.env.cr.postcommit, original_callbacks)
        self.assertEqual(len(original_callbacks), callback_count + 1)
        self.assertEqual(hashlib.sha256(_bytes(original_callbacks.data)).hexdigest(), deferred_data)
        self.assertEqual(result["receipt"]["move_id"], self.move.id)
        self.assertEqual(result["receipt"]["idempotency_key"], self.idempotency_key)
        self.assertEqual(result["receipt"]["action_hash"], _action_hash(self.command["action"]))
        self.assertEqual(len(self._post_receipts()), 1)
        self.assertEqual(self.draft_receipt.executor_mode, "CREATE_DRAFT")
        ledger = self._ledger().browse(result["receipt"]["approval_ledger_id"])
        self.assertEqual(ledger.state, "consumed")
        self.assertEqual(ledger.action_sha256, result["receipt"]["action_hash"])
        self.assertTrue(ledger.consumed_at)

    def test_post_does_not_recheck_quantity_consumed_by_its_draft(self):
        self.purchase_line.invalidate_recordset()
        self.assertEqual(self.purchase_line.qty_to_invoice, 0.0)
        self._posted()

    def test_identical_replay_returns_original_receipt_without_native_effects(self):
        first = self._posted()
        before = self._state_hash(include_guard=False)
        replay = self._execute(copy.deepcopy(self.command))
        self.assertEqual(replay["status"], "REPLAY")
        self.assertIs(replay["effect_applied"], False)
        self.assertEqual(replay["receipt"], first["receipt"])
        self.assertEqual(self._state_hash(include_guard=False), before)

    def test_expired_identical_replay_does_not_grant_a_new_effect(self):
        first = self._posted()
        before = self._state_hash(include_guard=False)
        replay = self._execute(clock=lambda: datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(replay["status"], "REPLAY")
        self.assertEqual(replay["receipt"], first["receipt"])
        self.assertIs(replay["effect_applied"], False)
        self.assertEqual(self._state_hash(include_guard=False), before)

    def test_replay_changed_command_timestamps_conflicts(self):
        self._posted()
        command = copy.deepcopy(self.command)
        command["policy_decision"]["evaluated_at"] = "2026-10-03T12:01:00Z"
        self._denied(command, reason="IDEMPOTENCY_CONFLICT")

    def test_replay_changed_registered_nonce_conflicts(self):
        self._posted()
        authority = replace(self.authority, nonce=secrets.token_urlsafe(24))
        self._denied(self._signed_command(authority=authority), authority=authority)

    def test_replay_tampered_post_receipt_is_denied(self):
        self._posted()
        receipt = self._post_receipts()
        receipt.receipt_payload = dict(receipt.receipt_payload, move_id=self.move.id + 1000000)
        self._denied()

    def test_replay_tampered_nonce_consumption_is_denied(self):
        result = self._posted()
        self._ledger().browse(result["receipt"]["approval_ledger_id"]).write({
            "state": "reserved", "consumed_at": False,
        })
        self._denied()

    def test_replay_financial_state_tampering_is_denied(self):
        self._posted()
        self.move.partner_bank_id = self.other_bank
        self._denied()

    def test_no_original_draft_receipt_cannot_be_adopted(self):
        self.draft_receipt.unlink()
        self._denied()

    def test_tampered_original_draft_receipt_cannot_authorize_post(self):
        self.draft_receipt.action_sha256 = "sha256:" + "e" * 64
        self._denied()

    def test_already_posted_bill_without_post_receipt_is_not_adopted(self):
        self.move.action_post()
        self._denied()

    def test_proposed_target_cannot_select_another_bill(self):
        self._denied(self._signed_command(action_changes={"target_move_id": self.move.id + 1000000}))

    def test_trusted_workflow_target_must_equal_original_draft(self):
        self._denied(workflow=replace(self.workflow, target_move_id=self.move.id + 1000000))

    def test_registered_action_cannot_redirect_beneficiary(self):
        self._denied(self._signed_command(action_changes={"recipient_bank_ref": self.other_bank.acc_number}),
                     reason="TARGET_BILL_MISMATCH")

    def test_registered_action_cannot_change_financial_amount(self):
        command = self._signed_command(action_changes={
            "amount": "124.50", "lines": [{
                "item_code": self.product.default_code, "quantity": "1.00", "unit_price": "124.50",
            }],
        })
        self._denied(command, reason="TARGET_BILL_MISMATCH")

    def test_mutated_draft_bank_is_rejected_without_repair(self):
        self.move.partner_bank_id = self.other_bank
        result = self._denied(reason="PERSISTED_STATE_MISMATCH")
        self.assertNotIn("TARGET_BILL_MISMATCH", result["reason_codes"])
        self.assertEqual(self.move.partner_bank_id, self.other_bank)

    def test_bank_trust_revocation_blocks_post(self):
        self.bank.allow_out_payment = False
        self._denied()
        self.assertEqual(self.move.partner_bank_id, self.bank)

    def test_closed_accounting_period_blocks_without_date_rewrite(self):
        self.company.fiscalyear_lock_date = date(2026, 9, 30)
        self._denied(reason="ACCOUNTING_PERIOD_CLOSED")
        self.assertEqual(self.move.date, date(2026, 9, 30))

    def test_purchase_price_drift_blocks_post(self):
        self.purchase_line.price_unit = 126.50
        self._denied()

    def test_purchase_state_drift_blocks_post(self):
        self.purchase.button_cancel()
        self._denied()

    def test_archived_executor_identity_blocks_post(self):
        self.executor_user.active = False
        self._denied()

    def test_new_financial_permission_blocks_post(self):
        self.executor_user.write({"group_ids": [Command.link(self.env.ref("account.group_account_invoice").id)]})
        self._denied()

    def test_new_vendor_guard_permission_blocks_post(self):
        self.env["ir.model.access"].create({
            "name": "TCC synthetic vendor guard drift",
            "model_id": self.env["ir.model"]._get_id("ap.security.vendor.guard"),
            "group_id": self.env.ref("ap_security_executor.group_executor").id,
            "perm_read": True, "perm_write": False,
            "perm_create": False, "perm_unlink": False,
        })
        self._denied(reason="EXECUTOR_IDENTITY_INVALID")

    def test_global_financial_default_blocks_post_without_repair(self):
        defaults = self.env["ir.default"].sudo()
        defaults.set("account.move", "auto_post", "at_date", company_id=self.company.id)
        count = defaults.search_count([])
        self._denied()
        self.assertEqual(defaults.search_count([]), count)

    def test_wrong_runtime_mac_key_never_posts(self):
        wrong = ApprovalKey(company_id=self.company.id, key_id=self.key.key_id, material=secrets.token_bytes(32))
        self._denied(key=wrong, reason="SIGNATURE_INVALID")

    def test_expired_approval_never_reserves_or_posts(self):
        self._denied(clock=lambda: datetime(2026, 10, 3, 12, 10, tzinfo=timezone.utc), reason="EXPIRED")

    def test_future_approval_never_reserves_or_posts(self):
        self._denied(clock=lambda: datetime(2026, 10, 3, 11, 59, tzinfo=timezone.utc), reason="NOT_YET_VALID")

    def test_expiry_while_reserving_nonce_is_rechecked_before_native_post(self):
        seen_reserved = []

        def reservation_sensitive_clock():
            reserved = bool(self._ledger().search_count([("state", "=", "reserved")]))
            if reserved:
                seen_reserved.append(True)
                return datetime(2026, 10, 3, 12, 10, tzinfo=timezone.utc)
            return self.now

        self._denied(clock=reservation_sensitive_clock, reason="EXPIRED")
        self.assertTrue(seen_reserved, "POST never re-read its clock after nonce reservation.")

    def test_consumed_nonce_from_another_operation_is_not_reused(self):
        with approval_transaction(
            self.env, command=self.command, trusted_action=self.registered_action,
            authority=self.authority, key=self.key, now=self.now,
        ):
            pass
        self._denied(reason="NONCE_REUSED")

    def test_non_administrator_cannot_call_private_post_helper(self):
        before = self._state_hash()
        restricted = api.Environment(self.env.cr, self.executor_user.id, {}, su=False)
        with unittest.TestCase.assertRaises(self, AccessError):
            self._execute(env=restricted)
        self.assertEqual(self._state_hash(), before)

    def test_public_executor_stays_closed_with_a_valid_registered_mac(self):
        before = self._state_hash()
        result = self.env["ap.security.executor"].with_user(self.executor_user).execute(self.command)
        self.assertFalse(result["effect_applied"])
        self.assertEqual(result["decision"], "DENY")
        self.assertEqual(result["executor_status"], "SCAFFOLD_NOT_READY")
        self.assertEqual(result["reason_codes"], ["DEPENDENCY_UNAVAILABLE"])
        self.assertEqual(self._state_hash(), before)

    def test_hostile_context_cannot_change_company_or_skip_post_validation(self):
        hostile = self.env(context={
            "allowed_company_ids": [self.other_company.id], "force_company": self.other_company.id,
            "default_partner_id": self.other_vendor.id, "default_partner_bank_id": self.other_bank.id,
            "check_move_validity": False, "skip_invoice_sync": True,
            "skip_account_deprecation_check": True, "move_reverse_cancel": True,
            "tracking_disable": False, "lang": "invalid_LANG", "tz": "invalid_TZ",
        })
        self._posted(env=hostile)
        self.assertEqual(self.move.company_id, self.company)
        self.assertEqual(self.move.partner_bank_id, self.bank)

    def test_fault_after_native_post_rolls_back_effect_nonce_and_receipt(self):
        before = self._state_hash()
        observed = []

        def fail_after_post(move):
            observed.append(move.state)
            raise RuntimeError("TCC-SYNTHETIC-POST-FAULT")

        with patch.object(post_kernel, "_after_post", side_effect=fail_after_post):
            # Never use TransactionCase.assertRaises: its own savepoint could
            # conceal a missing rollback in the private helper.
            with unittest.TestCase.assertRaises(self, RuntimeError):
                self._execute()
        self.assertEqual(observed, ["posted"])
        self.assertEqual(self._state_hash(), before)
        self._posted()

    def test_fault_after_post_receipt_rolls_back_then_retry_works(self):
        before = self._state_hash()
        observed = []

        def fail_after_receipt(receipt):
            observed.append(receipt.executor_mode)
            raise RuntimeError("TCC-SYNTHETIC-RECEIPT-FAULT")

        with patch.object(post_kernel, "_after_post_receipt", side_effect=fail_after_receipt):
            with unittest.TestCase.assertRaises(self, RuntimeError):
                self._execute()
        self.assertEqual(observed, ["POST_APPROVED"])
        self.assertEqual(self._state_hash(), before)
        self._posted()

    def test_fault_after_nonce_consumption_rolls_back_native_post_then_retry_works(self):
        before = self._state_hash()
        observed = []

        def fail_after_consumption(record):
            observed.append(record.state)
            raise RuntimeError("TCC-SYNTHETIC-NONCE-FAULT")

        with patch.object(approval_kernel, "_after_nonce_consume", side_effect=fail_after_consumption):
            with unittest.TestCase.assertRaises(self, RuntimeError):
                self._execute()
        self.assertEqual(observed, ["consumed"])
        self.assertEqual(self._state_hash(), before)
        self._posted()

    def test_command_is_not_mutated_or_copied_into_persistent_ledgers(self):
        before = hashlib.sha256(_bytes(self.command)).hexdigest()
        result = self._posted()
        self.assertEqual(hashlib.sha256(_bytes(self.command)).hexdigest(), before)
        receipt = self._post_receipts()
        self.assertFalse({"signature", "nonce", "material", "token", "approval", "command"} & set(receipt._fields))
        projection = _bytes(receipt.receipt_payload)
        self.assertFalse(self.authority.nonce.encode("utf-8") in projection)
        self.assertFalse(self.command["approval"]["signature"].encode("utf-8") in projection)
        self.assertEqual(result["receipt"], receipt.receipt_payload)

    def test_fault_preserves_existing_rank_callback_and_data_object(self):
        original = self.env.cr.postcommit
        data = original.data.setdefault("account.res.partner.increase_rank.supplier_rank", defaultdict(int))
        data[self.vendor.id] += 7
        observed = []

        def unrelated_callback():
            observed.append("existing")

        original.add(unrelated_callback)
        before = self._state_hash()
        before_data = hashlib.sha256(_bytes(data)).hexdigest()
        before_callbacks = tuple(original._funcs)
        with patch.object(post_kernel, "_after_post", side_effect=RuntimeError("TCC-SYNTHETIC-HOOK-FAULT")):
            with unittest.TestCase.assertRaises(self, RuntimeError):
                self._execute()
        self.assertIs(self.env.cr.postcommit, original)
        self.assertIs(original.data["account.res.partner.increase_rank.supplier_rank"], data)
        self.assertEqual(hashlib.sha256(_bytes(data)).hexdigest(), before_data)
        self.assertEqual(tuple(original._funcs), before_callbacks)
        self.assertFalse(observed, "Private POST executed a pre-existing deferred callback.")
        self.assertEqual(self._state_hash(), before)

    def test_non_rank_deferred_effect_is_rejected_and_rolled_back(self):
        before = self._state_hash()
        original = self.env.cr.postcommit
        observed = []

        def register_unexpected_effect(move):
            move.env.cr.postcommit.add(lambda: observed.append("unexpected"))
            move.env.cr.postcommit.data["tcc.synthetic.unexpected.effect"] = {"count": 1}

        with patch.object(post_kernel, "_after_post", side_effect=register_unexpected_effect):
            result = self._execute()
        self.assertEqual(result.get("status"), "DENIED")
        self.assertIs(result.get("effect_applied"), False)
        self.assertTrue(result.get("reason_codes"))
        self.assertIs(self.env.cr.postcommit, original)
        self.assertFalse(observed)
        self.assertEqual(self._state_hash(), before)

    def test_success_preserves_existing_rank_callback_and_data_object(self):
        original = self.env.cr.postcommit
        data = original.data.setdefault("account.res.partner.increase_rank.supplier_rank", defaultdict(int))
        data[self.vendor.id] += 7
        original.add(lambda: None)
        before_data = hashlib.sha256(_bytes(data)).hexdigest()
        callbacks_before = tuple(original._funcs)
        self._posted()
        self.assertIs(self.env.cr.postcommit, original)
        self.assertIs(original.data["account.res.partner.increase_rank.supplier_rank"], data)
        self.assertEqual(hashlib.sha256(_bytes(data)).hexdigest(), before_data)
        self.assertEqual(tuple(original._funcs)[:-1], callbacks_before)
        self.assertEqual(len(original), len(callbacks_before) + 1)

    def test_hash_secured_journal_is_denied_before_native_post(self):
        self.journal.restrict_mode_hash_table = True
        self._denied(reason="UNSUPPORTED_POST_STATE")

    def test_analytic_distribution_is_denied_before_creating_analytic_entries(self):
        project_plan_id = int(self.env["ir.config_parameter"].sudo().get_param("analytic.project_plan"))
        account = self.env["account.analytic.account"].create({
            "name": "TCC C1-08 ANALYTIC ACCOUNT - SEM VALOR FISCAL",
            "company_id": self.company.id, "plan_id": project_plan_id,
        })
        self.move.invoice_line_ids.analytic_distribution = {str(account.id): 100.0}
        self._denied(reason="UNSUPPORTED_POST_STATE")

    def test_imported_line_state_is_denied_before_native_post(self):
        self.move.invoice_line_ids.is_imported = True
        self._denied(reason="UNSUPPORTED_POST_STATE")

    def test_pending_matching_number_is_denied_before_reconciliation(self):
        payable = self.move.line_ids.filtered(lambda line: line.display_type == "payment_term")
        payable.matching_number = "ITCC-C108"
        self._denied(reason="UNSUPPORTED_POST_STATE")

    def test_partial_deductibility_is_denied_without_adding_user_permissions(self):
        groups_before = tuple(sorted(self.env.user.all_group_ids.ids))
        self.move.invoice_line_ids.deductible_amount = 50.0
        self._denied()
        self.assertEqual(tuple(sorted(self.env.user.all_group_ids.ids)), groups_before)

    def test_reversal_link_is_denied_before_reconciling_other_posted_bill(self):
        other = self.move.copy(default={
            "ref": "TCC-C108-OTHER-POSTED-SEM-VALOR-FISCAL",
            "invoice_date": self.move.invoice_date, "date": self.move.date,
        })
        other.action_post()
        self.move.reversed_entry_id = other
        self._denied(reason="UNSUPPORTED_POST_STATE")

    def test_non_rank_callback_after_nonce_consumption_is_rejected(self):
        before = self._state_hash()
        original = self.env.cr.postcommit

        def register_after_consumption(record):
            record.env.cr.postcommit.add(lambda: None)
            record.env.cr.postcommit.data["tcc.synthetic.late.effect"] = {"count": 1}

        with patch.object(approval_kernel, "_after_nonce_consume", side_effect=register_after_consumption):
            result = self._execute()
        self.assertEqual(result.get("status"), "DENIED")
        self.assertIs(result.get("effect_applied"), False)
        self.assertIn("UNEXPECTED_POST_EFFECT", result.get("reason_codes", []))
        self.assertIs(self.env.cr.postcommit, original)
        self.assertEqual(self._state_hash(), before)

    def test_unavailable_postcommit_guard_does_not_abort_unrelated_callbacks(self):
        # Failure-only lifecycle seam: no committed accounting or authorization
        # is mocked, and no real postcommit queue or second cursor is executed.
        observed = []
        pending = Callbacks()
        pending.add(lambda: observed.append("native"))
        pending.data["account.res.partner.increase_rank.supplier_rank"] = {self.vendor.id: 1}
        registry = SimpleNamespace(cursor=Mock(side_effect=OperationalError("TCC-SYNTHETIC-CURSOR-FAULT")))
        unrelated = Callbacks()
        unrelated.add(lambda: post_kernel._run_committed_rank(
            registry, pending, {}, self.company.id, "sha256:" + "f" * 64,
        ))
        unrelated.add(lambda: observed.append("subsequent"))
        before = self._state_hash()
        unrelated.run()
        self.assertEqual(observed, ["subsequent"])
        self.assertEqual(len(pending), 0)
        self.assertFalse(pending.data)
        registry.cursor.assert_called_once_with()
        self.assertEqual(self._state_hash(), before)
