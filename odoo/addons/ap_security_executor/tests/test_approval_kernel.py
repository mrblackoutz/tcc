# SPDX-License-Identifier: LGPL-3.0-or-later
"""Real ORM proof of the private C1-07 approval reservation primitive.

Only synthetic technical fixtures, without fiscal value. Keys, nonces and MACs
are runtime-only. No bill is posted and no public financial path is enabled.
These tests do not prove independent-cursor/process concurrency.
"""

import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import secrets
from unittest.mock import patch

from odoo import api
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from .. import approval_kernel
from ..approval import (
    APPROVAL_DOMAIN, ApprovalAuthority, ApprovalKey, ApprovalVerificationError,
    verify_approval,
)
from ..approval_kernel import approval_transaction
from ..identity import provision_executor_identity
from .test_executor import _action_hash, _command


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str).encode("utf-8")


@tagged("post_install", "-at_install", "c1_approval")
class TestApprovalKernel(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other_company = cls.env["res.company"].create({
            "name": "TCC C1-07 OTHER COMPANY - SEM VALOR FISCAL",
        })
        cls.executor_user = provision_executor_identity(
            cls.env, login="tcc-c107-approval-kernel", company=cls.company,
        )
        cls.other_executor = provision_executor_identity(
            cls.env, login="tcc-c107-other-company", company=cls.other_company,
        )

    def setUp(self):
        super().setUp()
        self.now = datetime(2026, 10, 1, 12, 5, tzinfo=timezone.utc)
        self.key = ApprovalKey(
            company_id=self.company.id, key_id="tcc-c107-key-v1", material=secrets.token_bytes(32),
        )
        self.authority = ApprovalAuthority(
            company_id=self.company.id, executor_user_id=self.executor_user.id,
            fixture_id="TCC-C107-APR-001", scenario_id="TCC-SCN-001",
            approver_ref="TCC-C107-SYNTHETIC-APPROVER", nonce=secrets.token_urlsafe(24),
            issued_at="2026-10-01T12:00:00Z", expires_at="2026-10-01T12:10:00Z",
            key_id=self.key.key_id,
        )
        self.command = self._signed_command()
        self.trusted_action = copy.deepcopy(self.command["action"])

    def _signed_command(self, *, authority=None, key=None, action_changes=None):
        registered = authority or self.authority
        selected = key or self.key
        command = _command(post=True)
        command["action"]["scenario_id"] = registered.scenario_id
        if action_changes:
            command["action"].update(action_changes)
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
            selected.material, APPROVAL_DOMAIN + _bytes({"company_id": registered.company_id, "approval": unsigned}), hashlib.sha256,
        ).hexdigest()
        command["approval"] = {**unsigned, "signature": signature}
        return command

    def _args(self, **changes):
        value = {
            "command": self.command, "trusted_action": self.trusted_action,
            "authority": self.authority, "key": self.key, "now": self.now,
        }
        value.update(changes)
        return value

    def _ledger(self):
        return self.env["ap.security.approval.nonce"].sudo().with_context(active_test=False)

    def _state_hash(self):
        fields = [
            "company_id", "executor_user_id", "key_id", "fixture_id", "scenario_id", "approver_ref",
            "nonce_sha256", "action_sha256", "approval_sha256", "command_sha256", "state",
            "verified_at", "expires_at", "consumed_at",
        ]
        projection = {
            "ledger": self._ledger().search([], order="id").read(fields),
            "effects": {
                model: self.env[model].sudo().with_context(active_test=False).search_count([])
                for model in ("account.move", "account.move.line", "account.payment", "ir.attachment", "mail.mail", "mail.notification")
            },
        }
        return hashlib.sha256(_bytes(projection)).hexdigest()

    def _negative(self, *, code, env=None, **changes):
        before = self._state_hash()
        # Deliberately NO enclosing test savepoint: rollback must be performed
        # by the implementation's own transaction context manager.
        with self.assertRaises(ApprovalVerificationError) as caught:
            with approval_transaction(env or self.env, **self._args(**changes)):
                self.fail("An invalid technical approval opened the operation body.")
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn("SENSITIVE-MARKER", str(caught.exception))
        self.assertEqual(self._state_hash(), before)

    def _consume(self, *, env=None, **changes):
        with approval_transaction(env or self.env, **self._args(**changes)) as reservation:
            ledger = self._ledger().browse(reservation.ledger_id)
            self.assertTrue(ledger.exists())
            self.assertEqual(ledger.state, "reserved")
            self.assertFalse(ledger.consumed_at)
            self.assertEqual(reservation.action_hash, _action_hash(self.trusted_action if "trusted_action" not in changes else changes["trusted_action"]))
        return reservation

    def test_valid_mac_reserves_then_consumes_without_financial_effects(self):
        effects = {model: self.env[model].sudo().search_count([]) for model in ("account.move", "account.move.line", "account.payment", "ir.attachment", "mail.mail", "mail.notification")}
        verified = verify_approval(**self._args())
        reservation = self._consume()
        ledger = self._ledger().browse(reservation.ledger_id)
        self.assertEqual(ledger.state, "consumed")
        self.assertTrue(ledger.consumed_at)
        self.assertEqual(ledger.company_id.id, self.company.id)
        self.assertEqual(ledger.executor_user_id.id, self.executor_user.id)
        self.assertEqual(ledger.nonce_sha256, verified.nonce_sha256)
        self.assertEqual(ledger.action_sha256, verified.action_hash)
        self.assertEqual(ledger.approval_sha256, reservation.approval_sha256)
        self.assertEqual(ledger.command_sha256, reservation.command_sha256)
        self.assertEqual(ledger.verified_at, self.now.replace(tzinfo=None))
        self.assertEqual(ledger.expires_at, datetime(2026, 10, 1, 12, 10))
        self.assertEqual(ledger.consumed_at, self.now.replace(tzinfo=None))
        self.assertEqual({model: self.env[model].sudo().search_count([]) for model in effects}, effects)

    def test_consumed_nonce_reuse_is_denied_without_state_change(self):
        self._consume()
        self._negative(code="NONCE_REUSED")

    def test_nested_attempt_cannot_reuse_a_currently_reserved_nonce(self):
        with approval_transaction(self.env, **self._args()):
            self._negative(code="NONCE_REUSED")
        self.assertEqual(self._ledger().search_count([("state", "=", "consumed")]), 1)

    def test_nonce_uniqueness_is_global_across_key_rotation(self):
        self._consume()
        authority = replace(self.authority, key_id="tcc-c107-other-key-v1")
        key = ApprovalKey(company_id=self.company.id, key_id=authority.key_id, material=secrets.token_bytes(32))
        self._negative(code="NONCE_REUSED", authority=authority, key=key, command=self._signed_command(authority=authority, key=key))

    def test_nonce_uniqueness_is_global_across_scenarios(self):
        self._consume()
        authority = replace(self.authority, fixture_id="TCC-C107-APR-OTHER", scenario_id="TCC-SCN-OTHER")
        command = self._signed_command(authority=authority)
        self._negative(code="NONCE_REUSED", authority=authority, command=command, trusted_action=command["action"])

    def test_nonce_uniqueness_is_global_across_companies(self):
        self._consume()
        authority = replace(self.authority, company_id=self.other_company.id, executor_user_id=self.other_executor.id)
        key = ApprovalKey(company_id=self.other_company.id, key_id=authority.key_id, material=secrets.token_bytes(32))
        command = self._signed_command(authority=authority, key=key)
        self._negative(code="NONCE_REUSED", authority=authority, key=key, command=command, trusted_action=command["action"])

    def test_new_nonce_can_be_consumed_as_a_distinct_registered_fixture(self):
        first = self._consume()
        authority = replace(self.authority, nonce=secrets.token_urlsafe(24), fixture_id="TCC-C107-APR-OTHER")
        command = self._signed_command(authority=authority)
        second = self._consume(authority=authority, command=command)
        self.assertNotEqual(first.ledger_id, second.ledger_id)
        self.assertEqual(self._ledger().search_count([("state", "=", "consumed")]), 2)

    def test_operation_failure_rolls_back_reservation_and_body_then_allows_retry(self):
        before = self._state_hash()
        with self.assertRaisesRegex(RuntimeError, "^Synthetic operation fault$"):
            with approval_transaction(self.env, **self._args()):
                self.env["ir.attachment"].sudo().create({
                    "name": "TCC-C107-SYNTHETIC-ROLLBACK-SEM-VALOR-FISCAL",
                    "raw": b"SEM VALOR FISCAL", "mimetype": "text/plain",
                })
                raise RuntimeError("Synthetic operation fault")
        self.assertEqual(self._state_hash(), before)
        self._consume()

    def test_fault_after_nonce_consumption_rolls_back_consumption_and_allows_retry(self):
        before = self._state_hash()
        observed_states = []

        def fail_after_consumption(record):
            observed_states.append(record.state)
            raise RuntimeError("Synthetic post-consumption fault")

        with patch.object(approval_kernel, "_after_nonce_consume", side_effect=fail_after_consumption):
            with self.assertRaisesRegex(RuntimeError, "^Synthetic post-consumption fault$"):
                with approval_transaction(self.env, **self._args()):
                    pass
        self.assertEqual(observed_states, ["consumed"])
        self.assertEqual(self._state_hash(), before)
        self._consume()

    def test_body_cannot_delete_its_reservation_and_still_succeed(self):
        before = self._state_hash()
        with self.assertRaises(ApprovalVerificationError) as caught:
            with approval_transaction(self.env, **self._args()) as reservation:
                self._ledger().browse(reservation.ledger_id).unlink()
        self.assertEqual(caught.exception.code, "RESERVATION_INVALID")
        self.assertEqual(self._state_hash(), before)

    def test_body_cannot_change_reservation_binding_and_still_succeed(self):
        before = self._state_hash()
        with self.assertRaises(ApprovalVerificationError) as caught:
            with approval_transaction(self.env, **self._args()) as reservation:
                self._ledger().browse(reservation.ledger_id).write({"action_sha256": "sha256:" + "f" * 64})
        self.assertEqual(caught.exception.code, "RESERVATION_INVALID")
        self.assertEqual(self._state_hash(), before)

    def test_malformed_signature_is_rejected_before_reservation(self):
        command = copy.deepcopy(self.command)
        command["approval"]["signature"] = "SENSITIVE-MARKER"
        self._negative(code="SIGNATURE_INVALID", command=command)

    def test_wrong_runtime_key_is_rejected_before_reservation(self):
        key = ApprovalKey(company_id=self.company.id, key_id=self.key.key_id, material=secrets.token_bytes(32))
        self._negative(code="SIGNATURE_INVALID", key=key)

    def test_changed_target_move_or_beneficiary_is_rejected_before_reservation(self):
        for changes in ({"target_move_id": 124}, {"recipient_bank_ref": "TCC-C107-OTHER-BANK"}):
            trusted = copy.deepcopy(self.trusted_action)
            trusted.update(changes)
            self._negative(code="BINDING_MISMATCH", trusted_action=trusted)

    def test_unknown_contract_is_rejected_before_reservation(self):
        command = copy.deepcopy(self.command)
        command["approval"]["schema_version"] = "SENSITIVE-MARKER"
        self._negative(code="CONTRACT_INVALID", command=command)

    def test_future_and_expired_approvals_never_reserve(self):
        self._negative(code="NOT_YET_VALID", now=datetime(2026, 10, 1, 11, 59, 59, tzinfo=timezone.utc))
        self._negative(code="EXPIRED", now=datetime(2026, 10, 1, 12, 10, tzinfo=timezone.utc))

    def test_policy_window_is_independent_of_valid_fixture(self):
        command = copy.deepcopy(self.command)
        command["policy_decision"]["expires_at"] = "2026-10-01T12:05:00Z"
        self._negative(code="EXPIRED", command=command)
        command["policy_decision"].update(evaluated_at="2026-10-01T12:06:00Z", expires_at="2026-10-01T12:10:00Z")
        self._negative(code="NOT_YET_VALID", command=command)

    def test_missing_key_authority_and_clock_fail_closed(self):
        self._negative(code="DEPENDENCY_UNAVAILABLE", key=None)
        self._negative(code="DEPENDENCY_UNAVAILABLE", authority=None)
        self._negative(code="DEPENDENCY_UNAVAILABLE", now=None)
        self._negative(code="DEPENDENCY_UNAVAILABLE", now=self.now.replace(tzinfo=None))
        self._negative(code="DEPENDENCY_UNAVAILABLE", now=datetime(2026, 10, 1, 14, 5, tzinfo=timezone(timedelta(hours=2))))

    def test_deleted_configuration_slots_fail_closed_before_any_reservation(self):
        object.__delattr__(self.key, "material")
        self._negative(code="DEPENDENCY_UNAVAILABLE")
        self.key = ApprovalKey(company_id=self.company.id, key_id=self.authority.key_id, material=secrets.token_bytes(32))
        object.__delattr__(self.authority, "nonce")
        self._negative(code="DEPENDENCY_UNAVAILABLE")

    def test_executor_from_another_company_or_archived_identity_is_rejected(self):
        authority = replace(self.authority, executor_user_id=self.other_executor.id)
        self._negative(code="IDENTITY_INVALID", authority=authority)
        self.executor_user.active = False
        self._negative(code="IDENTITY_INVALID")

    def test_executor_with_financial_group_is_rejected(self):
        group = self.env.ref("account.group_account_invoice")
        self.executor_user.write({"group_ids": [(4, group.id)]})
        self._negative(code="IDENTITY_INVALID")

    def test_executor_has_zero_direct_ledger_permissions(self):
        user_env = api.Environment(self.env.cr, self.executor_user.id, {}, su=False)
        for operation in ("read", "create", "write", "unlink"):
            with self.assertRaises(AccessError):
                user_env["ap.security.approval.nonce"].check_access(operation)

    def test_non_administrator_cannot_enter_private_transaction(self):
        before = self._state_hash()
        user_env = api.Environment(self.env.cr, self.executor_user.id, {}, su=False)
        with self.assertRaises(AccessError):
            with approval_transaction(user_env, **self._args()):
                self.fail("Non-administrative caller entered private transaction.")
        self.assertEqual(self._state_hash(), before)

    def test_hostile_context_cannot_redirect_or_rewrite_ledger_values(self):
        hostile = self.env(context={
            "allowed_company_ids": [self.other_company.id], "force_company": self.other_company.id,
            "default_company_id": self.other_company.id, "default_state": "consumed",
            "default_executor_user_id": self.other_executor.id, "active_test": False,
            "lang": "pt_BR", "tz": "Pacific/Honolulu",
        })
        reservation = self._consume(env=hostile)
        ledger = self._ledger().browse(reservation.ledger_id)
        self.assertEqual(ledger.company_id.id, self.company.id)
        self.assertEqual(ledger.executor_user_id.id, self.executor_user.id)

    def test_personal_defaults_are_not_used_and_global_defaults_are_denied(self):
        defaults = self.env["ir.default"].sudo()
        defaults.set("ap.security.approval.nonce", "key_id", "personal-poison-key-v1", user_id=self.executor_user.id, company_id=self.company.id)
        reservation = self._consume()
        self.assertEqual(self._ledger().browse(reservation.ledger_id).key_id, self.key.key_id)
        defaults.set("ap.security.approval.nonce", "state", "consumed", user_id=False, company_id=self.company.id)
        authority = replace(self.authority, nonce=secrets.token_urlsafe(24), fixture_id="TCC-C107-APR-OTHER")
        self._negative(code="DEPENDENCY_UNAVAILABLE", authority=authority, command=self._signed_command(authority=authority))

    def test_service_defaults_are_denied_without_auto_repair(self):
        defaults = self.env["ir.default"].sudo()
        defaults.set("ap.security.approval.nonce", "fixture_id", "TCC-POISON-FIXTURE", user_id=1, company_id=self.company.id)
        count = defaults.search_count([])
        self._negative(code="DEPENDENCY_UNAVAILABLE")
        self.assertEqual(defaults.search_count([]), count)

    def test_ledger_contains_only_metadata_and_hashes_not_raw_grants(self):
        reservation = self._consume()
        model = self._ledger()
        self.assertFalse({"signature", "nonce", "material", "token", "approval", "command"} & set(model._fields))
        ledger = model.browse(reservation.ledger_id)
        projection = _bytes(ledger.read([
            "key_id", "fixture_id", "scenario_id", "approver_ref", "nonce_sha256",
            "action_sha256", "approval_sha256", "command_sha256", "state",
        ]))
        self.assertFalse(self.authority.nonce.encode("utf-8") in projection)
        self.assertFalse(self.command["approval"]["signature"].encode("utf-8") in projection)
        self.assertFalse(self.key.material in projection)

    def test_public_executor_stays_closed_even_with_a_valid_signed_approval(self):
        before = self._state_hash()
        result = self.env["ap.security.executor"].with_user(self.executor_user).execute(self.command)
        self.assertFalse(result["effect_applied"])
        self.assertEqual(result["decision"], "DENY")
        self.assertEqual(result["executor_status"], "SCAFFOLD_NOT_READY")
        self.assertEqual(result["reason_codes"], ["DEPENDENCY_UNAVAILABLE"])
        self.assertEqual(self._state_hash(), before)
