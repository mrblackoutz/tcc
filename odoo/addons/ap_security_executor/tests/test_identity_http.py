# SPDX-License-Identifier: LGPL-3.0-or-later
"""Real HTTP/bearer/ACL checks in a disposable, transactional Odoo HttpCase.

All business records are synthetic and have no fiscal value. The test cursor
is Odoo's native test mechanism; this is not a production lifecycle or pilot.
API keys never leave Python memory or Odoo's hashed, disposable key table.
"""

import copy
import datetime as dt
import hashlib
import json
import logging
import os
from pathlib import Path

from odoo import Command
from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user

from ..identity import assert_executor_identity, provision_executor_identity
from .test_executor import _action_hash, _command


_logger = logging.getLogger(__name__)
_ACCESS_ERROR = "odoo.exceptions.AccessError"
_VALIDATION_ERROR = "odoo.exceptions.ValidationError"
_USER_ERROR = "odoo.exceptions.UserError"
_UNAUTHORIZED = "werkzeug.exceptions.Unauthorized"


@tagged("post_install", "-at_install", "c1_acl_http")
class TestExecutorIdentityHttp(HttpCase):
    """No mocked credentials, session authentication, or privileged request."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env["res.company"].create({
            "name": "TCC C1-05 OTHER COMPANY - SEM VALOR FISCAL",
        })
        if not cls.company.chart_template:
            cls.env["account.chart.template"].try_loading(
                "generic_coa", company=cls.company, install_demo=False,
            )
        cls.executor_user = provision_executor_identity(
            cls.env, login="tcc-c105-http-executor", company=cls.company,
        )
        cls.inventory = assert_executor_identity(
            cls.env, cls.executor_user, company=cls.company,
        )
        cls.wrong_user = new_test_user(
            cls.env, login="tcc-c105-http-no-group", groups="base.group_user",
            company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)],
            name="TCC C1-05 unauthorized synthetic user",
        )
        cls.executor_key = cls.env["res.users.apikeys"].with_user(
            cls.executor_user,
        ).sudo()._generate(
            None, "TCC C1-05 disposable HTTP test",
            dt.datetime.now() + dt.timedelta(hours=1),
        )
        cls.wrong_key = cls.env["res.users.apikeys"].with_user(
            cls.wrong_user,
        ).sudo()._generate(
            None, "TCC C1-05 disposable unauthorized HTTP test",
            dt.datetime.now() + dt.timedelta(hours=1),
        )
        cls.vendor = cls.env["res.partner"].create({
            "name": "TCC C1-05 SUPPLIER - SEM VALOR FISCAL",
            "ref": "TCC-C105-VENDOR", "is_company": True,
            "company_id": cls.company.id, "supplier_rank": 1,
        })
        cls.bank = cls.env["res.partner.bank"].create({
            "acc_number": "TCC-C105-SYNTHETIC-BANK",
            "partner_id": cls.vendor.id, "company_id": cls.company.id,
            "allow_out_payment": False,
        })
        cls.product = cls.env["product.product"].create({
            "name": "TCC C1-05 SERVICE - SEM VALOR FISCAL",
            "default_code": "TCC-C105-SERVICE", "type": "service",
            "purchase_ok": True, "sale_ok": False,
            "purchase_method": "purchase", "supplier_taxes_id": [Command.clear()],
        })
        po_values = {
            "name": "TCC-C105-PO-CONFIRMED", "partner_id": cls.vendor.id,
            "company_id": cls.company.id, "currency_id": cls.company.currency_id.id,
            "order_line": [Command.create({
                "name": cls.product.name, "product_id": cls.product.id,
                "product_qty": 5.0, "product_uom_id": cls.product.uom_id.id,
                "price_unit": 125.50, "date_planned": "2026-09-30 12:00:00",
                "tax_ids": [Command.clear()],
            })],
        }
        cls.purchase = cls.env["purchase.order"].create(po_values)
        cls.purchase.button_confirm()
        cls.draft_purchase = cls.purchase.copy({"name": "TCC-C105-PO-DRAFT"})
        cls.purchase_line = cls.purchase.order_line.filtered(lambda line: not line.display_type)
        expense = cls.env["account.account"].search([
            *cls.env["account.account"]._check_company_domain(cls.company),
            ("account_type", "=", "expense"),
        ], limit=1)
        journal = cls.env["account.journal"].search([
            ("company_id", "=", cls.company.id), ("type", "=", "purchase"),
        ], limit=1)
        if not expense or not journal or len(cls.purchase_line) != 1:
            raise AssertionError("Synthetic accounting fixtures are incomplete.")
        cls.bill_values = {
            "move_type": "in_invoice", "company_id": cls.company.id,
            "partner_id": cls.vendor.id, "currency_id": cls.company.currency_id.id,
            "journal_id": journal.id, "invoice_date": "2026-09-30",
            "ref": "TCC-C105-NF-DRAFT-SEM-VALOR-FISCAL", "auto_post": "no",
            "partner_bank_id": cls.bank.id,
            "invoice_line_ids": [Command.create({
                "name": cls.product.name, "product_id": cls.product.id,
                "account_id": expense.id, "quantity": 1.0, "price_unit": 125.50,
                "purchase_line_id": cls.purchase_line.id,
                "tax_ids": [Command.clear()],
            })],
        }
        cls.draft_bill = cls.env["account.move"].create(copy.deepcopy(cls.bill_values))
        cls.bill_line = cls.draft_bill.invoice_line_ids
        posted_values = copy.deepcopy(cls.bill_values)
        posted_values.update({
            "ref": "TCC-C105-NF-POSTED-SEM-VALOR-FISCAL", "partner_bank_id": False,
        })
        cls.posted_bill = cls.env["account.move"].create(posted_values)
        cls.posted_bill.action_post()
        bank_journal = cls.env["account.journal"].search([
            ("company_id", "=", cls.company.id), ("type", "=", "bank"),
        ], limit=1)
        if not bank_journal:
            bank_journal = cls.env["account.journal"].create({
                "name": "TCC C1-05 SYNTHETIC BANK JOURNAL", "code": "T105B",
                "type": "bank", "company_id": cls.company.id,
            })
        cls.payment_wizard = cls.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=cls.posted_bill.ids,
        ).create({"journal_id": bank_journal.id})
        manual_method = bank_journal.outbound_payment_method_line_ids.filtered(
            lambda method: method.code == "manual",
        )[:1]
        if not manual_method:
            raise AssertionError("Synthetic payment target lacks a manual method.")
        cls.draft_payment = cls.env["account.payment"].create({
            "payment_type": "outbound", "partner_type": "supplier",
            "partner_id": cls.vendor.id, "amount": 125.50,
            "journal_id": bank_journal.id, "payment_method_line_id": manual_method.id,
            "currency_id": cls.company.currency_id.id,
        })
        if (
            cls.draft_bill.state != "draft" or cls.posted_bill.state != "posted"
            or not cls.payment_wizard.line_ids or cls.bank.allow_out_payment
            or cls.draft_purchase.state != "draft"
            or cls.draft_payment.state != "draft"
        ):
            raise AssertionError("Synthetic mutation targets are not meaningful.")
        cls.http_observations = []
        cls.state_observations = []

    @classmethod
    def tearDownClass(cls):
        try:
            evidence_dir = os.environ.get("TCC_C1_PROBE_EVIDENCE_DIR")
            if evidence_dir and hasattr(cls, "http_observations"):
                directory = Path(evidence_dir).resolve()
                if directory != Path("/mnt/c1-evidence"):
                    raise AssertionError("Unexpected HTTP evidence destination.")
                expected_tests = {
                    name for name in cls.__dict__ if name.startswith("test_http_")
                }
                checked_tests = {item["case"] for item in cls.state_observations}
                evidence = {
                    "schema_version": "c105-http-evidence/v1",
                    "status": "PASS" if checked_tests == expected_tests else "FAIL",
                    "scope": "native-httpcase-bearer-and-acl-test-cursor",
                    "http_request_count": len(cls.http_observations),
                    "http_case_count": len({item["case"] for item in cls.http_observations}),
                    "http_test_count": len(checked_tests),
                    "requests": cls.http_observations,
                    "critical_state_checks": cls.state_observations,
                    "identity_inventory": cls.inventory,
                    "credentials_persisted_outside_database": False,
                    "financial_execution_enabled": False,
                }
                (directory / "c105-http.json").write_text(
                    json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8",
                )
            if hasattr(cls, "http_observations"):
                _logger.info("C1-05 HTTP probe observed %s real requests", len(cls.http_observations))
        finally:
            cls.executor_key = None
            cls.wrong_key = None
            super().tearDownClass()

    def _command_for_fixture(self, *, post=False):
        command = _command(post=post)
        action = command["action"]
        action.update({
            "vendor_ref": self.vendor.ref, "purchase_order_ref": self.purchase.name,
            "currency": self.company.currency_id.name,
            "recipient_bank_ref": "TCC-C105-BANK",
            "document_ref": self.draft_bill.ref,
        })
        action["lines"][0]["item_code"] = self.product.default_code
        if post:
            action["target_move_id"] = self.draft_bill.id
        digest = _action_hash(action)
        command["policy_decision"]["proposed_action_hash"] = digest
        if post:
            command["approval"]["canonical_action_hash"] = digest
        return command

    def _critical_hash(self):
        """Trusted local projection, not the frozen scientific reset oracle."""
        def identity_links(records, fields):
            rows = records.read(fields)
            for row in rows:
                for field in fields:
                    if records._fields[field].type == "many2one":
                        # Link identity is the ID, not an editable display_name.
                        row[field] = row[field][0] if row[field] else False
            return rows

        fields_by_model = {
            "account.move": ["id", "state", "move_type", "company_id", "partner_id",
                             "partner_bank_id", "ref", "amount_total", "auto_post"],
            "account.move.line": ["id", "move_id", "account_id", "partner_id", "quantity",
                                  "price_unit", "debit", "credit", "purchase_line_id"],
            "purchase.order": ["id", "state", "company_id", "partner_id", "currency_id", "amount_total"],
            "purchase.order.line": ["id", "order_id", "product_id", "product_qty", "price_unit", "qty_invoiced"],
            "account.payment": ["id", "state", "partner_id", "company_id", "amount"],
            "res.partner.bank": ["id", "partner_id", "company_id", "acc_number", "allow_out_payment", "active"],
        }
        projection = {}
        self.env.invalidate_all()
        for model, fields in fields_by_model.items():
            projection[model] = identity_links(self.env[model].with_context(active_test=False).search([], order="id"), fields)
        projection["vendor"] = identity_links(self.vendor, [
            "id", "name", "ref", "company_id", "parent_id", "bank_ids", "supplier_rank",
        ])
        projection["executor_identity"] = identity_links(self.executor_user, [
            "id", "company_id", "company_ids", "group_ids", "partner_id", "active",
        ])
        projection["executor_partner_links"] = identity_links(self.executor_user.partner_id, [
            "id", "parent_id", "company_id", "bank_ids",
        ])
        projection["attachment_count"] = self.env["ir.attachment"].search_count([])
        self._last_critical_projection = projection
        encoded = json.dumps(projection, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def _unchanged(self, before):
        initial = self._last_critical_projection
        after = self._critical_hash()
        if before != after:
            changed = sorted(key for key in initial if initial[key] != self._last_critical_projection[key])
            # Fixed projection labels only: never print records or values.
            raise AssertionError("Critical projection changed: " + ", ".join(changed))
        type(self).state_observations.append({
            "case": self._testMethodName, "before_sha256": before,
            "after_sha256": after, "unchanged": True,
        })

    def _rpc(self, model, method, payload, *, key="executor"):
        headers = {"X-Odoo-Database": self.env.cr.dbname}
        token = {
            "executor": self.executor_key, "wrong": self.wrong_key,
            "invalid": "TCC-INVALID-SYNTHETIC-KEY", "missing": None,
        }[key]
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        try:
            response = self.url_open(
                "/json/2/" + model + "/" + method,
                json=payload, headers=headers, timeout=15,
                method="POST", allow_redirects=False,
            )
            if self.executor_key in response.text or self.wrong_key in response.text:
                raise AssertionError("A credential appeared in an HTTP response.")
            body = response.json()
        except AssertionError:
            raise
        except Exception:
            raise AssertionError("HTTP probe transport or JSON decoding failed.") from None
        type(self).http_observations.append({
            "case": self._testMethodName, "model": model, "method": method,
            "http_status": response.status_code,
        })
        return response.status_code, body

    def _error(self, model, method, payload, *, status=403, name=_ACCESS_ERROR, key="executor"):
        observed, body = self._rpc(model, method, payload, key=key)
        if observed != status or not isinstance(body, dict) or body.get("name") != name:
            raise AssertionError("HTTP probe did not return the required denial category.")

    def _closed(self, command, *, context=None):
        payload = {"command": command}
        if context is not None:
            payload["context"] = context
        status, body = self._rpc("ap.security.executor", "execute", payload)
        expected = {
            "schema_version": "executor-preflight-result/v1", "decision": "DENY",
            "deny_class": "FAIL_CLOSED_UNAVAILABILITY", "reason_codes": ["DEPENDENCY_UNAVAILABLE"],
            "executor_status": "SCAFFOLD_NOT_READY", "effect_applied": False,
            "proposed_action_hash": _action_hash(command["action"]),
        }
        if status != 200 or body != expected:
            raise AssertionError("HTTP executor did not return the exact closed preflight result.")

    def test_http_valid_create_and_post_are_closed(self):
        before = self._critical_hash()
        self._closed(self._command_for_fixture())
        self._closed(self._command_for_fixture(post=True))
        self._unchanged(before)

    def test_http_invalid_contract_is_validation_denial(self):
        before = self._critical_hash()
        for command in (None, {}, {"context": {"su": True}}):
            self._error("ap.security.executor", "execute", {"command": command},
                        status=422, name=_VALIDATION_ERROR)
        self._unchanged(before)

    def test_http_missing_and_invalid_bearer_are_unauthorized(self):
        before = self._critical_hash()
        for key in ("missing", "invalid"):
            self._error("ap.security.executor", "execute", {"command": self._command_for_fixture()},
                        status=401, name=_UNAUTHORIZED, key=key)
        self._unchanged(before)

    def test_http_user_without_executor_group_is_denied(self):
        before = self._critical_hash()
        self._error("ap.security.executor", "execute", {"command": None}, key="wrong")
        self._unchanged(before)

    def test_http_private_helpers_are_not_remote_methods(self):
        before = self._critical_hash()
        for method in ("_trusted_service", "_preflight", "_check_access"):
            self._error("ap.security.executor", method, {})
        self._unchanged(before)

    def test_http_hostile_context_does_not_change_executor(self):
        before = self._critical_hash()
        contexts = [
            {}, {"allowed_company_ids": self.other_company.ids},
            {"allowed_company_ids": [999999999], "force_company": 999999999},
            {"allowed_company_ids": "hostile", "force_company": False},
            {"allowed_company_ids": self.other_company.ids, "default_company_id": self.other_company.id,
             "default_partner_id": self.vendor.id, "default_move_type": "out_invoice",
             "lang": "hostile_LANG", "tz": "hostile_TZ", "active_test": False,
             "uid": 1, "su": True, "check_move_validity": False, "skip_invoice_sync": True},
        ]
        for context in contexts:
            self._closed(self._command_for_fixture(), context=context)
        self._unchanged(before)

    def test_http_service_crud_is_denied(self):
        before = self._critical_hash()
        self._error("ap.security.executor", "create", {"vals_list": [{}]})
        self._error("ap.security.executor", "write", {"ids": [1], "vals": {}})
        self._error("ap.security.executor", "unlink", {"ids": [1]})
        self._unchanged(before)

    def test_http_bill_and_line_crud_and_post_are_denied(self):
        before = self._critical_hash()
        self._error("account.move", "create", {"vals_list": [copy.deepcopy(self.bill_values)]})
        self._error("account.move", "write", {"ids": self.draft_bill.ids, "vals": {"ref": "TCC-UNAUTHORIZED"}})
        self._error("account.move", "unlink", {"ids": self.draft_bill.ids})
        self._error("account.move", "action_post", {"ids": self.draft_bill.ids})
        self._error("account.move.line", "create", {"vals_list": [{
            "move_id": self.draft_bill.id, "account_id": self.bill_line.account_id.id,
            "name": "TCC-UNAUTHORIZED", "quantity": 1, "price_unit": 1,
        }]})
        self._error("account.move.line", "write", {"ids": self.bill_line.ids, "vals": {"price_unit": 1.0}})
        self._error("account.move.line", "unlink", {"ids": self.bill_line.ids})
        self._unchanged(before)

    def test_http_purchase_crud_and_methods_are_denied(self):
        before = self._critical_hash()
        self._error("purchase.order", "create", {"vals_list": [{
            "partner_id": self.vendor.id, "company_id": self.company.id,
        }]})
        self._error("purchase.order", "write", {"ids": self.purchase.ids, "vals": {"partner_ref": "TCC-UNAUTHORIZED"}})
        self._error("purchase.order", "unlink", {"ids": self.draft_purchase.ids})
        self._error("purchase.order", "button_confirm", {"ids": self.draft_purchase.ids})
        self._error("purchase.order", "button_cancel", {"ids": self.purchase.ids})
        self._error("purchase.order.line", "write", {"ids": self.purchase_line.ids, "vals": {"price_unit": 1.0}})
        self._error("purchase.order.line", "unlink", {"ids": self.purchase_line.ids})
        self._unchanged(before)

    def test_http_supplier_and_bank_crud_are_denied(self):
        before = self._critical_hash()
        self._error("res.partner", "create", {"vals_list": [{"name": "TCC-UNAUTHORIZED", "supplier_rank": 1}]})
        self._error("res.partner", "write", {"ids": self.vendor.ids, "vals": {"name": "TCC-UNAUTHORIZED"}})
        self._error("res.partner", "unlink", {"ids": self.vendor.ids})
        self._error("res.partner.bank", "create", {"vals_list": [{
            "acc_number": "TCC-UNAUTHORIZED-SYNTHETIC", "partner_id": self.vendor.id,
        }]})
        self._error("res.partner.bank", "write", {"ids": self.bank.ids, "vals": {"acc_number": "TCC-UNAUTHORIZED-SYNTHETIC"}})
        self._error("res.partner.bank", "unlink", {"ids": self.bank.ids})
        self._unchanged(before)

    def test_http_bank_trust_has_explicit_native_denial(self):
        before = self._critical_hash()
        self._error("res.partner.bank", "write", {
            "ids": self.bank.ids, "vals": {"allow_out_payment": True},
        }, status=422, name=_USER_ERROR)
        self._unchanged(before)

    def test_http_payment_and_wizard_are_denied(self):
        before = self._critical_hash()
        self._error("account.payment", "create", {"vals_list": [{
            "payment_type": "outbound", "partner_type": "supplier", "partner_id": self.vendor.id,
            "amount": 125.50, "journal_id": self.payment_wizard.journal_id.id,
        }]})
        self._error("account.payment", "write", {"ids": self.draft_payment.ids, "vals": {"amount": 1.0}})
        self._error("account.payment", "unlink", {"ids": self.draft_payment.ids})
        self._error("account.payment", "action_post", {"ids": self.draft_payment.ids})
        self._error("account.payment.register", "create", {"vals_list": [{}], "context": {
            "active_model": "account.move", "active_ids": self.posted_bill.ids,
        }})
        self._error("account.payment.register", "action_create_payments", {"ids": self.payment_wizard.ids})
        self._unchanged(before)

    def test_http_privilege_and_company_assignment_are_invariant(self):
        before = self._critical_hash()
        self._error("res.users", "write", {"ids": self.executor_user.ids, "vals": {
            "group_ids": [[4, self.env.ref("account.group_account_invoice").id]],
        }})
        self._error("res.users", "write", {"ids": self.executor_user.ids, "vals": {
            "company_ids": [[4, self.other_company.id]],
        }})
        # Core allows own company_id preferences but silently discards a
        # company not already allowed; HTTP 200 here is NOT an authority grant.
        status, body = self._rpc("res.users", "write", {"ids": self.executor_user.ids, "vals": {
            "company_id": self.other_company.id,
        }})
        if status != 200 or body is not True:
            raise AssertionError("Own-company preference response changed unexpectedly.")
        self._error("res.users", "write", {"ids": self.executor_user.ids, "vals": {"partner_id": self.vendor.id}})
        self._unchanged(before)

    def test_http_own_safe_field_does_not_alias_financial_partner(self):
        before = self._critical_hash()
        status, body = self._rpc("res.users", "write", {"ids": self.executor_user.ids, "vals": {
            "name": "TCC C1-05 own safe preference - SEM VALOR FISCAL",
        }})
        if status != 200 or body is not True:
            raise AssertionError("Own safe preference was not handled as documented.")
        if self.executor_user.partner_id == self.vendor or self.executor_user.partner_id == self.company.partner_id:
            raise AssertionError("Executor own partner aliases a financial master record.")
        self._unchanged(before)

    def test_http_residual_basic_reads_are_documented(self):
        before = self._critical_hash()
        for model, ids, fields in (
            ("res.partner", self.vendor.ids, ["ref"]),
            ("res.partner.bank", self.bank.ids, ["active"]),
            ("res.company", self.company.ids, ["currency_id"]),
        ):
            status, body = self._rpc(model, "read", {"ids": ids, "fields": fields})
            if status != 200 or not isinstance(body, list) or len(body) != 1:
                raise AssertionError("A documented residual basic read changed.")
        self._unchanged(before)
