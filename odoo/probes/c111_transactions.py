# SPDX-License-Identifier: LGPL-3.0-or-later
"""Private C1-11 proof with real PostgreSQL transactions, never test cursors.

Run only in the disposable, internal Docker harness. MAC material and PDFs
remain in memory; the output contains finite check identifiers and hashes.
Fault injection is confined to the documented private post-write seams. No
financial method, database connection, commit or native callback is mocked.
"""

from __future__ import annotations

import argparse
import copy
from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
from pathlib import Path
import re
import secrets
import threading
import time
from unittest.mock import patch

import psycopg2.errors as pgerrors

import odoo
from odoo import Command, SUPERUSER_ID, api
from odoo.exceptions import ValidationError
from odoo.orm.registry import Registry


WAIT_SECONDS = 20
MAX_ATTEMPTS = 3


class ProbeFailure(Exception):
    """Only a fixed check identifier, never an exception message or value."""


class InjectedFault(Exception):
    pass


def require(value, check):
    if not value:
        raise ProbeFailure(check)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False, default=str).encode("utf-8")


def digest(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def pdf(text):
    text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = ("BT /F1 10 Tf 40 750 Td (" + text + ") Tj ET\n").encode("ascii")
    bodies = [b"<< /Type /Catalog /Pages 2 0 R >>",
              b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
              b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
              b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
              b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream"]
    raw, offsets = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), [0]
    for number, body in enumerate(bodies, 1):
        offsets.append(len(raw))
        raw.extend(str(number).encode("ascii") + b" 0 obj\n" + body + b"\nendobj\n")
    xref = len(raw)
    raw.extend(f"xref\n0 {len(bodies)+1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        raw.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    raw.extend(f"trailer\n<< /Size {len(bodies)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return bytes(raw)


@dataclass
class Scope:
    workflow: object
    command: dict
    document: object
    vendor_id: int
    purchase_id: int
    result: dict | None = None
    post_workflow: object = None
    post_command: dict | None = None
    authority: object = None
    key: object = None


class Probe:
    def __init__(self, registry, *, executor_login="tcc-c111-private-probe"):
        require(type(executor_login) is str and
                re.fullmatch(r"tcc-[a-z0-9-]{1,60}", executor_login),
                "bounded_synthetic_executor_login")
        from odoo.addons.ap_security_executor import (
            approval_kernel, attachment_kernel, audit_kernel, draft_kernel, post_kernel,
        )
        from odoo.addons.ap_security_executor.approval import ApprovalAuthority, ApprovalKey, APPROVAL_DOMAIN
        from odoo.addons.ap_security_executor.audit_contracts import TrustedAuditContext
        from odoo.addons.ap_security_executor.document_contracts import SourceDocument
        from odoo.addons.ap_security_executor.draft_contracts import TrustedDraftWorkflow, bill_idempotency_key
        from odoo.addons.ap_security_executor.identity import provision_executor_identity
        from odoo.addons.ap_security_executor.post_contracts import TrustedPostWorkflow
        self.registry = registry
        self.approval_kernel, self.attachment_kernel = approval_kernel, attachment_kernel
        self.audit_kernel, self.draft_kernel, self.post_kernel = audit_kernel, draft_kernel, post_kernel
        self.ApprovalAuthority, self.ApprovalKey, self.approval_domain = ApprovalAuthority, ApprovalKey, APPROVAL_DOMAIN
        self.TrustedAuditContext, self.SourceDocument = TrustedAuditContext, SourceDocument
        self.TrustedDraftWorkflow, self.bill_idempotency_key = TrustedDraftWorkflow, bill_idempotency_key
        self.TrustedPostWorkflow = TrustedPostWorkflow
        self.results = []
        self.counter = 0
        self.concurrent_retries = 0
        self.concurrent_blocks = 0
        self.independent_pairs = 0
        self.failure_checks = {}
        with registry.cursor() as cr:
            self.cursor_gate(cr)
            env = api.Environment(cr, SUPERUSER_ID, {}, su=True)
            require(env["ir.module.module"].search_count([
                ("name", "=", "ap_security_executor"), ("state", "=", "installed")]) == 1,
                "addon_installed")
            require(not env["ir.module.module"].search_count([
                ("name", "=", "attachment_indexation"), ("state", "=", "installed")]),
                "indexation_disabled")
            env["ir.config_parameter"].set_param("ir_attachment.location", "db")
            company_name = ("TCC C1-11 - SEM VALOR FISCAL" if executor_login == "tcc-c111-private-probe"
                            else "TCC " + executor_login.upper() + " - SEM VALOR FISCAL")
            company = env["res.company"].create({"name": company_name})
            self.company_id = company.id
            env = api.Environment(cr, SUPERUSER_ID, self.draft_kernel._context(company.id), su=True)
            env["account.chart.template"].try_loading("generic_coa", company=company, install_demo=False)
            executor = provision_executor_identity(env, login=executor_login, company=company)
            self.user_id = executor.id
            self.currency = company.currency_id.name
            self.expense_id = env["account.account"].search([
                *env["account.account"]._check_company_domain(company), ("account_type", "=", "expense")], limit=1).id
            self.journal_id = env["account.journal"].search([
                ("company_id", "=", company.id), ("type", "=", "purchase")], limit=1).id
            require(self.expense_id and self.journal_id, "accounting_fixture_complete")

    def cursor_gate(self, cr):
        require(type(cr).__name__ == "Cursor", "native_cursor_not_test_cursor")
        require(not odoo.tools.config["test_enable"], "test_mode_configuration_disabled")
        require(not getattr(self.registry, "test_cr", None), "registry_not_test_cursor")
        mode = getattr(self.registry, "in_test_mode", None)
        require(not (mode() if callable(mode) else mode), "registry_not_test_mode")
        cr.execute("SET LOCAL statement_timeout = '30000ms'")
        cr.execute("SET LOCAL lock_timeout = '25000ms'")
        cr.execute("SHOW transaction_isolation")
        require(cr.fetchone()[0] == "repeatable read", "repeatable_read")

    def env(self, cr):
        return api.Environment(cr, SUPERUSER_ID, self.draft_kernel._context(self.company_id), su=True)

    def audit(self):
        return self.TrustedAuditContext(
            run_id="TCC-C111-PRIVATE", attempt_id=secrets.token_hex(16),
            code_commit="a" * 40, code_sha256="sha256:" + "b" * 64,
            configuration_sha256="sha256:" + "c" * 64)

    def administrative_bank(self, env, *, vendor_id, reference):
        """Native trusted preparation, never an executor/C1 permission.

        OdooBot/UID1 cannot trust a bank outside installation or tests. Use the
        real administrative identity for this one native preparatory write;
        sudo preserves that identity and the explicit synthetic company.
        """
        administrator = env.ref("base.user_admin")
        require(administrator.exists() and administrator.active and
                administrator.id not in (SUPERUSER_ID, self.user_id), "bank_preparation_real_administrator")
        require(administrator.with_user(administrator).has_group("base.group_system"),
                "bank_preparation_administration_group")
        bank = env["res.partner.bank"].create({
            "acc_number": reference, "partner_id": vendor_id,
            "company_id": self.company_id, "allow_out_payment": False})
        require(bank.allow_out_payment is False, "bank_initially_untrusted")
        # Odoo Environment.__call__ sanitizes mail_* context when sudo changes
        # from non-su to su. Reconstruct the already trusted context explicitly
        # instead of comparing against that intentionally cleaned environment.
        # This still uses the real administrator UID and the native bank write.
        preparer_env = api.Environment(env.cr, administrator.id, dict(env.context), su=True)
        preparer = preparer_env["res.partner.bank"].browse(bank.id)
        closed_checks = {
            "administrator_uid_preserved": preparer.env.uid == administrator.id,
            "administrative_su_enabled": preparer.env.su is True,
            "trusted_context_exact": preparer.env.context == env.context,
            "synthetic_company_exact": preparer.company_id.id == self.company_id,
            "same_native_cursor": preparer.env.cr is env.cr,
        }
        self.failure_checks = closed_checks
        require(all(closed_checks.values()), "bank_preparation_identity_company_context")
        preparer.write({"allow_out_payment": True})
        preparer.flush_recordset(["allow_out_payment"])
        bank.invalidate_recordset(["allow_out_payment"])
        require(bank.allow_out_payment is True, "native_bank_trust_written")
        return bank

    def verify_trusted_bank(self, bank_id, vendor_id):
        with self.registry.cursor() as cr:
            self.cursor_gate(cr)
            bank = self.env(cr)["res.partner.bank"].browse(bank_id).exists()
            require(bank and bank.active and bank.allow_out_payment is True and
                    bank.partner_id.id == vendor_id and bank.company_id.id == self.company_id,
                    "native_bank_trust_persisted_fresh_cursor")

    def fixture(self, *, vendor_scope=None):
        self.counter += 1
        label = f"TCC-C111-{self.counter:03d}"
        document = self.SourceDocument(raw=pdf(label + " SEM VALOR FISCAL"), mimetype="application/pdf")
        document_hash = hashlib.sha256(document.raw).hexdigest()
        with self.registry.cursor() as cr:
            self.cursor_gate(cr)
            env = self.env(cr)
            if vendor_scope is None:
                vendor = env["res.partner"].create({
                    "name": label + " SUPPLIER - SEM VALOR FISCAL", "ref": label + "-VENDOR",
                    "is_company": True, "company_id": self.company_id,
                    "supplier_rank": 1, "autopost_bills": "never"})
                bank = self.administrative_bank(env, vendor_id=vendor.id,
                                                reference=label + "-SYNTHETIC-BANK")
            else:
                vendor = env["res.partner"].browse(vendor_scope.vendor_id)
                bank = env["res.partner.bank"].browse(vendor_scope.workflow.allowed_bank_ids[0])
            product = env["product.product"].create({
                "name": label + " SERVICE - SEM VALOR FISCAL", "default_code": label + "-SERVICE",
                "type": "service", "purchase_ok": True, "sale_ok": False,
                "purchase_method": "purchase", "supplier_taxes_id": [Command.clear()]})
            po = env["purchase.order"].create({
                "name": label + "-PO", "partner_id": vendor.id, "company_id": self.company_id,
                "currency_id": env.company.currency_id.id,
                "order_line": [Command.create({
                    "name": label + " LINE - SEM VALOR FISCAL", "product_id": product.id,
                    "product_qty": 1.0, "product_uom_id": product.uom_id.id, "price_unit": 125.50,
                    "date_planned": "2026-09-30 12:00:00", "tax_ids": [Command.clear()]})]})
            po.button_confirm()
            lines = po.order_line.filtered(lambda line: not line.display_type)
            require(len(lines) == 1 and lines.qty_to_invoice == 1.0, "purchase_fixture_invoiceable")
            workflow = self.TrustedDraftWorkflow(
                company_id=self.company_id, executor_user_id=self.user_id, purchase_order_id=po.id,
                vendor_id=vendor.id, journal_id=self.journal_id, expense_account_id=self.expense_id,
                purchase_line_ids=tuple(lines.ids), allowed_bank_ids=(bank.id,),
                scenario_id="TCC-SCN-001", document_sha256=document_hash,
                policy_version="policy-v1.0.0", phase="DRAFT_INTAKE",
                invoice_date_min="2026-09-01", invoice_date_max="2026-09-30",
                quantity_scale=2, monetary_tolerance="0.00")
            action = {
                "canonicalization_version": "canon/v1", "action_schema_version": "vendor-bill-action-proposal/v2",
                "policy_version": "policy-v1.0.0", "action": "CREATE_DRAFT_BILL", "executor_mode": "CREATE_DRAFT",
                "scenario_id": "TCC-SCN-001", "document_sha256": document_hash,
                "vendor_ref": vendor.ref, "purchase_order_ref": po.name,
                "document_ref": label + "-NF-SEM-VALOR-FISCAL", "invoice_date": "2026-09-30",
                "currency": self.currency, "amount": "125.50", "recipient_bank_ref": bank.acc_number,
                "lines": [{"item_code": product.default_code, "quantity": "1.00", "unit_price": "125.50"}]}
            command = {"schema_version": "capability-command/v1", "action": action,
                       "policy_decision": self.policy(action, post=False),
                       "idempotency_key": self.bill_idempotency_key(
                           document_sha256=document_hash, company_id=self.company_id, vendor_id=vendor.id,
                           purchase_order_id=po.id, purchase_line_ids=tuple(lines.ids))}
            scope = Scope(workflow, command, document, vendor.id, po.id)
        self.verify_trusted_bank(scope.workflow.allowed_bank_ids[0], scope.vendor_id)
        return scope

    @staticmethod
    def policy(action, *, post, issued="2020-01-01T00:00:00Z", expires="2020-01-01T00:05:00Z"):
        return {"schema_version": "policy-decision/v1", "decision": "REVIEW" if post else "ALLOW",
                "reason_codes": ["CRITICAL_ACTION_REQUIRES_APPROVAL" if post else "DRAFT_CONSISTENT"],
                "proposed_action_hash": digest(action), "input_sha256": "sha256:" + "b" * 64,
                "policy_version": "policy-v1.0.0", "allowed_executor": "post_bill_executor" if post else "create_bill_executor",
                "deny_class": None, "evaluated_at": issued, "expires_at": expires}

    def prepare_post(self, scope, *, nonce=None):
        if scope.result is None:
            with self.registry.cursor() as cr:
                self.cursor_gate(cr)
                scope.result = self.create(self.env(cr), scope)
                self.success(scope.result, "CREATED")
        scope.post_workflow = self.TrustedPostWorkflow(draft=scope.workflow, target_move_id=scope.result["receipt"]["move_id"])
        now = datetime.now(timezone.utc).replace(microsecond=0)
        issued = (now - timedelta(seconds=60)).isoformat().replace("+00:00", "Z")
        expires = (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        scope.key = self.ApprovalKey(company_id=self.company_id, key_id="tcc-c111-runtime-v1", material=secrets.token_bytes(32))
        scope.authority = self.ApprovalAuthority(
            company_id=self.company_id, executor_user_id=self.user_id, fixture_id="TCC-C111-APR",
            scenario_id="TCC-SCN-001", approver_ref="TCC-C111-SYNTHETIC-APPROVER",
            nonce=nonce or secrets.token_urlsafe(24), issued_at=issued, expires_at=expires, key_id=scope.key.key_id)
        action = dict(copy.deepcopy(scope.command["action"]), action="POST_VENDOR_BILL",
                      executor_mode="POST_APPROVED", target_move_id=scope.result["receipt"]["move_id"])
        unsigned = {"fixture_id": scope.authority.fixture_id, "scenario_id": scope.authority.scenario_id,
                    "approver_ref": scope.authority.approver_ref, "decision": "APPROVE",
                    "canonical_action_hash": digest(action), "nonce": scope.authority.nonce,
                    "issued_at": issued, "expires_at": expires, "key_id": scope.key.key_id}
        signature = "hmac-sha256/v1:" + hmac.new(scope.key.material,
                    self.approval_domain + canonical({"company_id": self.company_id, "approval": unsigned}),
                    hashlib.sha256).hexdigest()
        scope.post_command = {"schema_version": "capability-command/v1", "action": action,
                              "policy_decision": self.policy(action, post=True, issued=issued, expires=expires),
                              "idempotency_key": scope.command["idempotency_key"], "approval": dict(unsigned, signature=signature)}
        return scope

    def create(self, env, scope, command=None):
        result = self.audit_kernel.create_draft_audited(env, command=copy.deepcopy(command or scope.command),
            workflow=scope.workflow, audit=self.audit(), document=scope.document)
        self.closed_result(result, "CREATE_DRAFT")
        return result

    def post(self, env, scope, command=None):
        result = self.audit_kernel.post_bill_audited(env, command=copy.deepcopy(command or scope.post_command),
            workflow=scope.post_workflow, authority=scope.authority, key=scope.key,
            audit=self.audit(), document=scope.document)
        self.closed_result(result, "POST_APPROVED")
        return result

    def closed_result(self, result, mode):
        """Capture only finite return categories before success assertions."""
        require(type(result) is dict, "closed_return_dictionary")
        status = result.get("status")
        codes = result.get("reason_codes")
        complete = result.get("audit_complete")
        require(status in {"CREATED", "POSTED", "REPLAY", "DENIED"}, "closed_return_status")
        require(type(codes) is list and codes and all(type(code) is str and code in self.audit_kernel._CODES
                    for code in codes), "closed_return_reason_catalog")
        require(type(complete) is bool, "closed_return_audit_completeness")
        self.failure_checks = {"operation": mode, "result_status": status,
                               "reason_codes": list(codes), "audit_complete": complete}

    @staticmethod
    def success(result, status):
        require(result.get("status") == status and result.get("audit_complete") is True,
                "expected_audited_" + status.lower())
        require(result.get("effect_applied") is (status in ("CREATED", "POSTED")), "effect_flag_correct")

    @staticmethod
    def denied(result, code=None):
        require(result.get("status") == "DENIED" and result.get("effect_applied") is False, "failed_closed")
        if code:
            require(code in result.get("reason_codes", []), "finite_reason_expected")

    def projection(self, scope):
        with self.registry.cursor() as cr:
            self.cursor_gate(cr)
            env = self.env(cr)
            moves = env["account.move"].search([("company_id", "=", self.company_id), ("invoice_origin", "=", scope.command["action"]["purchase_order_ref"])])
            # Find by trusted source identity even if a defective rollback
            # leaves an orphan whose account.move no longer exists.
            attachments = env["ir.attachment"].search([
                ("company_id", "=", self.company_id),
                ("name", "=", "NF-SINTETICA-" + scope.workflow.document_sha256 + ".pdf")])
            receipts = env["ap.security.draft.receipt"].search([("po_id", "=", scope.purchase_id)])
            nonces = env["ap.security.approval.nonce"].search([
                ("company_id", "=", self.company_id), ("action_sha256", "=", digest(scope.post_command["action"]))]) if scope.post_command else env["ap.security.approval.nonce"]
            result = {
                "moves": moves.read(["state", "name", "posted_before", "partner_id", "partner_bank_id", "amount_total", "ref", "invoice_origin"]),
                "lines": moves.line_ids.read(["move_id", "purchase_line_id", "account_id", "quantity", "price_unit", "debit", "credit", "reconciled"]),
                "attachments": [{"id": row.id, "target": row.res_id, "mime": row.mimetype,
                    "hash": hashlib.sha256(row.raw).hexdigest(), "private": not row.public,
                    "storage_db": not row.store_fname} for row in attachments],
                "receipts": receipts.read(["executor_mode", "receipt_payload", "command_sha256", "action_sha256"]),
                "successful_audits": env["ap.security.audit.event"].search([
                    ("company_id", "=", self.company_id), ("success_receipt_id", "in", receipts.ids),
                    ("status", "in", ["CREATED", "POSTED"])]).read([
                        "status", "receipt_id", "success_receipt_id", "attachment_id", "event_sha256"]),
                "nonces": nonces.read(["state", "command_sha256", "action_sha256"]),
                "rank": env["res.partner"].browse(scope.vendor_id).supplier_rank,
                "po": env["purchase.order"].browse(scope.purchase_id).order_line.read(["qty_invoiced", "qty_to_invoice"]),
                "side_effect_counts": {name: env[name].search_count([]) for name in (
                    "account.payment", "account.partial.reconcile", "account.full.reconcile", "account.analytic.line", "mail.mail", "mail.notification")},
            }
            return result

    def guard_projection(self, scope):
        """Separate rollback projection; successful replay may bump guards."""
        with self.registry.cursor() as cr:
            self.cursor_gate(cr)
            env = self.env(cr)
            return {
                "purchase_guard": env["ap.security.po.guard"].search([
                    ("company_id", "=", self.company_id), ("po_id", "=", scope.purchase_id)
                ]).read(["company_id", "po_id", "revision"]),
                "vendor_guard": env["ap.security.vendor.guard"].search([
                    ("company_id", "=", self.company_id), ("vendor_id", "=", scope.vendor_id)
                ]).read(["company_id", "vendor_id", "revision"]),
            }

    def assert_persisted(self, scope, *, posted=False):
        state = self.projection(scope)
        require(len(state["moves"]) == len(state["attachments"]) == 1, "one_move_one_original_document")
        require(state["moves"][0]["state"] == ("posted" if posted else "draft"), "persisted_move_state")
        require(state["attachments"][0]["hash"] == scope.workflow.document_sha256 and
                state["attachments"][0]["private"] and state["attachments"][0]["storage_db"], "original_document_integrity")
        require(len(state["receipts"]) == (2 if posted else 1), "one_receipt_per_namespace")
        require(len(state["successful_audits"]) == len(state["receipts"]), "one_success_audit_per_effect")
        require(len(state["nonces"]) == (1 if posted else 0), "nonce_exactly_once")
        if posted:
            require(state["nonces"][0]["state"] == "consumed" and state["rank"] == 2, "native_postcommit_rank_and_nonce")
        return state

    def record(self, name, operation):
        self.failure_checks = {}
        try:
            detail = operation() or {}
            self.results.append({"case": name, "case_id": name, "status": "PASS", "checks": detail})
        except BaseException as error:
            category = str(error) if isinstance(error, ProbeFailure) else "unexpected_runtime_failure"
            require(re.fullmatch(r"[a-z_]+", category), "safe_failure_category")
            self.results.append({"case": name, "case_id": name, "status": "FAIL", "category": category,
                                 "checks": self.failure_checks})
            raise ProbeFailure(category) from None

    def create_commit(self):
        scope = self.fixture()
        with self.registry.cursor() as cr:
            self.cursor_gate(cr)
            result = self.create(self.env(cr), scope)
            self.success(result, "CREATED")
            require(not self.projection(scope)["moves"], "uncommitted_create_invisible")
            cr.commit()
        before = self.assert_persisted(scope)
        with self.registry.cursor() as cr:
            self.cursor_gate(cr)
            replay = self.create(self.env(cr), scope)
            self.success(replay, "REPLAY")
            require(replay["receipt"] == result["receipt"], "original_create_receipt")
        require(self.projection(scope) == before, "create_replay_no_financial_duplicate")
        return {"fresh_cursor_visibility": True, "original_receipt": True, "projection_sha256": digest(before)}

    def rollback_case(self, *, post, savepoint):
        scope = self.fixture()
        if post:
            self.prepare_post(scope)
        before = self.projection(scope)
        guards_before = self.guard_projection(scope)
        unrelated_callbacks = []
        with self.registry.cursor() as cr:
            self.cursor_gate(cr)
            env = self.env(cr)
            if savepoint:
                cr.postcommit.add(lambda: unrelated_callbacks.append(True))
                try:
                    with cr.savepoint():
                        result = self.post(env, scope) if post else self.create(env, scope)
                        self.success(result, "POSTED" if post else "CREATED")
                        raise InjectedFault()
                except InjectedFault:
                    pass
                # Real commit runs any guards left by the rolled-back savepoint.
                cr.commit()
            else:
                result = self.post(env, scope) if post else self.create(env, scope)
                self.success(result, "POSTED" if post else "CREATED")
                cr.rollback()
                cr.commit()
        require(self.projection(scope) == before, "outer_rollback_restores_all_financial_state")
        require(self.guard_projection(scope) == guards_before, "outer_rollback_restores_both_serialization_guards")
        require(unrelated_callbacks == ([True] if savepoint else []), "unrelated_commit_callback_preserved")
        return {"external_rollback": True, "native_rank_unchanged": True,
                "unrelated_callback_preserved": savepoint, "both_guards_rolled_back": True,
                "projection_sha256": digest(before), "guards_sha256": digest(guards_before)}

    def fault_case(self, module, seam, *, post, observed_kind):
        scope = self.fixture()
        if post:
            self.prepare_post(scope)
        before = self.projection(scope)
        guards_before = self.guard_projection(scope)
        observed = []
        def fail(record):
            if observed_kind == "move":
                require(record.exists() and record.state == ("posted" if post else "draft"), "fault_after_genuine_financial_write")
            elif observed_kind == "attachment":
                require(record.exists() and record.raw == scope.document.raw, "fault_after_genuine_attachment_write")
            elif observed_kind == "nonce":
                require(record.exists() and record.state == "consumed", "fault_after_genuine_nonce_consumption")
            elif observed_kind == "audit":
                if record.status == "DENIED":
                    return
                require(record.exists() and record.status == ("POSTED" if post else "CREATED"), "fault_after_genuine_audit_write")
            observed.append(True)
            raise InjectedFault()
        with patch.object(module, seam, side_effect=fail):
            with self.registry.cursor() as cr:
                self.cursor_gate(cr)
                result = self.post(self.env(cr), scope) if post else self.create(self.env(cr), scope)
                self.denied(result)
                cr.commit()
        require(observed == [True], "fault_observed_exactly_once")
        require(self.projection(scope) == before, "fault_rolls_back_all_financial_state")
        require(self.guard_projection(scope) == guards_before, "fault_rolls_back_both_serialization_guards")
        with self.registry.cursor() as cr:
            self.cursor_gate(cr)
            retry = self.post(self.env(cr), scope) if post else self.create(self.env(cr), scope)
            self.success(retry, "POSTED" if post else "CREATED")
        self.assert_persisted(scope, posted=post)
        return {"real_write_before_fault": True, "complete_rollback": True,
                "both_guards_rolled_back": True, "same_command_retry": True}

    def post_commit(self):
        scope = self.prepare_post(self.fixture())
        before = self.projection(scope)
        with self.registry.cursor() as cr:
            self.cursor_gate(cr)
            result = self.post(self.env(cr), scope)
            self.success(result, "POSTED")
            require(self.projection(scope) == before, "uncommitted_post_and_rank_invisible")
            cr.commit()
        after = self.assert_persisted(scope, posted=True)
        require(after["rank"] == before["rank"] + 1, "genuine_native_rank_callback_committed")
        with self.registry.cursor() as cr:
            self.cursor_gate(cr)
            replay = self.post(self.env(cr), scope)
            self.success(replay, "REPLAY")
            require(replay["receipt"] == result["receipt"], "original_post_receipt")
        require(self.projection(scope) == after, "post_replay_no_nonce_or_rank_duplicate")
        return {"real_commit_native_callback": True, "replay_no_additional_rank": True, "projection_sha256": digest(after)}

    def altered_approval(self, *, storage=False):
        scope = self.prepare_post(self.fixture())
        command = copy.deepcopy(scope.post_command)
        if storage:
            with self.registry.cursor() as cr:
                self.cursor_gate(cr)
                env = self.env(cr)
                bank = self.administrative_bank(env, vendor_id=scope.vendor_id,
                                                reference="TCC-C111-ALTERED-SYNTHETIC")
                env["account.move"].browse(scope.post_workflow.target_move_id).write({"partner_bank_id": bank.id})
                drift_bank_id = bank.id
            self.verify_trusted_bank(drift_bank_id, scope.vendor_id)
        else:
            command["action"]["amount"] = "126.50"
            command["policy_decision"]["proposed_action_hash"] = digest(command["action"])
        before = self.projection(scope)
        with self.registry.cursor() as cr:
            self.cursor_gate(cr)
            if storage:
                result = self.post(self.env(cr), scope, command)
                self.denied(result, "PERSISTED_STATE_MISMATCH")
                require(result.get("audit_complete") is True, "storage_drift_denial_audited")
            else:
                # Preserve the authentic original approval unchanged. Its
                # canonical action hash no longer matches the altered body,
                # so the closed contract rejects before operational effects.
                observed = False
                try:
                    self.post(self.env(cr), scope, command)
                except ValidationError as error:
                    require(str(error) == "Invalid private audit command.", "exact_structural_drift_validation")
                    observed = True
                require(observed, "altered_approval_contract_rejected")
        require(self.projection(scope) == before, "approval_drift_no_post_or_nonce")
        return {"registered_approval_not_reissued": True, "complete_financial_neutrality": True}

    def conflict(self, *, post):
        scope = self.fixture()
        if post:
            self.prepare_post(scope)
        with self.registry.cursor() as cr:
            self.cursor_gate(cr)
            result = self.post(self.env(cr), scope) if post else self.create(self.env(cr), scope)
            self.success(result, "POSTED" if post else "CREATED")
        before = self.projection(scope)
        command = copy.deepcopy(scope.post_command if post else scope.command)
        # Same action/key, different body; do not mint or re-sign an approval.
        command["policy_decision"]["input_sha256"] = "sha256:" + "d" * 64
        with self.registry.cursor() as cr:
            self.cursor_gate(cr)
            result = self.post(self.env(cr), scope, command) if post else self.create(self.env(cr), scope, command)
            self.denied(result, "IDEMPOTENCY_CONFLICT")
            require(result.get("audit_complete") is True, "changed_body_denial_audited")
        require(self.projection(scope) == before, "changed_command_no_effect")
        return {"same_key_changed_body_denied": True, "original_state_unchanged": True}

    def duplicate(self):
        first = self.fixture()
        with self.registry.cursor() as cr:
            self.cursor_gate(cr)
            self.success(self.create(self.env(cr), first), "CREATED")
        second = self.fixture(vendor_scope=first)
        second.command["action"]["document_ref"] = first.command["action"]["document_ref"]
        second.command["policy_decision"]["proposed_action_hash"] = digest(second.command["action"])
        before = self.projection(second)
        with self.registry.cursor() as cr:
            self.cursor_gate(cr)
            result = self.create(self.env(cr), second)
            self.denied(result, "DUPLICATE_DOCUMENT")
            require(result.get("audit_complete") is True, "duplicate_reference_denial_audited")
        require(self.projection(second) == before, "duplicate_reference_no_second_bill")
        return {"distinct_document_and_po_same_vendor_reference": True, "second_effect_absent": True}

    def race(self, scopes, *, mode, expected, seam_module, seam_name, require_retry=True):
        """Hold leader after genuine write; observe follower blocked in PostgreSQL.

        A serialization/deadlock MUST escape the helper, be fully rolled back,
        and retry on a new cursor/transaction with the identical command body.
        Backend PID values are never written to the evidence.
        """
        leader_ready, release, follower_ready = threading.Event(), threading.Event(), threading.Event()
        pids, results, errors, retries, rollback_seen, retry_new = {}, {}, {}, {}, {}, {}
        original_cursors, snapshot_established = {}, {}
        gate = threading.Lock()
        original_hashes = [digest(scope.post_command if mode in ("POST", "NONCE") else scope.command) for scope in scopes]
        leader_write = []
        def hold(record):
            if threading.current_thread().name == "c111-leader":
                require(record.exists(), "concurrency_leader_genuine_write")
                leader_write.append(True)
                leader_ready.set()
                require(release.wait(WAIT_SECONDS), "bounded_leader_release")
        def operate(env, scope):
            if mode == "CREATE":
                return self.create(env, scope)
            if mode == "POST":
                return self.post(env, scope)
            with self.approval_kernel.approval_transaction(env, command=copy.deepcopy(scope.post_command),
                    trusted_action=copy.deepcopy(scope.post_command["action"]), authority=scope.authority,
                    key=scope.key, now=datetime.now(timezone.utc)) as reservation:
                record = env["ap.security.approval.nonce"].browse(reservation.ledger_id)
                hold(record)
            return {"status": "CONSUMED", "ledger_id": reservation.ledger_id}
        def worker(number):
            try:
                for attempt in range(MAX_ATTEMPTS):
                    cr = self.registry.cursor()
                    try:
                        self.cursor_gate(cr)
                        cr.execute("SELECT pg_backend_pid()")
                        pid = cr.fetchone()[0]
                        if attempt == 0:
                            with gate:
                                pids[number] = pid
                                original_cursors[number] = cr
                            # A genuine read establishes the RR snapshot while
                            # leader still holds its uncommitted real write.
                            cr.execute("SELECT count(*) FROM account_move")
                            cr.fetchone()
                            snapshot_established[number] = True
                            if number == 1:
                                follower_ready.set()
                                require(leader_ready.wait(WAIT_SECONDS), "leader_wait_bounded")
                        elif number == 1:
                            # A pooled connection may reuse a PID; cursor and
                            # transaction must be new, not necessarily socket.
                            retry_new[number] = cr is not original_cursors[number]
                        scope = scopes[number]
                        require(digest(scope.post_command if mode in ("POST", "NONCE") else scope.command) == original_hashes[number], "retry_body_identical")
                        result = operate(self.env(cr), scope)
                        cr.commit()
                        results[number] = result
                        retries[number] = attempt
                        return
                    except (pgerrors.SerializationFailure, pgerrors.DeadlockDetected):
                        cr.rollback()
                        # Validate rollback using a real SQL query in a fresh
                        # transaction before closing and retrying the helper.
                        cr.execute("SELECT txid_current_if_assigned() IS NULL")
                        require(cr.fetchone()[0] is True, "pg_retry_full_transaction_rollback")
                        rollback_seen[number] = True
                    except self.approval_kernel.ApprovalVerificationError as error:
                        cr.rollback()
                        if mode == "NONCE" and error.code == "NONCE_REUSED":
                            results[number] = {"status": "NONCE_REUSED"}
                            retries[number] = attempt
                            return
                        raise
                    finally:
                        cr.close()
                raise ProbeFailure("bounded_retry_exhausted")
            except BaseException as error:
                errors[number] = str(error) if isinstance(error, ProbeFailure) else "unexpected_worker_failure"
                release.set()
        leader = threading.Thread(target=worker, args=(0,), name="c111-leader", daemon=True)
        follower = threading.Thread(target=worker, args=(1,), name="c111-follower", daemon=True)
        blocked = False
        # NONCE holds at the real INSERT reservation body above, not both at
        # reservation and consumption. All other holds use a post-write seam.
        fault_scope = nullcontext() if mode == "NONCE" else patch.object(seam_module, seam_name, side_effect=hold)
        with fault_scope:
            try:
                leader.start()
                require(leader_ready.wait(WAIT_SECONDS), "leader_real_write_reached")
                follower.start()
                require(follower_ready.wait(WAIT_SECONDS), "follower_cursor_ready")
                require(pids.get(0) != pids.get(1), "concurrent_connections_independent")
                deadline = time.monotonic() + WAIT_SECONDS
                while time.monotonic() < deadline and not errors:
                    with self.registry.cursor() as observer:
                        self.cursor_gate(observer)
                        observer.execute("SELECT wait_event_type = 'Lock' AND %s = ANY(pg_blocking_pids(pid)) FROM pg_stat_activity WHERE pid = %s", (pids[0], pids[1]))
                        row = observer.fetchone()
                        blocked = bool(row and row[0])
                    if blocked:
                        break
                    release.wait(0.02)
                require(blocked, "postgres_blocking_overlap_observed")
            finally:
                release.set()
                leader.join(WAIT_SECONDS)
                if follower.ident is not None:
                    follower.join(WAIT_SECONDS)
        require(not leader.is_alive() and not follower.is_alive(), "workers_terminated_bounded")
        require(not errors, "concurrent_workers_succeeded")
        observed_statuses = [results[number].get("status") for number in (0, 1)]
        require(all(status in {"CREATED", "POSTED", "REPLAY", "DENIED", "CONSUMED", "NONCE_REUSED"}
                    for status in observed_statuses), "finite_concurrent_statuses")
        self.failure_checks = {"observed_statuses": observed_statuses,
            "independent_backend_connections": pids.get(0) != pids.get(1),
            "postgres_lock_overlap": blocked, "follower_snapshot_before_leader_commit": snapshot_established.get(1) is True,
            "retry_count": sum(retries.values())}
        require([results[number]["status"] for number in (0, 1)] == expected, "concurrent_result_contract")
        if require_retry:
            require(bool(rollback_seen.get(1)) and retries.get(1, 0) >= 1 and retry_new.get(1), "serialization_retried_new_cursor")
        require(leader_write == [True], "single_leader_write")
        self.concurrent_retries += sum(retries.values())
        self.concurrent_blocks += 1
        self.independent_pairs += 1
        return results, {"independent_backend_connections": True, "postgres_lock_overlap": True,
                         "follower_snapshot_before_leader_commit": snapshot_established.get(1) is True,
                         "full_rollback_before_retry": bool(rollback_seen.get(1)),
                         "new_cursor_identical_command_retry": bool(retry_new.get(1)),
                         "retry_count": sum(retries.values())}

    def concurrent_same(self, *, post):
        scope = self.fixture()
        if post:
            self.prepare_post(scope)
        results, detail = self.race([scope, scope], mode="POST" if post else "CREATE",
            expected=["POSTED" if post else "CREATED", "REPLAY"],
            seam_module=self.post_kernel if post else self.draft_kernel,
            seam_name="_after_post" if post else "_after_draft_create")
        require(results[0]["receipt"] == results[1]["receipt"], "concurrent_original_receipt")
        self.assert_persisted(scope, posted=post)
        return dict(detail, one_financial_effect=True, original_receipt=True)

    def concurrent_remaining(self):
        first = self.fixture()
        raw = pdf("TCC C111 DISTINCT DOCUMENT SAME PO SEM VALOR FISCAL")
        second = copy.copy(first)
        second.document = self.SourceDocument(raw=raw, mimetype="application/pdf")
        second.workflow = replace(first.workflow, document_sha256=hashlib.sha256(raw).hexdigest())
        second.command = copy.deepcopy(first.command)
        second.command["action"]["document_sha256"] = second.workflow.document_sha256
        second.command["action"]["document_ref"] += "-SECOND"
        second.command["policy_decision"]["proposed_action_hash"] = digest(second.command["action"])
        second.command["idempotency_key"] = self.bill_idempotency_key(
            document_sha256=second.workflow.document_sha256, company_id=self.company_id,
            vendor_id=second.vendor_id, purchase_order_id=second.purchase_id,
            purchase_line_ids=second.workflow.purchase_line_ids)
        results, detail = self.race([first, second], mode="CREATE", expected=["CREATED", "DENIED"],
            seam_module=self.draft_kernel, seam_name="_after_draft_create")
        self.denied(results[1], "LINE_MISMATCH")
        require(results[1].get("audit_complete") is True, "remaining_quantity_denial_audited")
        self.assert_persisted(first)
        return dict(detail, consumed_quantity_not_reused=True, second_financial_effect_absent=True)

    def concurrent_nonce(self):
        first = self.prepare_post(self.fixture())
        second = self.prepare_post(self.fixture(), nonce=first.authority.nonce)
        before = [self.projection(scope) for scope in (first, second)]
        results, detail = self.race([first, second], mode="NONCE", expected=["CONSUMED", "NONCE_REUSED"],
            seam_module=self.approval_kernel, seam_name="_after_nonce_consume")
        after = [self.projection(scope) for scope in (first, second)]
        for index in (0, 1):
            old = copy.deepcopy(before[index]); new = copy.deepcopy(after[index])
            old.pop("nonces"); new.pop("nonces")
            require(old == new, "nonce_primitive_no_financial_effect")
        require(len(after[0]["nonces"]) == 1 and not after[1]["nonces"], "globally_unique_nonce")
        return dict(detail, global_nonce_one_consumption=True, scope="private-approval-primitive-only")

    def concurrent_cross_po_reference(self):
        first = self.fixture()
        second = self.fixture(vendor_scope=first)
        second.command["action"]["document_ref"] = first.command["action"]["document_ref"]
        second.command["policy_decision"]["proposed_action_hash"] = digest(second.command["action"])
        second_before = self.projection(second)
        results, detail = self.race([first, second], mode="CREATE", expected=["CREATED", "DENIED"],
            seam_module=self.draft_kernel, seam_name="_after_draft_create", require_retry=True)
        self.denied(results[1], "DUPLICATE_DOCUMENT")
        require(results[1].get("audit_complete") is True, "cross_po_reference_denial_audited")
        self.assert_persisted(first)
        require(self.projection(second) == second_before, "cross_po_duplicate_second_document_neutral")
        return dict(detail, cross_po_reference_unique=True,
                    audited_duplicate_denial=True, second_document_projection_unchanged=True)

    def run(self):
        self.record("create_commit_replay", self.create_commit)
        for post in (False, True):
            for savepoint in (False, True):
                self.record(("post" if post else "create") + ("_outer_savepoint_rollback" if savepoint else "_outer_rollback"),
                            lambda post=post, savepoint=savepoint: self.rollback_case(post=post, savepoint=savepoint))
        for name, module, seam, post, kind in (
            ("create_fault_after_move", self.draft_kernel, "_after_draft_create", False, "move"),
            ("create_fault_after_attachment", self.attachment_kernel, "_after_attachment_create", False, "attachment"),
            ("create_fault_after_audit", self.audit_kernel, "_after_audit_append", False, "audit"),
            ("post_fault_after_native_post", self.post_kernel, "_after_post", True, "move"),
            ("post_fault_after_nonce_consumption", self.approval_kernel, "_after_nonce_consume", True, "nonce"),
            ("post_fault_after_audit", self.audit_kernel, "_after_audit_append", True, "audit"),
        ):
            self.record(name, lambda module=module, seam=seam, post=post, kind=kind:
                        self.fault_case(module, seam, post=post, observed_kind=kind))
        self.record("post_commit_native_rank_replay", self.post_commit)
        self.record("altered_command_after_approval", self.altered_approval)
        self.record("stored_beneficiary_drift_after_approval", lambda: self.altered_approval(storage=True))
        self.record("create_idempotency_changed_body", lambda: self.conflict(post=False))
        self.record("post_idempotency_changed_body", lambda: self.conflict(post=True))
        self.record("duplicate_reference_distinct_document", self.duplicate)
        self.record("concurrent_create_identical_command", lambda: self.concurrent_same(post=False))
        self.record("concurrent_post_identical_command", lambda: self.concurrent_same(post=True))
        self.record("concurrent_distinct_documents_remaining_quantity", self.concurrent_remaining)
        self.record("concurrent_global_nonce_primitive", self.concurrent_nonce)
        self.record("concurrent_cross_po_same_vendor_reference", self.concurrent_cross_po_reference)

    def evidence(self, *, status):
        return {"schema_version": "c111-transactions-evidence/v1", "status": status,
                "scope": "private-native-transactions-and-deferred-metadata-only",
                "case_count": len(self.results), "test_count": len(self.results),
                "passed_case_count": sum(result["status"] == "PASS" for result in self.results),
                "cases": self.results, "concurrent_retry_count": self.concurrent_retries,
                "observed_blocking_pair_count": self.concurrent_blocks,
                "independent_connection_pair_count": self.independent_pairs,
                "normal_registry": True, "test_cursor_used": False, "mocked_sql_commit": False,
                "registry_test_mode": False, "public_financial_effects_enabled": False,
                "independent_cursor_concurrency_tested": self.independent_pairs == 5,
                "native_supplier_rank_commit_lifecycle_tested": any(case["case_id"] == "post_commit_native_rank_replay" and case["status"] == "PASS" for case in self.results),
                "backend_independence_verified": self.independent_pairs == 5,
                "blocking_overlap_verified": self.concurrent_blocks == 5,
                "native_postcommit_executed": any(case["case_id"] == "post_commit_native_rank_replay" and case["status"] == "PASS" for case in self.results),
                "public_executor_enabled": False, "scientific_run": False,
                "human_review_complete": False, "limitations": [
                    "Private administrative wrappers, not integrated JSON-2 financial execution.",
                    "Approval nonce collision separately exercises the private approval primitive.",
                    "Bounded pairs do not exhaust all schedules, isolation levels or admin configuration races.",
                    "Deferred supplier rank is best-effort native metadata, not financial atomicity.",
                    "No scientific dataset, pilot, freeze or independent human acceptance."]}


def main():
    parser = argparse.ArgumentParser(description="Disposable private C1-11 transaction probe")
    parser.add_argument("--config", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    require(args.config == "/etc/odoo/c104.conf", "trusted_config_path")
    require(re.fullmatch(r"tcc_c111_[0-9a-f]{12}", args.database), "disposable_database_namespace")
    require(args.evidence == "/mnt/c1-evidence/c111-transactions.json", "trusted_evidence_path")
    # Expected PostgreSQL failures can log full query parameters. Disable all
    # runtime logging before loading Odoo; never output exception messages.
    logging.disable(logging.CRITICAL)
    odoo.tools.config.parse_config(["-c", args.config, "-d", args.database, "--no-http"], setup_logging=False)
    registry = Registry(args.database)
    probe = Probe(registry)
    status = "FAIL"
    try:
        probe.run()
        require(len(probe.results) == 22 and all(case["status"] == "PASS" for case in probe.results), "all_cases_executed")
        require(probe.concurrent_blocks == probe.independent_pairs == 5, "all_concurrency_pairs_executed")
        status = "PASS"
    except BaseException:
        pass
    result = probe.evidence(status=status)
    Path(args.evidence).write_bytes(canonical(result) + b"\n")
    print("C1-11 " + status + " " + str(result["passed_case_count"]) + "/" + str(result["case_count"]) + " cases")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ProbeFailure, Exception):
        print("C1-11 FAIL safe-runtime-category")
        raise SystemExit(1) from None
