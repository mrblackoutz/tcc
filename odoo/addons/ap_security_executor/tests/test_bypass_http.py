# SPDX-License-Identifier: LGPL-3.0-or-later
"""C1-10 real JSON-2 bypass probes against meaningful synthetic targets.

The public executor is deliberately still closed. These checks attest today's
HTTP identity/ACL boundary, not an integrated financial endpoint, production
transactions, scientific runs or the absence of all personal user mutations.
"""

import base64
import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets

from odoo import Command
from odoo.tests import HttpCase, tagged

from .. import audit_kernel, workflow_registry
from ..approval import ApprovalAuthority, ApprovalKey
from ..audit_contracts import TrustedAuditContext
from ..document_contracts import SourceDocument
from ..draft_contracts import TrustedDraftWorkflow, bill_idempotency_key
from ..post_contracts import TrustedPostWorkflow
from ..workflow_contracts import WorkflowProvenance
from .test_audit_kernel import _synthetic_pdf
from .test_executor import _action_hash, _command
from .test_identity_http import (
    ExecutorHttpFixtureMixin, _USER_ERROR,
)
from .test_post_kernel import TestPostKernel


_NOT_FOUND = "werkzeug.exceptions.NotFound"
_LEDGER_FIELDS = {
    "ap.security.workflow.registration": [
        "id", "company_id", "executor_user_id", "registrar_user_id", "po_id", "vendor_id",
        "journal_id", "expense_account_id", "scenario_id", "document_sha256", "schema_version",
        "registration_sha256", "registration_payload", "create_uid", "write_uid",
    ],
    "ap.security.draft.receipt": [
        "id", "company_id", "executor_mode", "idempotency_key", "command_sha256",
        "action_sha256", "document_sha256", "po_id", "vendor_id", "purchase_line_ids",
        "move_id", "executor_user_id", "receipt_payload",
    ],
    "ap.security.po.guard": ["id", "company_id", "po_id", "revision"],
    "ap.security.vendor.guard": ["id", "company_id", "vendor_id", "revision"],
    "ap.security.approval.nonce": [
        "id", "company_id", "executor_user_id", "key_id", "fixture_id", "scenario_id",
        "approver_ref", "nonce_sha256", "action_sha256", "approval_sha256",
        "command_sha256", "state", "verified_at", "expires_at", "consumed_at",
    ],
    "ap.security.audit.event": [
        "id", "company_id", "executor_user_id", "run_id", "attempt_id", "executor_mode",
        "status", "receipt_id", "success_receipt_id", "original_event_id",
        "attachment_id", "event_sha256", "event_payload",
    ],
}


@tagged("post_install", "-at_install", "c1_bypass_http")
class TestExecutorBypassHttp(ExecutorHttpFixtureMixin, HttpCase):
    """Bearer keys stay in memory; only finite diagnostics leave this class."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("ir_attachment.location", "db")
        cls.vendor.autopost_bills = "never"
        cls.bank.allow_out_payment = True
        cls.bank_master = cls.env["res.bank"].create({
            "name": "TCC C1-10 SYNTHETIC BANK - SEM VALOR FISCAL",
            "bic": "TCCSYNTHETIC",
        })
        cls.bank.bank_id = cls.bank_master
        cls.bypass_purchase = cls.env["purchase.order"].create({
            "name": "TCC-C110-PO-AUDITED", "partner_id": cls.vendor.id,
            "company_id": cls.company.id, "currency_id": cls.company.currency_id.id,
            "order_line": [Command.create({
                "name": "TCC C1-10 AUDITED SERVICE - SEM VALOR FISCAL",
                "product_id": cls.product.id, "product_qty": 1.0,
                "product_uom_id": cls.product.uom_id.id, "price_unit": 125.50,
                "date_planned": "2026-09-30 12:00:00", "tax_ids": [Command.clear()],
            })],
        })
        cls.bypass_purchase.button_confirm()
        cls.bypass_line = cls.bypass_purchase.order_line.filtered(lambda line: not line.display_type)
        raw = _synthetic_pdf("TCC C1-10 DOCUMENTO SINTETICO SEM VALOR FISCAL")
        cls.source_document = SourceDocument(raw=raw, mimetype="application/pdf")
        document_sha256 = hashlib.sha256(raw).hexdigest()
        cls.draft_workflow = TrustedDraftWorkflow(
            company_id=cls.company.id, executor_user_id=cls.executor_user.id,
            purchase_order_id=cls.bypass_purchase.id, vendor_id=cls.vendor.id,
            journal_id=cls.draft_bill.journal_id.id,
            expense_account_id=cls.bill_line.account_id.id,
            purchase_line_ids=tuple(sorted(cls.bypass_line.ids)), allowed_bank_ids=(cls.bank.id,),
            scenario_id="TCC-SCN-001", document_sha256=document_sha256,
            policy_version="policy-v1.0.0", phase="DRAFT_INTAKE",
            invoice_date_min="2026-09-01", invoice_date_max="2026-09-30",
            quantity_scale=2, monetary_tolerance="0.00",
        )
        cls.idempotency_key = bill_idempotency_key(
            document_sha256=document_sha256, company_id=cls.company.id,
            vendor_id=cls.vendor.id, purchase_order_id=cls.bypass_purchase.id,
            purchase_line_ids=tuple(sorted(cls.bypass_line.ids)),
        )
        command = _command()
        command["action"].update({
            "document_sha256": document_sha256, "vendor_ref": cls.vendor.ref,
            "purchase_order_ref": cls.bypass_purchase.name,
            "document_ref": "TCC-C110-NF-AUDITED-SEM-VALOR-FISCAL",
            "currency": cls.company.currency_id.name, "recipient_bank_ref": cls.bank.acc_number,
            "lines": [{"item_code": cls.product.default_code, "quantity": "1.00", "unit_price": "125.50"}],
        })
        command["idempotency_key"] = cls.idempotency_key
        command["policy_decision"]["proposed_action_hash"] = _action_hash(command["action"])
        audit = TrustedAuditContext(
            run_id="TCC-C110-FIXTURE", attempt_id=secrets.token_hex(16),
            code_commit="a" * 40, code_sha256="sha256:" + "b" * 64,
            configuration_sha256="sha256:" + "c" * 64,
        )
        workflow_registry.register_draft_workflow(
            cls.env, workflow=cls.draft_workflow, document=cls.source_document,
            provenance=WorkflowProvenance(
                code_commit=audit.code_commit, code_sha256=audit.code_sha256,
                configuration_sha256=audit.configuration_sha256,
            ),
        )
        created = audit_kernel.create_draft_audited(
            cls.env, command=command, workflow=cls.draft_workflow,
            audit=audit, document=cls.source_document,
        )
        if created.get("status") != "CREATED" or not created.get("audit_complete"):
            raise AssertionError("Administrative audited CREATE fixture failed.")
        cls.audited_bill = cls.env["account.move"].browse(created["receipt"]["move_id"])
        cls.registered_action = {
            **copy.deepcopy(command["action"]), "action": "POST_VENDOR_BILL",
            "executor_mode": "POST_APPROVED", "target_move_id": cls.audited_bill.id,
        }
        now = datetime.now(timezone.utc).replace(microsecond=0)
        cls.key = ApprovalKey(
            company_id=cls.company.id, key_id="tcc-c110-fixture-key", material=secrets.token_bytes(32),
        )
        cls.authority = ApprovalAuthority(
            company_id=cls.company.id, executor_user_id=cls.executor_user.id,
            fixture_id="TCC-C110-APPROVAL", scenario_id="TCC-SCN-001",
            approver_ref="TCC-C110-SYNTHETIC-REVIEW", nonce=secrets.token_urlsafe(24),
            issued_at=(now - timedelta(seconds=5)).isoformat().replace("+00:00", "Z"),
            expires_at=(now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            key_id=cls.key.key_id,
        )
        signed = TestPostKernel._signed_command(cls)
        posted = audit_kernel.post_bill_audited(
            cls.env, command=signed,
            workflow=TrustedPostWorkflow(draft=cls.draft_workflow, target_move_id=cls.audited_bill.id),
            authority=cls.authority, key=cls.key,
            audit=replace(audit, attempt_id=secrets.token_hex(16)), document=cls.source_document,
        )
        if posted.get("status") != "POSTED" or not posted.get("audit_complete"):
            raise AssertionError("Administrative audited POST fixture failed.")
        cls.linked_attachment = cls.env["ir.attachment"].browse(
            cls.env["ap.security.audit.event"].browse(created["audit_event"]["event_id"]).attachment_id.id,
        )
        cls.ledger_targets = {
            name: cls.env[name].sudo().search([("company_id", "=", cls.company.id)], order="id")
            for name in _LEDGER_FIELDS
        }
        cls.env["ir.default"].set("account.move", "ref", "TCC-C110-TRUSTED-DEFAULT", user_id=1)
        cls.trusted_default = cls.env["ir.default"].search([
            ("user_id", "=", 1), ("field_id.model", "=", "account.move"), ("field_id.name", "=", "ref"),
        ], limit=1)
        cls.storage_parameter = cls.env["ir.config_parameter"].sudo().search([
            ("key", "=", "ir_attachment.location"),
        ], limit=1)
        cls.audited_bill.invalidate_recordset()
        if (
            cls.audited_bill.state != "posted" or not cls.linked_attachment.raw
            or cls.linked_attachment.res_model != "account.move"
            or cls.linked_attachment.res_id != cls.audited_bill.id
            or hashlib.sha256(cls.linked_attachment.raw).hexdigest() != document_sha256
            or not cls.trusted_default or not cls.storage_parameter
            or any(not target for target in cls.ledger_targets.values())
            or cls.ledger_targets["ap.security.approval.nonce"].state != "consumed"
            or len(cls.ledger_targets["ap.security.workflow.registration"]) != 1
            or len(cls.ledger_targets["ap.security.vendor.guard"]) != 1
            or cls.ledger_targets["ap.security.vendor.guard"].vendor_id != cls.vendor
            or cls.ledger_targets["ap.security.vendor.guard"].revision < 2
        ):
            raise AssertionError("Bypass fixtures lack genuine persisted critical targets.")
        # The generated MAC key/authority are not needed by any remote probe.
        cls.key = None
        cls.authority = None

    def _critical_hash(self):
        """Local administrative snapshot, not the frozen reset/oracle hash.

        Raw document bytes are read only in memory and reduced to SHA-256.
        Canonical values/IDs are never returned in the evidence file.
        """
        super()._critical_hash()
        projection = self._last_critical_projection
        for model, fields in _LEDGER_FIELDS.items():
            projection[model] = self.env[model].sudo().search([], order="id").read(fields)
        projection["bank_master"] = self.bank_master.read(["id", "name", "bic", "active"])
        projection["companies"] = self.env["res.company"].search([], order="id").read([
            "id", "name", "parent_id", "currency_id", "account_fiscal_country_id", "partner_id",
        ])
        projection["privileged_defaults"] = self.env["ir.default"].sudo().search([
            ("user_id", "in", [False, 1]),
        ], order="id").read(["id", "field_id", "user_id", "company_id", "condition", "json_value"])
        projection["attachment_storage"] = self.storage_parameter.sudo().read(["id", "key", "value"])
        projection["attachments"] = []
        for attachment in self.env["ir.attachment"].sudo().with_context(active_test=False).search([], order="id"):
            row = attachment.read([
                "id", "name", "description", "type", "mimetype", "res_model", "res_id",
                "res_field", "company_id", "public", "access_token", "url", "store_fname",
                "file_size", "checksum", "index_content",
            ])[0]
            raw = attachment.raw or b""
            row["raw_sha256"] = hashlib.sha256(raw).hexdigest()
            row["raw_bytes"] = len(raw)
            projection["attachments"].append(row)
        self._last_critical_projection = projection
        encoded = json.dumps(projection, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def _deny_mutations(self, model, target, *, create, write, context=None):
        common = {} if context is None else {"context": context}
        self._error(model, "create", {"vals_list": [create], **common})
        self._error(model, "write", {"ids": target.ids, "vals": write, **common})
        self._error(model, "unlink", {"ids": target.ids, **common})

    @classmethod
    def _write_http_evidence(cls):
        evidence_dir = os.environ.get("TCC_C1_PROBE_EVIDENCE_DIR")
        if not evidence_dir or not hasattr(cls, "http_observations"):
            return
        directory = Path(evidence_dir).resolve()
        if directory != Path("/mnt/c1-evidence"):
            raise AssertionError("Unexpected bypass evidence destination.")
        expected = {name for name in cls.__dict__ if name.startswith("test_http_")}
        checked = {item["case"] for item in cls.state_observations}
        requested = {item["case"] for item in cls.http_observations}
        evidence = {
            "schema_version": "c110-http-evidence/v1",
            "status": "PASS" if expected == checked == requested else "FAIL",
            "scope": "native-httpcase-bearer-bypass-with-closed-public-executor",
            "http_request_count": len(cls.http_observations), "http_case_count": len(requested),
            "http_test_count": len(checked), "expected_test_count": len(expected),
            "requests": cls.http_observations, "critical_state_checks": cls.state_observations,
            "critical_projection": [
                "financial-models", "supplier-and-bank-masters", "executor-identity",
                "companies", "privileged-defaults", "attachment-storage",
                "idempotency-receipts", "po-guards", "vendor-guards", "consumed-approval-nonces",
                "operational-audit-events", "all-attachments-metadata-and-raw-sha256",
            ],
            "meaningful_targets": {
                "posted_audited_bill": True, "linked_pdf_bytes_verified": True,
                "all_private_ledgers_nonempty": True, "consumed_approval_nonce": True,
                "trusted_default_nonempty": True, "bank_master_nonempty": True,
            },
            "credentials_persisted_outside_database": False,
            "financial_execution_enabled": False, "public_executor_integrated": False,
            "public_financial_effects_enabled": False,
            "integrated_executor_tested": False,
            "uses_test_cursor": True, "proves_production_lifecycle": False,
            "allows_documented_personal_default_mutation": True,
        }
        (directory / "c110-http.json").write_text(
            json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8",
        )

    def test_http_financial_crud_and_public_post_methods_are_denied(self):
        before = self._critical_hash()
        self._deny_mutations("account.move", self.draft_bill,
                             create=copy.deepcopy(self.bill_values), write={"partner_bank_id": False})
        self._deny_mutations("account.move.line", self.bill_line, create={
            "move_id": self.draft_bill.id, "account_id": self.bill_line.account_id.id,
            "name": "TCC-C110-UNAUTHORIZED", "quantity": 1.0, "price_unit": 1.0,
        }, write={"price_unit": 1.0})
        for method, target in (
            ("action_post", self.draft_bill), ("button_draft", self.audited_bill),
            ("button_cancel", self.draft_bill), ("action_duplicate", self.draft_bill),
            ("action_register_payment", self.audited_bill),
        ):
            self._error("account.move", method, {"ids": target.ids})
        self._unchanged(before)

    def test_http_purchase_master_crud_and_workflow_methods_are_denied(self):
        before = self._critical_hash()
        self._deny_mutations("purchase.order", self.draft_purchase, create={
            "partner_id": self.vendor.id, "company_id": self.company.id,
        }, write={"partner_ref": "TCC-C110-UNAUTHORIZED"})
        self._deny_mutations("purchase.order.line", self.purchase_line, create={
            "order_id": self.draft_purchase.id, "product_id": self.product.id,
            "name": "TCC-C110-UNAUTHORIZED", "product_qty": 1.0,
            "product_uom_id": self.product.uom_id.id, "price_unit": 1.0,
            "date_planned": "2026-09-30 12:00:00",
        }, write={"price_unit": 1.0})
        for method, target in (("button_confirm", self.draft_purchase), ("button_cancel", self.purchase)):
            self._error("purchase.order", method, {"ids": target.ids})
        self._unchanged(before)

    def test_http_supplier_master_crud_is_denied(self):
        before = self._critical_hash()
        self._deny_mutations("res.partner", self.vendor,
                             create={"name": "TCC-C110-UNAUTHORIZED", "supplier_rank": 1},
                             write={"ref": "TCC-C110-UNAUTHORIZED"})
        self._unchanged(before)

    def test_http_bank_master_crud_is_denied(self):
        before = self._critical_hash()
        self._deny_mutations("res.bank", self.bank_master,
                             create={"name": "TCC-C110-UNAUTHORIZED"}, write={"bic": "UNAUTHORIZED"})
        self._deny_mutations("res.partner.bank", self.bank, create={
            "acc_number": "TCC-C110-UNAUTHORIZED-SYNTHETIC", "partner_id": self.vendor.id,
        }, write={"active": False})
        self._unchanged(before)

    def test_http_bank_trust_and_trusted_recipient_have_native_denials(self):
        before = self._critical_hash()
        # The pinned core intentionally rejects these operations with UserError
        # before ordinary ACL enforcement. Accept exactly HTTP422/UserError.
        self._error("res.partner.bank", "write", {
            "ids": self.bank.ids, "vals": {"allow_out_payment": False},
        }, status=422, name=_USER_ERROR)
        self._error("res.partner.bank", "write", {
            "ids": self.bank.ids, "vals": {"acc_number": "TCC-C110-UNAUTHORIZED-SYNTHETIC"},
        }, status=422, name=_USER_ERROR)
        self._unchanged(before)

    def test_http_company_and_storage_configuration_crud_is_denied(self):
        before = self._critical_hash()
        self._deny_mutations("res.company", self.other_company,
                             create={"name": "TCC-C110-UNAUTHORIZED"}, write={"name": "TCC-C110-UNAUTHORIZED"})
        self._deny_mutations("ir.config_parameter", self.storage_parameter,
                             create={"key": "tcc.c110.unauthorized", "value": "synthetic"},
                             write={"value": "file"})
        self._error("ir.config_parameter", "set_param", {"key": "ir_attachment.location", "value": "file"})
        self._error("ir.attachment", "force_storage", {})
        self._unchanged(before)

    def test_http_payment_and_wizard_crud_and_actions_are_denied(self):
        before = self._critical_hash()
        self._deny_mutations("account.payment", self.draft_payment, create={
            "payment_type": "outbound", "partner_type": "supplier", "partner_id": self.vendor.id,
            "amount": 125.50, "journal_id": self.payment_wizard.journal_id.id,
        }, write={"amount": 1.0})
        self._deny_mutations("account.payment.register", self.payment_wizard,
                             create={"journal_id": self.payment_wizard.journal_id.id},
                             write={"amount": 1.0})
        for model, method, target in (
            ("account.payment", "action_post", self.draft_payment),
            ("account.payment", "action_cancel", self.draft_payment),
            ("account.payment.register", "action_create_payments", self.payment_wizard),
        ):
            self._error(model, method, {"ids": target.ids})
        self._unchanged(before)

    def test_http_receipt_and_po_guard_crud_and_read_are_denied(self):
        before = self._critical_hash()
        for model, changes in (
            ("ap.security.workflow.registration", {"scenario_id": "TCC-C110-DRIFT"}),
            ("ap.security.draft.receipt", {"command_sha256": "sha256:" + "e" * 64}),
            ("ap.security.po.guard", {"revision": 999}),
            ("ap.security.vendor.guard", {"revision": 999}),
        ):
            target = self.ledger_targets[model]
            self._deny_mutations(model, target, create={}, write=changes)
            self._error(model, "read", {"ids": target.ids, "fields": ["id"]})
        self._unchanged(before)

    def test_http_consumed_nonce_crud_and_read_are_denied(self):
        before = self._critical_hash()
        target = self.ledger_targets["ap.security.approval.nonce"]
        self._deny_mutations(target._name, target, create={}, write={"state": "reserved", "consumed_at": False})
        self._error(target._name, "read", {"ids": target.ids, "fields": ["id"]})
        self._unchanged(before)

    def test_http_audit_event_crud_and_read_are_denied(self):
        before = self._critical_hash()
        target = self.ledger_targets["ap.security.audit.event"]
        self._deny_mutations(target._name, target, create={}, write={"event_sha256": "sha256:" + "e" * 64})
        self._error(target._name, "read", {"ids": target.ids, "fields": ["id"]})
        self._unchanged(before)

    def test_http_financial_attachment_crud_read_and_token_are_denied(self):
        before = self._critical_hash()
        self._deny_mutations("ir.attachment", self.linked_attachment, create={
            "name": "TCC-C110-UNAUTHORIZED.pdf", "res_model": "account.move",
            "res_id": self.audited_bill.id, "type": "binary", "mimetype": "application/pdf",
            "datas": base64.b64encode(self.source_document.raw).decode("ascii"),
        }, write={"public": True})
        self._error("ir.attachment", "read", {"ids": self.linked_attachment.ids, "fields": ["id"]})
        self._error("ir.attachment", "generate_access_token", {"ids": self.linked_attachment.ids})
        self._unchanged(before)

    def test_http_financial_attachment_retarget_and_bytes_are_denied(self):
        before = self._critical_hash()
        for vals in (
            {"res_model": "res.users", "res_id": self.executor_user.id},
            {"res_model": False, "res_id": False},
            {"company_id": self.other_company.id},
            {"datas": base64.b64encode(b"%PDF-1.4\nTCC ALTERED SEM VALOR FISCAL").decode("ascii")},
            {"res_field": "invoice_pdf_report_file"},
        ):
            self._error("ir.attachment", "write", {"ids": self.linked_attachment.ids, "vals": vals})
        self._unchanged(before)

    def test_http_private_storage_and_financial_helpers_are_blocked_by_transport(self):
        before = self._critical_hash()
        for model, methods in (
            ("ap.security.executor", ("_trusted_service", "_preflight", "_check_access")),
            ("account.move", ("_post", "_create_invoices")),
            ("account.payment.register", ("_create_payments",)),
            ("ir.attachment", ("_file_write", "_generate_access_token", "_get_raw_access_token")),
        ):
            for method in methods:
                self._error(model, method, {})
        self._unchanged(before)

    def test_http_unknown_model_and_method_have_exact_transport_not_found(self):
        before = self._critical_hash()
        for model, method in (
            ("tcc.nonexistent.synthetic.model", "execute"),
            ("ap.security.executor", "create_draft_audited"),
            ("ap.security.executor", "post_bill_audited"),
            ("ap.security.executor", "sudo"),
        ):
            # Unknown model/method is NotFound; sudo is @api.private and denied
            # by get_public_method rather than by model ACL enforcement.
            if method == "sudo":
                self._error(model, method, {})
            else:
                self._error(model, method, {}, status=404, name=_NOT_FOUND)
        self._unchanged(before)

    def test_http_extra_model_method_and_document_fields_cannot_expand_capability(self):
        before = self._critical_hash()
        for field, value in (
            ("model", "account.move"), ("method", "action_post"),
            ("document", {"mimetype": "application/pdf", "raw": "%PDF synthetic"}),
            ("context", {"uid": 1, "su": True}),
        ):
            command = self._command_for_fixture()
            command[field] = value
            self._error("ap.security.executor", "execute", {"command": command},
                        status=422, name="odoo.exceptions.ValidationError")
        self._unchanged(before)

    def test_http_hostile_context_cannot_grant_generic_financial_or_ledger_writes(self):
        before = self._critical_hash()
        contexts = [
            {"uid": 1, "su": True, "allowed_company_ids": self.other_company.ids,
             "force_company": self.other_company.id, "active_test": False},
            {"allowed_company_ids": self.company.ids, "default_partner_id": self.vendor.id,
             "default_company_id": self.other_company.id, "default_move_type": "out_invoice",
             "check_move_validity": False, "tracking_disable": True,
             "skip_invoice_sync": True, "mail_create_nolog": True},
        ]
        for context in contexts:
            self._error("account.move", "create", {"vals_list": [copy.deepcopy(self.bill_values)], "context": context})
            self._error("account.move", "write", {
                "ids": self.draft_bill.ids, "vals": {"company_id": self.other_company.id}, "context": context,
            })
            self._error("account.move", "action_post", {"ids": self.draft_bill.ids, "context": context})
            self._error("ap.security.draft.receipt", "write", {
                "ids": self.ledger_targets["ap.security.draft.receipt"].ids,
                "vals": {"command_sha256": "sha256:" + "f" * 64}, "context": context,
            })
            self._error("ir.attachment", "write", {
                "ids": self.linked_attachment.ids, "vals": {"public": True}, "context": context,
            })
        self._unchanged(before)

    def test_http_own_company_and_group_preferences_do_not_expand_authority(self):
        before = self._critical_hash()
        for vals in (
            {"group_ids": [[4, self.env.ref("account.group_account_invoice").id]]},
            {"company_ids": [[4, self.other_company.id]]},
            {"partner_id": self.vendor.id},
        ):
            self._error("res.users", "write", {"ids": self.executor_user.ids, "vals": vals})
        status, body = self._rpc("res.users", "write", {
            "ids": self.executor_user.ids, "vals": {"company_id": self.other_company.id},
        })
        if status != 200 or body is not True:
            raise AssertionError("Own-company preference did not follow the pinned native behavior.")
        self._closed(self._command_for_fixture(), context={
            "allowed_company_ids": self.other_company.ids, "force_company": self.other_company.id,
        })
        self._unchanged(before)

    def test_http_privileged_defaults_cannot_be_mutated(self):
        before = self._critical_hash()
        self._deny_mutations("ir.default", self.trusted_default, create={
            "field_id": self.trusted_default.field_id.id, "user_id": 1,
            "json_value": json.dumps("TCC-C110-UNAUTHORIZED"),
        }, write={"json_value": json.dumps("TCC-C110-UNAUTHORIZED")})
        for user_id in (False, 1):
            self._error("ir.default", "set", {
                "model_name": "account.move", "field_name": "auto_post", "value": "at_date",
                "user_id": user_id,
            })
        self._unchanged(before)

    def test_http_personal_default_is_residual_but_cannot_open_public_executor(self):
        before = self._critical_hash()
        status, body = self._rpc("ir.default", "set", {
            "model_name": "account.move", "field_name": "auto_post", "value": "at_date", "user_id": True,
        })
        if status != 200 or body is not True:
            raise AssertionError("Documented personal default mutation changed unexpectedly.")
        defaults = self.env["ir.default"].sudo().search([
            ("user_id", "=", self.executor_user.id), ("field_id.model", "=", "account.move"),
            ("field_id.name", "=", "auto_post"),
        ])
        if len(defaults) != 1 or defaults.json_value != json.dumps("at_date"):
            raise AssertionError("Personal default was not scoped to the C1 user.")
        self._closed(self._command_for_fixture(), context={"default_auto_post": "at_date"})
        self._closed(self._command_for_fixture(post=True))
        self._unchanged(before)
        type(self).state_observations[-1]["permitted_residual_effect"] = "personal-default-only"

    def test_http_context_and_administratively_valid_fixture_leave_public_executor_closed(self):
        before = self._critical_hash()
        for context in (
            {}, {"allowed_company_ids": self.other_company.ids},
            {"uid": 1, "su": True, "force_company": self.other_company.id,
             "default_company_id": self.other_company.id, "default_public": True,
             "default_access_token": "TCC-SYNTHETIC-NOT-A-CREDENTIAL",
             "lang": "hostile_LANG", "tz": "hostile_TZ", "active_test": False},
        ):
            self._closed(self._command_for_fixture(), context=context)
            self._closed(self._command_for_fixture(post=True), context=context)
        self._unchanged(before)
