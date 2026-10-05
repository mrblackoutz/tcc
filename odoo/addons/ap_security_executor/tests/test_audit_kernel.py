# SPDX-License-Identifier: LGPL-3.0-or-later
"""Real disposable C1-09 operational audit and rollback evidence.

All accounting inputs are synthetic and without fiscal value. Runtime MACs
are real; only fault seams are patched. These tests do not commit callbacks,
attest independent-cursor concurrency, or open the public executor.
"""

import copy
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import secrets
import unittest
from unittest.mock import patch

from psycopg2.errors import SerializationFailure

from odoo import Command, api
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged

from .. import approval_kernel, audit_kernel, post_kernel
from ..approval import ApprovalAuthority, ApprovalKey
from ..document_contracts import SourceDocument
from ..audit_contracts import TrustedAuditContext, audit_digest
from ..draft_contracts import TrustedDraftWorkflow, bill_idempotency_key
from ..draft_kernel import create_draft_atomic
from ..identity import provision_executor_identity
from ..post_contracts import TrustedPostWorkflow
from .test_executor import _action_hash, _command
from .test_post_kernel import TestPostKernel, _bytes


def _synthetic_pdf(text="TCC C1-09 DOCUMENTO SINTETICO SEM VALOR FISCAL"):
    """Deterministic PDF bytes; no gateway imports, files or real documents."""
    text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = ("BT /F1 10 Tf 40 750 Td (" + text + ") Tj ET\n").encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream",
    ]
    raw = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(raw))
        raw.extend(str(number).encode("ascii") + b" 0 obj\n" + body + b"\nendobj\n")
    xref = len(raw)
    raw.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        raw.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    raw.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return bytes(raw)


class AuditFixtureMixin:
    # Reuse only hash/projection/signing helpers, not the C1-08 test class or
    # its tags/fixtures/test methods. Every test below has its own real scope.
    _signed_command = TestPostKernel._signed_command
    _ledger = TestPostKernel._ledger
    _post_receipts = TestPostKernel._post_receipts
    _effects = TestPostKernel._effects
    _state_hash = TestPostKernel._state_hash

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.document_raw = _synthetic_pdf()
        cls.document = SourceDocument(raw=cls.document_raw, mimetype="application/pdf")
        cls.env["ir.config_parameter"].sudo().set_param("ir_attachment.location", "db")
        cls.company = cls.env["res.company"].create({
            "name": "TCC C1-09 COMPANY - SEM VALOR FISCAL",
        })
        cls.env = cls.env(context={**cls.env.context, "allowed_company_ids": [cls.company.id]})
        cls.env["account.chart.template"].try_loading(
            "generic_coa", company=cls.company, install_demo=False,
        )
        cls.other_company = cls.env["res.company"].create({
            "name": "TCC C1-09 OTHER COMPANY - SEM VALOR FISCAL",
        })
        cls.executor_user = provision_executor_identity(
            cls.env, login="tcc-c109-audit-kernel", company=cls.company,
        )
        cls.vendor = cls.env["res.partner"].create({
            "name": "TCC C1-09 SUPPLIER - SEM VALOR FISCAL", "ref": "TCC-C109-VENDOR",
            "is_company": True, "company_id": cls.company.id,
            "supplier_rank": 1, "autopost_bills": "never",
        })
        cls.other_vendor = cls.env["res.partner"].create({
            "name": "TCC C1-09 OTHER SUPPLIER - SEM VALOR FISCAL",
            "ref": "TCC-C109-OTHER-VENDOR", "is_company": True,
            "company_id": cls.company.id, "supplier_rank": 1, "autopost_bills": "never",
        })
        cls.bank = cls.env["res.partner.bank"].create({
            "acc_number": "TCC-C109-SYNTHETIC-BANK", "partner_id": cls.vendor.id,
            "company_id": cls.company.id, "allow_out_payment": True,
        })
        cls.other_bank = cls.env["res.partner.bank"].create({
            "acc_number": "TCC-C109-OTHER-SYNTHETIC-BANK",
            "partner_id": cls.other_vendor.id, "company_id": cls.company.id,
            "allow_out_payment": True,
        })
        cls.product = cls.env["product.product"].create({
            "name": "TCC C1-09 SERVICE - SEM VALOR FISCAL", "default_code": "TCC-C109-SERVICE",
            "type": "service", "purchase_ok": True, "sale_ok": False,
            "purchase_method": "purchase", "supplier_taxes_id": [Command.clear()],
        })
        cls.purchase = cls.env["purchase.order"].create({
            "name": "TCC-C109-PO-CONFIRMED", "partner_id": cls.vendor.id,
            "company_id": cls.company.id, "currency_id": cls.company.currency_id.id,
            "order_line": [Command.create({
                "name": "TRUSTED C109 PO LINE - SEM VALOR FISCAL",
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
            raise AssertionError("Synthetic audit accounting fixtures are incomplete.")
        cls.draft_workflow = TrustedDraftWorkflow(
            company_id=cls.company.id, executor_user_id=cls.executor_user.id,
            purchase_order_id=cls.purchase.id, vendor_id=cls.vendor.id,
            journal_id=cls.journal.id, expense_account_id=cls.expense.id,
            purchase_line_ids=tuple(cls.purchase_line.ids), allowed_bank_ids=(cls.bank.id,),
            scenario_id="TCC-SCN-001", document_sha256=hashlib.sha256(cls.document_raw).hexdigest(),
            policy_version="policy-v1.0.0", phase="DRAFT_INTAKE",
            invoice_date_min="2026-09-01", invoice_date_max="2026-09-30",
            quantity_scale=2, monetary_tolerance="0.00",
        )

    def setUp(self):
        super().setUp()
        self.now = datetime(2026, 10, 3, 12, 5, tzinfo=timezone.utc)
        self.audit = TrustedAuditContext(
            run_id="TCC-C109-RUN", attempt_id=secrets.token_hex(16),
            code_commit="a" * 40, code_sha256="sha256:" + "b" * 64,
            configuration_sha256="sha256:" + "c" * 64,
        )
        self.draft_command = _command()
        self.draft_command["action"].update({
            "document_sha256": self.draft_workflow.document_sha256,
            "vendor_ref": self.vendor.ref, "purchase_order_ref": self.purchase.name,
            "currency": self.company.currency_id.name, "recipient_bank_ref": self.bank.acc_number,
            "document_ref": "TCC-C109-NF-SEM-VALOR-FISCAL",
            "lines": [{"item_code": self.product.default_code, "quantity": "1.00", "unit_price": "125.50"}],
        })
        self.draft_command["policy_decision"]["proposed_action_hash"] = _action_hash(self.draft_command["action"])
        self.idempotency_key = bill_idempotency_key(
            document_sha256=self.draft_workflow.document_sha256,
            company_id=self.company.id, vendor_id=self.vendor.id,
            purchase_order_id=self.purchase.id, purchase_line_ids=tuple(self.purchase_line.ids),
        )
        self.draft_command["idempotency_key"] = self.idempotency_key

    def _events(self):
        return self.env["ap.security.audit.event"].sudo().search([
            ("company_id", "=", self.company.id),
        ], order="id")

    def _event(self, result):
        metadata = result.get("audit_event")
        self.assertIs(result.get("audit_complete"), True)
        self.assertIsInstance(metadata, dict)
        self.assertIs(type(metadata.get("event_id")), int)
        self.assertRegex(metadata.get("event_sha256", ""), r"^sha256:[0-9a-f]{64}$")
        event = self.env["ap.security.audit.event"].sudo().browse(metadata["event_id"])
        self.assertTrue(event.exists())
        self.assertEqual(event.event_sha256, metadata["event_sha256"])
        self.assertEqual(event.event_sha256, audit_digest(event.event_payload))
        return event

    def _create(self, command=None, *, workflow=None, audit=None, env=None, document=None):
        return audit_kernel.create_draft_audited(
            self.env if env is None else env,
            command=self.draft_command if command is None else command,
            workflow=self.draft_workflow if workflow is None else workflow,
            audit=self.audit if audit is None else audit,
            document=self.document if document is None else document,
        )

    def _created(self, **changes):
        result = self._create(**changes)
        self.assertEqual(result.get("schema_version"), "draft-kernel-result/v1")
        self.assertEqual(result.get("status"), "CREATED", "Audited CREATE rejected a valid fixture.")
        self.assertIs(result.get("effect_applied"), True)
        event = self._event(result)
        self.assertEqual(event.status, "CREATED")
        self.assertEqual(event.executor_mode, "CREATE_DRAFT")
        self.assertEqual(event.receipt_id.id, result["receipt"]["receipt_id"])
        self.assertEqual(event.success_receipt_id, event.receipt_id)
        self.assertFalse(event.original_event_id)
        return result

    def _prepare_post(self, *, audited=True):
        result = self._created() if audited else create_draft_atomic(
            self.env, command=self.draft_command, workflow=self.draft_workflow,
        )
        if result.get("status") != "CREATED":
            raise AssertionError("Synthetic audit POST fixture could not create its original draft.")
        self.created_result = result
        self.move = self.env["account.move"].browse(result["receipt"]["move_id"])
        self.draft_receipt = self.env["ap.security.draft.receipt"].browse(result["receipt"]["receipt_id"])
        self.workflow = TrustedPostWorkflow(draft=self.draft_workflow, target_move_id=self.move.id)
        self.key = ApprovalKey(
            company_id=self.company.id, key_id="tcc-c109-key-v1", material=secrets.token_bytes(32),
        )
        self.authority = ApprovalAuthority(
            company_id=self.company.id, executor_user_id=self.executor_user.id,
            fixture_id="TCC-C109-APR-001", scenario_id="TCC-SCN-001",
            approver_ref="TCC-C109-SYNTHETIC-APPROVER", nonce=secrets.token_urlsafe(24),
            issued_at="2026-10-03T12:00:00Z", expires_at="2026-10-03T12:10:00Z",
            key_id=self.key.key_id,
        )
        self.registered_action = {
            **copy.deepcopy(self.draft_command["action"]), "action": "POST_VENDOR_BILL",
            "executor_mode": "POST_APPROVED", "target_move_id": self.move.id,
        }
        self.command = self._signed_command()
        self.audit = replace(self.audit, attempt_id=secrets.token_hex(16))

    def _post(self, command=None, *, workflow=None, authority=None, key=None,
              audit=None, env=None, clock=None, document=None):
        with patch.object(post_kernel, "_utc_now", side_effect=clock or (lambda: self.now)):
            return audit_kernel.post_bill_audited(
                self.env if env is None else env,
                command=self.command if command is None else command,
                workflow=self.workflow if workflow is None else workflow,
                authority=self.authority if authority is None else authority,
                key=self.key if key is None else key,
                audit=self.audit if audit is None else audit,
                document=self.document if document is None else document,
            )

    def _posted(self, **changes):
        result = self._post(**changes)
        self.assertEqual(result.get("schema_version"), "post-kernel-result/v1")
        self.assertEqual(result.get("status"), "POSTED", "Audited POST rejected a valid fixture.")
        self.assertIs(result.get("effect_applied"), True)
        self.move.invalidate_recordset()
        self.assertEqual(self.move.state, "posted")
        event = self._event(result)
        self.assertEqual(event.status, "POSTED")
        self.assertEqual(event.executor_mode, "POST_APPROVED")
        self.assertEqual(event.receipt_id.id, result["receipt"]["receipt_id"])
        self.assertEqual(event.success_receipt_id, event.receipt_id)
        self.assertFalse(event.original_event_id)
        ledger = self._ledger().browse(result["receipt"]["approval_ledger_id"])
        self.assertEqual(ledger.state, "consumed")
        return result

    def _denied(self, result, *, unavailable=False, reason=None):
        self.assertEqual(result.get("status"), "DENIED")
        self.assertIs(result.get("effect_applied"), False)
        self.assertIn(result.get("deny_class"), ("POLICY_RULE", "FAIL_CLOSED_UNAVAILABILITY"))
        self.assertTrue(result.get("reason_codes"))
        if reason:
            self.assertIn(reason, result["reason_codes"])
        if unavailable:
            self.assertEqual(result.get("deny_class"), "FAIL_CLOSED_UNAVAILABILITY")
            self.assertIs(result.get("audit_complete"), False)
            self.assertNotIn("audit_event", result)
        else:
            event = self._event(result)
            self.assertEqual(event.status, "DENIED")
            self.assertFalse(event.receipt_id or event.success_receipt_id or event.original_event_id)
        return result

    def _unavailable(self, operation, *, reason="AUDIT_UNAVAILABLE"):
        before = self._state_hash()
        events_before = len(self._events())
        result = self._denied(operation(), unavailable=True, reason=reason)
        self.assertEqual(self._state_hash(), before, "Unavailable audit leaked a financial effect.")
        self.assertEqual(len(self._events()), events_before, "Failed audit retained a partial event.")
        return result

@tagged("post_install", "-at_install", "c1_audit")
class TestAuditKernel(AuditFixtureMixin, TransactionCase):
    def test_create_records_real_receipt_and_canonical_event(self):
        payments_before = self.env["account.payment"].sudo().search_count([])
        result = self._created()
        move = self.env["account.move"].browse(result["receipt"]["move_id"])
        self.assertEqual(move.state, "draft")
        self.assertEqual(move.partner_bank_id, self.bank)
        self.assertEqual(move.amount_total, 125.50)
        self.assertEqual(len(self._events()), 1)
        self.assertEqual(self.env["account.payment"].sudo().search_count([]), payments_before)

    def test_create_replay_has_new_event_and_original_financial_receipt(self):
        first = self._created()
        before = self._state_hash(include_guard=False)
        replay = self._create(copy.deepcopy(self.draft_command), audit=replace(
            self.audit, attempt_id=secrets.token_hex(16),
        ))
        self.assertEqual(replay["status"], "REPLAY")
        self.assertIs(replay["effect_applied"], False)
        self.assertEqual(replay["receipt"], first["receipt"])
        event = self._event(replay)
        self.assertEqual(event.original_event_id.id, first["audit_event"]["event_id"])
        self.assertEqual(event.receipt_id.id, first["receipt"]["receipt_id"])
        self.assertFalse(event.success_receipt_id)
        self.assertEqual(self._state_hash(include_guard=False), before)
        self.assertEqual(len(self._events()), 2)

    def test_run_correlation_change_does_not_create_another_bill(self):
        first = self._created()
        replay = self._create(audit=replace(
            self.audit, run_id="TCC-C109-ANOTHER-RUN", attempt_id=secrets.token_hex(16),
        ))
        self.assertEqual(replay["status"], "REPLAY")
        self.assertEqual(replay["receipt"], first["receipt"])
        self.assertEqual(self._event(replay).run_id, "TCC-C109-ANOTHER-RUN")

    def test_unaudited_create_receipt_cannot_be_adopted_by_replay(self):
        raw = create_draft_atomic(self.env, command=self.draft_command, workflow=self.draft_workflow)
        self.assertEqual(raw.get("status"), "CREATED")
        self._unavailable(self._create)

    def test_corrupted_original_create_hash_blocks_replay(self):
        first = self._created()
        self.env.cr.execute(
            "UPDATE ap_security_audit_event SET event_sha256 = %s WHERE id = %s",
            ("sha256:" + "d" * 64, first["audit_event"]["event_id"]),
        )
        self.env["ap.security.audit.event"].invalidate_model()
        self._unavailable(self._create)

    def test_corrupted_original_payload_blocks_replay(self):
        first = self._created()
        self.env.cr.execute(
            "UPDATE ap_security_audit_event SET event_payload = %s::jsonb WHERE id = %s",
            ('{"schema_version":"TCC-C109-CORRUPT-SYNTHETIC"}', first["audit_event"]["event_id"]),
        )
        self.env["ap.security.audit.event"].invalidate_model()
        self._unavailable(self._create)

    def _replace_event_payload(self, event, payload):
        """Privileged corruption seam: never a supported audit mutation API."""
        self.env.cr.execute(
            "UPDATE ap_security_audit_event SET event_payload = %s::jsonb, event_sha256 = %s WHERE id = %s",
            (_bytes(payload).decode("utf-8"), audit_digest(payload), event.id),
        )
        self.env["ap.security.audit.event"].invalidate_model()

    def test_subject_list_with_recomputed_hash_is_rejected_by_closed_shape(self):
        original = self._created()
        event = self._event(original)
        corrupted = copy.deepcopy(event.event_payload)
        corrupted["subject"] = []
        self._replace_event_payload(event, corrupted)
        self._unavailable(self._create)

    def test_nested_status_policy_approval_corruption_with_recomputed_hash_is_finite(self):
        self._prepare_post()
        original = self._posted()
        event = self._event(original)
        original_payload = copy.deepcopy(event.event_payload)
        for section, field, value in (
            ("outcome", "status", []),
            ("received_policy", None, []),
            ("received_policy", "decision", []),
            ("approval", None, []),
            ("approval", "key_id", []),
            ("approval", "state", []),
            ("approval", "ledger_id", []),
        ):
            with self.subTest(section=section, field=field):
                corrupted = copy.deepcopy(original_payload)
                if field is None:
                    corrupted[section] = value
                else:
                    corrupted[section][field] = value
                self._replace_event_payload(event, corrupted)
                try:
                    self._unavailable(self._post)
                finally:
                    self._replace_event_payload(event, original_payload)

    def test_nested_reason_code_list_with_recomputed_hash_is_rejected(self):
        original = self._created()
        event = self._event(original)
        corrupted = copy.deepcopy(event.event_payload)
        corrupted["outcome"]["reason_codes"] = [["DRAFT_CONSISTENT"]]
        self._replace_event_payload(event, corrupted)
        self._unavailable(self._create)

    def test_business_denial_has_event_but_no_financial_effect(self):
        command = copy.deepcopy(self.draft_command)
        command["action"]["recipient_bank_ref"] = self.other_bank.acc_number
        command["policy_decision"]["proposed_action_hash"] = _action_hash(command["action"])
        before = self._state_hash()
        result = self._denied(self._create(command))
        self.assertEqual(result["deny_class"], "POLICY_RULE")
        outcome = self._event(result).event_payload["outcome"]
        self.assertEqual(outcome["before_sha256"], outcome["after_sha256"])
        self.assertIs(outcome["effect_applied"], False)
        self.assertEqual(self._state_hash(), before)
        self.assertEqual(len(self._events()), 1)

    def test_document_controlled_reference_is_not_persisted_in_audit(self):
        marker = "TCC-C109-ATTACKER-CONTROLLED-REFERENCE"
        command = copy.deepcopy(self.draft_command)
        command["action"]["document_ref"] = marker
        command["action"]["recipient_bank_ref"] = self.other_bank.acc_number
        command["policy_decision"]["proposed_action_hash"] = _action_hash(command["action"])
        result = self._denied(self._create(command))
        encoded = _bytes(self._event(result).event_payload)
        self.assertFalse(marker.encode("utf-8") in encoded)
        for value in (self.vendor.ref, self.purchase.name, self.bank.acc_number, self.other_bank.acc_number):
            self.assertFalse(value.encode("utf-8") in encoded)

    def test_audit_provenance_comes_from_trusted_context_not_client_context(self):
        hostile = self.env(context={
            "allowed_company_ids": [self.other_company.id], "force_company": self.other_company.id,
            "run_id": "TCC-C109-CLIENT-RUN", "code_commit": "f" * 40,
            "default_company_id": self.other_company.id, "default_status": "POSTED",
            "default_event_sha256": "sha256:" + "f" * 64,
        })
        result = self._created(env=hostile)
        event = self._event(result)
        self.assertEqual(event.company_id, self.company)
        self.assertEqual(event.executor_user_id, self.executor_user)
        self.assertEqual(event.run_id, self.audit.run_id)
        self.assertEqual(event.attempt_id, self.audit.attempt_id)
        self.assertEqual(event.event_payload["context"], {
            "run_id": self.audit.run_id, "attempt_id": self.audit.attempt_id,
            "code_commit": self.audit.code_commit, "code_sha256": self.audit.code_sha256,
            "configuration_sha256": self.audit.configuration_sha256,
        })
        self.assertFalse(b"TCC-C109-CLIENT-RUN" in _bytes(event.event_payload))

    def test_audit_orm_defaults_cannot_select_company_identity_status_or_provenance(self):
        defaults = self.env["ir.default"].sudo()
        for name, value in (
            ("company_id", self.other_company.id),
            ("executor_user_id", self.env.user.id),
            ("status", "POSTED"),
            ("run_id", "TCC-C109-UNTRUSTED-DEFAULT"),
            ("event_sha256", "sha256:" + "f" * 64),
        ):
            defaults.set("ap.security.audit.event", name, value)
        count = defaults.search_count([])
        result = self._created()
        event = self._event(result)
        self.assertEqual(event.company_id, self.company)
        self.assertEqual(event.executor_user_id, self.executor_user)
        self.assertEqual(event.status, "CREATED")
        self.assertEqual(event.run_id, self.audit.run_id)
        self.assertEqual(event.event_payload["context"]["code_commit"], self.audit.code_commit)
        self.assertEqual(defaults.search_count([]), count)
        self.assertFalse(b"TCC-C109-UNTRUSTED-DEFAULT" in _bytes(event.event_payload))

    def test_mapping_is_not_a_trusted_audit_registration(self):
        before = self._state_hash()
        with unittest.TestCase.assertRaises(self, ValidationError):
            self._create(audit={
                "run_id": self.audit.run_id, "attempt_id": self.audit.attempt_id,
                "code_commit": self.audit.code_commit, "code_sha256": self.audit.code_sha256,
                "configuration_sha256": self.audit.configuration_sha256,
            })
        self.assertEqual(self._state_hash(), before)
        self.assertFalse(self._events())

    def test_corrupted_frozen_audit_context_is_revalidated_before_financial_effect(self):
        corrupted = replace(self.audit)
        object.__setattr__(corrupted, "code_commit", "TCC-C109-INVALID-COMMIT")
        before = self._state_hash()
        with unittest.TestCase.assertRaises(self, ValidationError):
            self._create(audit=corrupted)
        self.assertEqual(self._state_hash(), before)
        self.assertFalse(self._events())

    def test_audit_insert_failure_rolls_back_create_receipt_and_lines(self):
        with patch.object(audit_kernel, "_append_event", side_effect=RuntimeError("TCC-C109-WRITER-FAULT")):
            self._unavailable(self._create)
        self._created()

    def test_failure_after_real_audit_insert_rolls_back_create_and_event(self):
        observed = []

        def fail_after_insert(event):
            observed.append(bool(event.exists()))
            raise RuntimeError("TCC-C109-AFTER-APPEND-FAULT")

        with patch.object(audit_kernel, "_after_audit_append", side_effect=fail_after_insert):
            self._unavailable(self._create)
        self.assertEqual(observed, [True])
        self._created()

    def test_post_records_real_accounting_nonce_and_original_draft_audit(self):
        self._prepare_post()
        effects_before = self._effects()
        self._posted()
        self.assertEqual(self._effects(), effects_before)
        self.assertEqual(len(self._events()), 2)
        self.assertEqual(len(self._post_receipts()), 1)

    def test_post_replay_retains_financial_receipt_without_second_nonce(self):
        self._prepare_post()
        first = self._posted()
        before = self._state_hash(include_guard=False)
        replay = self._post(audit=replace(self.audit, attempt_id=secrets.token_hex(16)))
        self.assertEqual(replay["status"], "REPLAY")
        self.assertIs(replay["effect_applied"], False)
        self.assertEqual(replay["receipt"], first["receipt"])
        event = self._event(replay)
        self.assertEqual(event.original_event_id.id, first["audit_event"]["event_id"])
        self.assertFalse(event.success_receipt_id)
        self.assertEqual(self._state_hash(include_guard=False), before)
        self.assertEqual(len(self._events()), 3)

    def test_expired_identical_post_replay_remains_no_new_authorization(self):
        self._prepare_post()
        first = self._posted()
        before = self._state_hash(include_guard=False)
        replay = self._post(clock=lambda: datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(replay["status"], "REPLAY")
        self.assertEqual(replay["receipt"], first["receipt"])
        self._event(replay)
        self.assertEqual(self._state_hash(include_guard=False), before)

    def test_post_requires_audited_original_draft(self):
        self._prepare_post(audited=False)
        self._unavailable(self._post)

    def test_post_requires_uncorrupted_original_draft_audit(self):
        self._prepare_post()
        self.env.cr.execute(
            "UPDATE ap_security_audit_event SET event_sha256 = %s WHERE id = %s",
            ("sha256:" + "d" * 64, self.created_result["audit_event"]["event_id"]),
        )
        self.env["ap.security.audit.event"].invalidate_model()
        self._unavailable(self._post)

    def test_post_replay_requires_intact_original_post_audit(self):
        self._prepare_post()
        first = self._posted()
        self.env.cr.execute(
            "UPDATE ap_security_audit_event SET event_sha256 = %s WHERE id = %s",
            ("sha256:" + "d" * 64, first["audit_event"]["event_id"]),
        )
        self.env["ap.security.audit.event"].invalidate_model()
        self._unavailable(self._post)

    def test_invalid_post_mac_logs_denial_without_posting(self):
        self._prepare_post()
        before = self._state_hash()
        wrong = ApprovalKey(company_id=self.company.id, key_id=self.key.key_id, material=secrets.token_bytes(32))
        self._denied(self._post(key=wrong), reason="SIGNATURE_INVALID")
        self.assertEqual(self._state_hash(), before)
        self.assertEqual(len(self._events()), 2)

    def test_altered_post_bank_is_business_denial_not_audit_unavailability(self):
        self._prepare_post()
        before = self._state_hash()
        command = self._signed_command(action_changes={"recipient_bank_ref": self.other_bank.acc_number})
        result = self._denied(self._post(command))
        self.assertEqual(result["deny_class"], "POLICY_RULE")
        self.assertNotIn("AUDIT_UNAVAILABLE", result["reason_codes"])
        self.assertEqual(self._state_hash(), before)
        self.assertEqual(len(self._events()), 2)

    def test_altered_post_amount_is_business_denial_not_audit_unavailability(self):
        self._prepare_post()
        before = self._state_hash()
        command = self._signed_command(action_changes={
            "amount": "124.50", "lines": [{
                "item_code": self.product.default_code, "quantity": "1.00", "unit_price": "124.50",
            }],
        })
        result = self._denied(self._post(command))
        self.assertEqual(result["deny_class"], "POLICY_RULE")
        self.assertNotIn("AUDIT_UNAVAILABLE", result["reason_codes"])
        self.assertEqual(self._state_hash(), before)
        self.assertEqual(len(self._events()), 2)

    def test_expired_approval_logs_denial_without_reserving_nonce(self):
        self._prepare_post()
        before = self._state_hash()
        self._denied(self._post(clock=lambda: datetime(2026, 10, 3, 12, 10, tzinfo=timezone.utc)), reason="EXPIRED")
        self.assertEqual(self._state_hash(), before)
        self.assertFalse(self._ledger().search_count([("company_id", "=", self.company.id)]))

    def test_runtime_key_signature_nonce_and_bank_text_never_enter_audit(self):
        self._prepare_post()
        digest = hashlib.sha256(_bytes(self.command)).hexdigest()
        first = self._posted()
        encoded = _bytes(self._event(first).event_payload)
        for value in (
            self.authority.nonce, self.command["approval"]["signature"],
            self.key.material.hex(), self.bank.acc_number, self.vendor.ref,
            self.purchase.name, self.draft_command["action"]["document_ref"],
        ):
            self.assertFalse(value.encode("utf-8") in encoded)
        self.assertEqual(hashlib.sha256(_bytes(self.command)).hexdigest(), digest)

    def test_post_audit_insert_failure_rolls_back_post_nonce_receipt_and_callback(self):
        self._prepare_post()
        with patch.object(audit_kernel, "_append_event", side_effect=RuntimeError("TCC-C109-WRITER-FAULT")):
            self._unavailable(self._post)
        self._posted()

    def test_post_after_real_audit_insert_failure_removes_event_and_accounting(self):
        self._prepare_post()
        observed = []

        def fail_after_insert(event):
            self.move.invalidate_recordset()
            observed.append((bool(event.exists()), self.move.state))
            raise RuntimeError("TCC-C109-AFTER-APPEND-FAULT")

        with patch.object(audit_kernel, "_after_audit_append", side_effect=fail_after_insert):
            self._unavailable(self._post)
        self.assertEqual(observed, [(True, "posted")])
        self._posted()

    def test_completion_fault_after_real_create_rolls_back_event_and_financial_receipt(self):
        observed = []

        def fail_completion(result, event):
            observed.append((result["status"], bool(event.exists())))
            raise RuntimeError("TCC-C109-COMPLETION-FAULT")

        with patch.object(audit_kernel, "_complete", side_effect=fail_completion):
            self._unavailable(self._create)
        self.assertEqual(observed, [("CREATED", True)])
        self._created()

    def test_completion_fault_after_real_post_rolls_back_nonce_event_receipt_callback(self):
        self._prepare_post()
        observed = []

        def fail_completion(result, event):
            self.move.invalidate_recordset()
            observed.append((result["status"], bool(event.exists()), self.move.state))
            raise RuntimeError("TCC-C109-POST-COMPLETION-FAULT")

        with patch.object(audit_kernel, "_complete", side_effect=fail_completion):
            self._unavailable(self._post)
        self.assertEqual(observed, [("POSTED", True, "posted")])
        self._posted()

    def test_replay_event_failure_preserves_original_success_without_partial_replay(self):
        self._prepare_post()
        self._posted()
        with patch.object(audit_kernel, "_append_event", side_effect=RuntimeError("TCC-C109-REPLAY-FAULT")):
            self._unavailable(self._post)

    def test_financial_wrapper_failure_rolls_back_create_then_logs_safe_denial(self):
        before = self._state_hash()
        observed = []

        def fail_after_finance(result):
            observed.append(result.get("status"))
            raise RuntimeError("TCC-C109-PRIVATE-EXCEPTION-NOT-FOR-AUDIT")

        with patch.object(audit_kernel, "_after_financial_kernel", side_effect=fail_after_finance):
            result = self._denied(self._create(), reason="KERNEL_UNAVAILABLE")
        self.assertEqual(observed, ["CREATED"])
        self.assertEqual(result["deny_class"], "FAIL_CLOSED_UNAVAILABILITY")
        self.assertEqual(self._state_hash(), before)
        self.assertFalse(b"TCC-C109-PRIVATE-EXCEPTION-NOT-FOR-AUDIT" in _bytes(self._event(result).event_payload))

    def test_financial_wrapper_failure_rolls_back_post_then_logs_safe_denial(self):
        self._prepare_post()
        before = self._state_hash()
        observed = []

        def fail_after_finance(result):
            observed.append(result.get("status"))
            raise RuntimeError("TCC-C109-POST-WRAPPER-FAULT")

        with patch.object(audit_kernel, "_after_financial_kernel", side_effect=fail_after_finance):
            self._denied(self._post(), reason="KERNEL_UNAVAILABLE")
        self.assertEqual(observed, ["POSTED"])
        self.assertEqual(self._state_hash(), before)
        self._posted()

    def test_native_fault_after_post_is_safely_classified_and_audited_after_rollback(self):
        self._prepare_post()
        before = self._state_hash()
        with patch.object(post_kernel, "_after_post", side_effect=RuntimeError("TCC-C109-NATIVE-FAULT")):
            self._denied(self._post(), reason="KERNEL_UNAVAILABLE")
        self.assertEqual(self._state_hash(), before)
        self._posted()

    def test_rolled_back_native_method_trace_is_explicitly_incomplete_not_fabricated(self):
        self._prepare_post()
        before = self._state_hash()
        observed = []

        def fail_after_post(move):
            observed.append(move.state)
            raise RuntimeError("TCC-C109-TRACE-FAULT")

        with patch.object(post_kernel, "_after_post", side_effect=fail_after_post):
            result = self._denied(self._post(), reason="KERNEL_UNAVAILABLE")
        payload = self._event(result).event_payload
        self.assertEqual(observed, ["posted"])
        self.assertEqual(payload["outcome"]["financial_methods"], [])
        self.assertEqual(payload["provenance"]["method_trace"], "SUCCESSFUL_EFFECT_METHODS_ONLY")
        self.assertIs(payload["provenance"]["attempted_method_trace_complete"], False)
        self.assertEqual(self._state_hash(), before)

    def test_native_fault_after_nonce_consumption_is_safely_audited_after_rollback(self):
        self._prepare_post()
        before = self._state_hash()
        with patch.object(approval_kernel, "_after_nonce_consume", side_effect=RuntimeError("TCC-C109-NONCE-FAULT")):
            self._denied(self._post(), reason="KERNEL_UNAVAILABLE")
        self.assertEqual(self._state_hash(), before)
        self._posted()

    def test_post_serialization_failure_propagates_for_integral_retry(self):
        self._prepare_post()
        before = self._state_hash()
        events_before = len(self._events())
        with patch.object(post_kernel, "_after_post", side_effect=SerializationFailure("TCC-C109-SERIALIZATION")):
            # TransactionCase.assertRaises creates its own savepoint and would
            # hide a missing rollback in the implementation under test.
            with unittest.TestCase.assertRaises(self, SerializationFailure):
                self._post()
        self.assertEqual(self._state_hash(), before)
        self.assertEqual(len(self._events()), events_before)
        self._posted()

    def test_audit_serialization_failure_propagates_without_partial_create_or_event(self):
        before = self._state_hash()
        with patch.object(audit_kernel, "_after_audit_append", side_effect=SerializationFailure("TCC-C109-AUDIT-SERIALIZATION")):
            with unittest.TestCase.assertRaises(self, SerializationFailure):
                self._create()
        self.assertEqual(self._state_hash(), before)
        self.assertFalse(self._events())
        self._created()

    def test_audit_failure_cannot_modify_preexisting_callback_objects_or_data(self):
        self._prepare_post()
        original = self.env.cr.postcommit
        observed = []
        data = original.data.setdefault("account.res.partner.increase_rank.supplier_rank", defaultdict(int))
        data[self.vendor.id] += 7
        original.add(lambda: observed.append("existing"))
        before_funcs = tuple(original._funcs)
        before_data = hashlib.sha256(_bytes(data)).hexdigest()
        with patch.object(audit_kernel, "_after_audit_append", side_effect=RuntimeError("TCC-C109-CALLBACK-FAULT")):
            self._unavailable(self._post)
        self.assertIs(self.env.cr.postcommit, original)
        self.assertIs(original.data["account.res.partner.increase_rank.supplier_rank"], data)
        self.assertEqual(tuple(original._funcs), before_funcs)
        self.assertEqual(hashlib.sha256(_bytes(data)).hexdigest(), before_data)
        self.assertFalse(observed)

    def test_success_preserves_preexisting_callbacks_and_adds_only_one_guard(self):
        self._prepare_post()
        original = self.env.cr.postcommit
        observed = []
        data = original.data.setdefault("account.res.partner.increase_rank.supplier_rank", defaultdict(int))
        data[self.vendor.id] += 7
        original.add(lambda: observed.append("existing"))
        before_funcs = tuple(original._funcs)
        before_data = hashlib.sha256(_bytes(data)).hexdigest()
        self._posted()
        self.assertIs(self.env.cr.postcommit, original)
        self.assertIs(original.data["account.res.partner.increase_rank.supplier_rank"], data)
        self.assertEqual(tuple(original._funcs)[:-1], before_funcs)
        self.assertEqual(len(original), len(before_funcs) + 1)
        self.assertEqual(hashlib.sha256(_bytes(data)).hexdigest(), before_data)
        self.assertFalse(observed)

    def test_denial_writer_failure_returns_explicit_incomplete_audit(self):
        command = copy.deepcopy(self.draft_command)
        command["action"]["recipient_bank_ref"] = self.other_bank.acc_number
        command["policy_decision"]["proposed_action_hash"] = _action_hash(command["action"])
        with patch.object(audit_kernel, "_append_event", side_effect=RuntimeError("TCC-C109-DENIAL-FAULT")):
            self._unavailable(lambda: self._create(command))

    def test_c1_user_has_no_audit_read_or_mutation_capabilities(self):
        first = self._created()
        restricted = api.Environment(self.env.cr, self.executor_user.id, {}, su=False)
        model = restricted["ap.security.audit.event"]
        for operation in ("read", "create", "write", "unlink"):
            self.assertFalse(model.browse().has_access(operation))
        event = model.browse(first["audit_event"]["event_id"])
        with unittest.TestCase.assertRaises(self, AccessError):
            event.read(["event_sha256"])

    def test_sudo_cannot_create_audit_event_through_orm(self):
        before = len(self._events())
        with unittest.TestCase.assertRaises(self, AccessError):
            self.env["ap.security.audit.event"].sudo().create({})
        self.assertEqual(len(self._events()), before)

    def test_sudo_cannot_rewrite_audit_event_through_orm(self):
        result = self._created()
        event = self._event(result)
        before = event.event_sha256
        with unittest.TestCase.assertRaises(self, AccessError):
            event.sudo().write({"event_sha256": "sha256:" + "f" * 64})
        event.invalidate_recordset()
        self.assertEqual(event.event_sha256, before)

    def test_sudo_cannot_delete_audit_event_through_orm(self):
        result = self._created()
        event = self._event(result)
        with unittest.TestCase.assertRaises(self, AccessError):
            event.sudo().unlink()
        self.assertTrue(event.exists())

    def test_non_admin_cannot_call_private_audited_financial_wrapper(self):
        before = self._state_hash()
        restricted = api.Environment(self.env.cr, self.executor_user.id, {}, su=False)
        with unittest.TestCase.assertRaises(self, AccessError):
            self._create(env=restricted)
        self.assertEqual(self._state_hash(), before)
        self.assertFalse(self._events())

    def test_public_executor_remains_closed_even_with_valid_audited_post_fixture(self):
        self._prepare_post()
        before = self._state_hash()
        events_before = len(self._events())
        result = self.env["ap.security.executor"].with_user(self.executor_user).execute(self.command)
        self.assertFalse(result["effect_applied"])
        self.assertEqual(result["decision"], "DENY")
        self.assertEqual(result["executor_status"], "SCAFFOLD_NOT_READY")
        self.assertEqual(self._state_hash(), before)
        self.assertEqual(len(self._events()), events_before)
