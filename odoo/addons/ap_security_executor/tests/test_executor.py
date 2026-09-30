# SPDX-License-Identifier: LGPL-3.0-or-later
"""Real Odoo tests of the C1-04 boundary, not of future financial execution.

All payloads and users below are synthetic and have no fiscal value. The
fixtures are built independently of the gateway so the add-on remains usable
without installing the gateway or its dependencies in Odoo.
"""

import copy
import hashlib
import json

from odoo import SUPERUSER_ID, api
from odoo.exceptions import AccessError, ValidationError
from odoo.service.model import get_public_method
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user

from ..models.executor import ApSecurityExecutor


def _action_hash(action):
    encoded = json.dumps(
        action, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _command(*, post=False):
    """Closed, structurally valid data; these are not authenticated grants."""
    action = {
        "canonicalization_version": "canon/v1",
        "action_schema_version": "vendor-bill-action-proposal/v2",
        "policy_version": "policy-v1.0.0",
        "action": "POST_VENDOR_BILL" if post else "CREATE_DRAFT_BILL",
        "executor_mode": "POST_APPROVED" if post else "CREATE_DRAFT",
        "scenario_id": "TCC-SCN-001",
        "document_sha256": "a" * 64,
        "vendor_ref": "TCC-VENDOR-001",
        "purchase_order_ref": "TCC-PO-001",
        "document_ref": "TCC-NF-001-SEM-VALOR-FISCAL",
        "invoice_date": "2026-09-30",
        "currency": "BRL",
        "amount": "125.50",
        "recipient_bank_ref": "TCC-BANK-001",
        "lines": [{
            "item_code": "TCC-SERVICE-001", "quantity": "1.00",
            "unit_price": "125.50",
        }],
    }
    if post:
        action["target_move_id"] = 123
    digest = _action_hash(action)
    command = {
        "schema_version": "capability-command/v1",
        "action": action,
        "policy_decision": {
            "schema_version": "policy-decision/v1",
            "decision": "REVIEW" if post else "ALLOW",
            "reason_codes": [
                "CRITICAL_ACTION_REQUIRES_APPROVAL" if post else "DRAFT_CONSISTENT",
            ],
            "proposed_action_hash": digest,
            "input_sha256": "sha256:" + "b" * 64,
            "policy_version": "policy-v1.0.0",
            "allowed_executor": "post_bill_executor" if post else "create_bill_executor",
            "deny_class": None,
            # Deliberately expired. Structural preflight must not invent a
            # current authorization: C1-07 must verify expiry and authenticity.
            "evaluated_at": "2020-01-01T00:00:00Z",
            "expires_at": "2020-01-01T00:05:00Z",
        },
        "idempotency_key": "sha256:" + "c" * 64,
    }
    if post:
        command["approval"] = {
            "fixture_id": "TCC-APPROVAL-001",
            "scenario_id": "TCC-SCN-001",
            "approver_ref": "TCC-SIMULATED-REVIEWER",
            "decision": "APPROVE",
            "canonical_action_hash": digest,
            "nonce": "TCC-SYNTHETIC-NONCE",
            "issued_at": "2020-01-01T00:00:00Z",
            "expires_at": "2020-01-01T00:05:00Z",
            "key_id": "test-key-v1",
            "signature": "TCC-UNSIGNED-SYNTHETIC-FIXTURE",
        }
    return command


@tagged("post_install", "-at_install")
class TestExecutorBoundary(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.primary_company = cls.env["res.company"].create({
            "name": "TCC C1-04 PRIMARY SYNTHETIC",
        })
        cls.other_company = cls.env["res.company"].create({
            "name": "TCC C1-04 OTHER SYNTHETIC",
        })
        cls.executor_user = new_test_user(
            cls.env, login="tcc-c104-executor",
            groups="base.group_user,ap_security_executor.group_executor",
            company_id=cls.primary_company.id,
            company_ids=[(6, 0, [cls.primary_company.id, cls.other_company.id])],
            name="TCC synthetic executor test user",
        )
        cls.unauthorized_user = new_test_user(
            cls.env, login="tcc-c104-no-group", groups="base.group_user",
            company_id=cls.primary_company.id,
            name="TCC synthetic unauthorized test user",
        )

    def _service(self, user=None):
        return self.env["ap.security.executor"].with_user(user or self.executor_user)

    def _effect_counts(self):
        return {
            model: self.env[model].with_context(active_test=False).search_count([])
            for model in ("account.move", "account.move.line", "ir.attachment")
        }

    def _assert_closed_result(self, result, command):
        self.assertEqual(result, {
            "schema_version": "executor-preflight-result/v1",
            "decision": "DENY",
            "deny_class": "FAIL_CLOSED_UNAVAILABILITY",
            "reason_codes": ["DEPENDENCY_UNAVAILABLE"],
            "executor_status": "SCAFFOLD_NOT_READY",
            "effect_applied": False,
            "proposed_action_hash": _action_hash(command["action"]),
        })

    def test_valid_create_denies_without_financial_or_attachment_effects(self):
        command = _command()
        before = self._effect_counts()
        self._assert_closed_result(self._service().execute(command), command)
        self.assertEqual(self._effect_counts(), before)

    def test_valid_post_and_opaque_approval_do_not_authorize_effects(self):
        command = _command(post=True)
        before = self._effect_counts()
        self._assert_closed_result(self._service().execute(command), command)
        self.assertEqual(self._effect_counts(), before)

    def test_repeated_request_has_no_effect_or_persisted_receipt(self):
        command = _command()
        before = self._effect_counts()
        first = self._service().execute(command)
        self.assertEqual(self._service().execute(copy.deepcopy(command)), first)
        self.assertEqual(self._effect_counts(), before)
        self.assertTrue(self._service()._abstract)
        self.assertFalse(self._service()._auto)

    def test_input_dictionary_is_not_modified(self):
        for post in (False, True):
            with self.subTest(post=post):
                command = _command(post=post)
                original = copy.deepcopy(command)
                self._service().execute(command)
                self.assertEqual(command, original)

    def test_group_has_no_implied_privilege_groups(self):
        group = self.env.ref("ap_security_executor.group_executor")
        self.assertFalse(group.implied_ids)
        acl = self.env.ref("ap_security_executor.access_executor_read")
        self.assertTrue(acl.active)
        self.assertEqual(acl.model_id.model, "ap.security.executor")
        self.assertEqual(acl.group_id, group)
        self.assertTrue(acl.perm_read)
        self.assertFalse(acl.perm_create or acl.perm_write or acl.perm_unlink)

    def test_generic_service_crud_is_denied_by_actual_acl(self):
        service = self._service()
        service.check_access("read")
        for operation in ("create", "write", "unlink"):
            with self.subTest(operation=operation):
                with self.assertRaises(AccessError):
                    service.check_access(operation)
        with self.assertRaises(AccessError):
            service.create({})
        # Nonempty handles force ACL evaluation. Empty write/unlink are ORM
        # no-ops and must not be mistaken for authorized critical mutations.
        with self.assertRaises(AccessError):
            service.browse(1).write({})
        with self.assertRaises(AccessError):
            service.browse(1).unlink()

    def test_unauthorized_internal_user_is_denied_before_payload_parsing(self):
        with self.assertRaises(AccessError) as caught:
            self._service(self.unauthorized_user).execute(None)
        self.assertEqual(str(caught.exception), "Executor access denied.")

    def test_public_user_is_denied(self):
        with self.assertRaises(AccessError) as caught:
            self._service(self.env.ref("base.public_user")).execute(_command())
        self.assertEqual(str(caught.exception), "Executor access denied.")

    def test_superuser_is_denied_even_when_given_executor_group(self):
        superuser = self.env["res.users"].browse(SUPERUSER_ID)
        superuser.write({
            "group_ids": [(4, self.env.ref("ap_security_executor.group_executor").id)],
        })
        with self.assertRaises(AccessError) as caught:
            self._service(superuser).execute(_command())
        self.assertEqual(str(caught.exception), "Executor access denied.")

    def test_sudo_executor_user_is_denied(self):
        with self.assertRaises(AccessError) as caught:
            self._service().sudo().execute(_command())
        self.assertEqual(str(caught.exception), "Executor access denied.")

    def test_inactive_executor_user_is_denied(self):
        self.executor_user.write({"active": False})
        with self.assertRaises(AccessError) as caught:
            self._service().execute(_command())
        self.assertEqual(str(caught.exception), "Executor access denied.")

    def test_group_membership_without_read_acl_is_denied(self):
        acl = self.env.ref("ap_security_executor.access_executor_read")
        with self.cr.savepoint():
            acl.write({"active": False})
            try:
                with self.assertRaises(AccessError) as caught:
                    self._service().execute(_command())
                self.assertEqual(str(caught.exception), "Executor access denied.")
            finally:
                acl.write({"active": True})
        self._assert_closed_result(self._service().execute(_command()), _command())

    def test_hostile_context_is_replaced_not_merged(self):
        contexts = [
            {"allowed_company_ids": [self.other_company.id]},
            {"allowed_company_ids": [999999999], "force_company": 999999999},
            {"allowed_company_ids": "not-an-id-list", "force_company": False},
            {
                "allowed_company_ids": [self.other_company.id],
                "force_company": self.other_company.id,
                "default_company_id": self.other_company.id,
                "default_partner_id": 999999999, "default_move_type": "out_invoice",
                "lang": "hostile_LANG", "tz": "hostile_TZ", "active_test": False,
                "tracking_disable": True, "check_move_validity": False,
                "skip_invoice_sync": True, "mail_create_nolog": True,
                "uid": SUPERUSER_ID, "su": True,
            },
        ]
        before = self._effect_counts()
        for context in contexts:
            with self.subTest(context_keys=sorted(context)):
                hostile = self._service().with_context(context)
                trusted = hostile._trusted_service()
                self.assertEqual(dict(trusted.env.context), {
                    "allowed_company_ids": [self.primary_company.id],
                    "force_company": self.primary_company.id,
                    "lang": "en_US", "tz": "UTC", "active_test": True,
                })
                self.assertEqual(trusted.env.company, self.primary_company)
                self.assertEqual(trusted.env.uid, self.executor_user.id)
                self.assertFalse(trusted.env.su)
                for post in (False, True):
                    command = _command(post=post)
                    self._assert_closed_result(hostile.execute(command), command)
        self.assertEqual(self._effect_counts(), before)

    def test_only_custom_public_method_is_execute(self):
        custom_public = {
            name for name, member in ApSecurityExecutor.__dict__.items()
            if callable(member) and not name.startswith("_")
        }
        self.assertEqual(custom_public, {"execute"})
        self.assertIsNotNone(get_public_method(self._service(), "execute"))
        for name in ("_trusted_service", "_preflight"):
            with self.subTest(method=name):
                with self.assertRaises(AccessError):
                    get_public_method(self._service(), name)

    def test_top_level_invalid_payloads_have_sanitized_errors(self):
        before = self._effect_counts()
        for payload in (None, True, [], "UNTRUSTED-TEST-PAYLOAD", {}):
            with self.subTest(payload_type=type(payload).__name__):
                with self.assertRaises(ValidationError) as caught:
                    self._service().execute(payload)
                self.assertEqual(str(caught.exception), "Invalid capability command.")
        self.assertEqual(self._effect_counts(), before)

    def test_nested_invalid_fields_have_sanitized_errors_and_no_effect(self):
        malformed = []
        value = _command()
        value["context"] = {"default_partner_id": 123}
        malformed.append(("command_context", value))
        value = _command()
        value["action"]["description"] = "UNTRUSTED-TEST-PAYLOAD"
        malformed.append(("extra_action_field", value))
        value = _command()
        value["action"]["lines"][0]["quantity"] = 1.0
        malformed.append(("float_quantity", value))
        value = _command()
        value["action"]["amount"] = "125.51"
        malformed.append(("changed_amount", value))
        value = _command()
        value["policy_decision"]["proposed_action_hash"] = "sha256:" + "d" * 64
        malformed.append(("changed_decision_hash", value))
        value = _command()
        value["policy_decision"]["allowed_executor"] = "post_bill_executor"
        malformed.append(("wrong_executor", value))
        value = _command(post=True)
        value["action"]["target_move_id"] = True
        malformed.append(("boolean_target_id", value))
        value = _command(post=True)
        value.pop("approval")
        malformed.append(("missing_approval", value))
        value = _command(post=True)
        value["approval"]["scenario_id"] = "TCC-SCN-002"
        malformed.append(("changed_approval_scenario", value))
        value = _command(post=True)
        value["approval"]["canonical_action_hash"] = "sha256:" + "e" * 64
        malformed.append(("changed_approval_hash", value))
        value = _command(post=True)
        value["approval"]["signature"] = "TCC-TEST-INVALID" * 400
        malformed.append(("oversized_opaque_approval", value))
        before = self._effect_counts()
        for label, payload in malformed:
            with self.subTest(case=label):
                with self.assertRaises(ValidationError) as caught:
                    self._service().execute(payload)
                self.assertEqual(str(caught.exception), "Invalid capability command.")
        self.assertEqual(self._effect_counts(), before)

    def test_acl_and_context_use_real_non_superuser_environment(self):
        neutral = api.Environment(self.cr, self.executor_user.id, {}, su=False)
        self.assertFalse(neutral.su)
        service = neutral["ap.security.executor"]
        self.assertTrue(service.has_access("read"))
        self.assertFalse(service.has_access("write"))
        self._assert_closed_result(service.execute(_command()), _command())
