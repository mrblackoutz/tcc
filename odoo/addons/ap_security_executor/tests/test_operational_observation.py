# SPDX-License-Identifier: LGPL-3.0-or-later
"""Candidate-bound reads over real synthetic ORM state, without effects.

TransactionCase is not proof of a native external commit, an independent
cursor, scientific readiness, or future availability of the audit writer.
"""

import copy
from dataclasses import replace
from datetime import date, datetime, timezone
import hashlib
from unittest.mock import patch

from psycopg2.errors import SerializationFailure
from psycopg2.extras import Json

from odoo import Command, SUPERUSER_ID
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from .. import operational_observation, registered_post, workflow_registry
from ..audit_contracts import audit_digest
from ..contracts import _bytes, canonical_action_bytes
from ..workflow_contracts import WorkflowProvenance
from .test_audit_kernel import AuditFixtureMixin
from .test_workflow_registry import TestWorkflowRegistration


@tagged("post_install", "-at_install", "c1_observation")
class TestOperationalObservation(AuditFixtureMixin, TransactionCase):
    _financial_projection = TestWorkflowRegistration._financial_projection

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "TCC OBSERVATION EMPLOYEE - SEM VALOR FISCAL",
            "login": "tcc-operational-observation-employee", "company_id": cls.company.id,
            "company_ids": [Command.set(cls.company.ids)],
            "group_ids": [Command.set([cls.env.ref("base.group_user").id])],
        })

    def setUp(self):
        super().setUp()
        self.provenance = WorkflowProvenance(**{name: getattr(self.audit, name) for name in (
            "code_commit", "code_sha256", "configuration_sha256")})
        self.registration = workflow_registry.register_draft_workflow(self.env,
            workflow=self.draft_workflow, document=self.document, provenance=self.provenance)

    def _observe(self, *, env=None, action=None, **changes):
        arguments = dict(registration_id=self.registration.registration_id,
            expected_company_id=self.company.id, expected_executor_user_id=self.executor_user.id,
            expected_scenario_id=self.draft_workflow.scenario_id, document=self.document,
            provenance=self.provenance,
            canonical_action=copy.deepcopy(self.draft_command["action"] if action is None else action))
        arguments.update(changes)
        before = self._financial_projection()
        pending = self.env.cr.postcommit
        callbacks = tuple(pending._funcs)
        try:
            return operational_observation.observe_registered_policy_state(
                self.env if env is None else env, **arguments)
        finally:
            self.assertEqual(self._financial_projection(), before)
            self.assertIs(self.env.cr.postcommit, pending)
            self.assertEqual(tuple(pending._funcs), callbacks)

    def _error(self, operation, *, code, error_type=operational_observation.OperationalObservationError):
        with self.assertRaises(error_type) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn("SENSITIVE", str(caught.exception))

    def _bill(self, *, ref=None, company=None, vendor=None, move_type="in_invoice"):
        company = self.company if company is None else company
        vendor = self.vendor if vendor is None else vendor
        journal = self.journal
        if company != self.company:
            journal = self.env["account.journal"].create({
                "name": "TCC OBSERVATION FOREIGN PURCHASE - SEM VALOR FISCAL", "code": "TCOP",
                "type": "purchase", "company_id": company.id,
            })
        return self.env["account.move"].with_context(
            allowed_company_ids=[company.id], force_company=company.id,
            tracking_disable=True, mail_create_nolog=True, mail_create_nosubscribe=True,
        ).create({"company_id": company.id, "partner_id": vendor.id, "journal_id": journal.id,
            "move_type": move_type, "ref": self.draft_command["action"]["document_ref"] if ref is None else ref,
            "invoice_date": self.draft_command["action"]["invoice_date"]})

    def _post_action(self):
        self._prepare_post()
        return copy.deepcopy(self.registered_action)

    def test_closed_binding_and_hash_from_real_reads(self):
        action = copy.deepcopy(self.draft_command["action"])
        observed = self._observe(action=action)
        self.assertEqual(set(observed), {"schema_version", "registration", "provenance", "scope",
            "facts", "preflight", "observed_at", "observation_sha256"})
        self.assertEqual(observed["schema_version"], "registered-operational-observation/v1")
        self.assertEqual(observed["registration"], {"registration_id": self.registration.registration_id,
            "registration_sha256": self.registration.registration_sha256})
        scope = observed["scope"]
        self.assertEqual(set(scope), {"company_id", "executor_user_id", "vendor_id", "purchase_order_id",
            "purchase_line_ids", "journal_id", "allowed_bank_ids", "scenario_id", "document_sha256",
            "policy_version", "invoice_date_min", "invoice_date_max", "monetary_tolerance", "quantity_scale",
            "executor_mode", "action_sha256", "document_ref", "invoice_date", "target_move_id"})
        for field, value in {
            "company_id": self.company.id, "executor_user_id": self.executor_user.id,
            "vendor_id": self.vendor.id, "purchase_order_id": self.purchase.id,
            "purchase_line_ids": sorted(self.purchase_line.ids), "journal_id": self.journal.id,
            "allowed_bank_ids": [self.bank.id], "invoice_date_min": "2026-09-01",
            "invoice_date_max": "2026-09-30", "monetary_tolerance": "0.00", "quantity_scale": 2,
            "executor_mode": "CREATE_DRAFT", "target_move_id": None,
        }.items():
            self.assertEqual(scope[field], value)
        self.assertEqual(scope["action_sha256"], "sha256:" + hashlib.sha256(canonical_action_bytes(action)).hexdigest())
        self.assertEqual(observed["facts"], {"document_duplicate": False, "reference_duplicate": False,
            "duplicate_detected": False, "accounting_period_open": True})
        self.assertEqual(observed["preflight"], {"state": "AVAILABLE", "audit": "AVAILABLE"})
        instant = datetime.fromisoformat(observed["observed_at"].replace("Z", "+00:00"))
        self.assertEqual(instant.tzinfo, timezone.utc)
        body = {key: value for key, value in observed.items() if key != "observation_sha256"}
        self.assertEqual(observed["observation_sha256"], "sha256:" + hashlib.sha256(
            b"tcc-operational-observation/v1\0" + _bytes(body)).hexdigest())
        self.assertEqual(action, self.draft_command["action"])

    def test_reference_change_is_preserved_and_candidate_bound(self):
        self._bill()
        first = self._observe()
        action = {**self.draft_command["action"], "document_ref": "TCC-NEW-REFERENCE"}
        second = self._observe(action=action)
        self.assertIs(first["facts"]["reference_duplicate"], True)
        self.assertIs(second["facts"]["reference_duplicate"], False)
        self.assertEqual(second["scope"]["document_ref"], "TCC-NEW-REFERENCE")
        self.assertNotEqual(first["scope"]["action_sha256"], second["scope"]["action_sha256"])
        self.assertEqual(action["document_ref"], "TCC-NEW-REFERENCE")

    def test_amount_vendor_bank_mismatch_remains_candidate_for_policy(self):
        action = copy.deepcopy(self.draft_command["action"])
        action.update({"amount": "124.50", "vendor_ref": self.other_vendor.ref,
            "recipient_bank_ref": self.other_bank.acc_number})
        action["lines"][0]["unit_price"] = "124.50"
        observed = self._observe(action=action)
        self.assertEqual(observed["scope"]["vendor_id"], self.vendor.id)
        self.assertEqual(observed["scope"]["allowed_bank_ids"], [self.bank.id])
        self.assertEqual(observed["scope"]["action_sha256"], "sha256:" + hashlib.sha256(canonical_action_bytes(action)).hexdigest())
        self.assertEqual(action["amount"], "124.50")
        self.assertIs(observed["facts"]["accounting_period_open"], True)

    def test_candidate_date_changes_period_without_repair(self):
        self.company.fiscalyear_lock_date = "2026-09-20"
        closed = {**self.draft_command["action"], "invoice_date": "2026-09-19"}
        opened = {**self.draft_command["action"], "invoice_date": "2026-09-30"}
        first = self._observe(action=closed); second = self._observe(action=opened)
        self.assertIs(first["facts"]["accounting_period_open"], False)
        self.assertIs(second["facts"]["accounting_period_open"], True)
        self.assertEqual(first["scope"]["invoice_date"], "2026-09-19")
        self.assertNotEqual(first["scope"]["action_sha256"], second["scope"]["action_sha256"])

    def test_outside_window_date_is_not_rewritten(self):
        action = {**self.draft_command["action"], "invoice_date": "2026-10-01"}
        observed = self._observe(action=action)
        self.assertEqual(observed["scope"]["invoice_date"], "2026-10-01")
        self.assertEqual(observed["scope"]["invoice_date_max"], "2026-09-30")

    def test_document_ledger_duplicate_survives_reference_change(self):
        self._created()
        observed = self._observe(action={**self.draft_command["action"], "document_ref": "TCC-CHANGED-REF"})
        self.assertIs(observed["facts"]["document_duplicate"], True)
        self.assertIs(observed["facts"]["reference_duplicate"], False)
        self.assertIs(observed["facts"]["duplicate_detected"], True)

    def test_ledger_idempotency_key_detects_different_document_hash(self):
        result = self._created()
        self.env["ap.security.draft.receipt"].browse(result["receipt"]["receipt_id"]).document_sha256 = "d" * 64
        observed = self._observe(action={**self.draft_command["action"], "document_ref": "TCC-CHANGED-REF"})
        self.assertIs(observed["facts"]["document_duplicate"], True)

    def test_ledger_document_hash_detects_different_key(self):
        result = self._created()
        self.env["ap.security.draft.receipt"].browse(result["receipt"]["receipt_id"]).idempotency_key = "sha256:" + "d" * 64
        self.assertIs(self._observe()["facts"]["document_duplicate"], True)

    def test_reference_duplicate_is_observed_in_draft(self):
        bill = self._bill()
        self.assertEqual(bill.state, "draft")
        observed = self._observe()
        self.assertIs(observed["facts"]["reference_duplicate"], True)
        self.assertIs(observed["facts"]["document_duplicate"], False)

    def test_cancelled_bill_does_not_duplicate_reference(self):
        bill = self._bill(); bill.button_cancel()
        self.assertEqual(bill.state, "cancel")
        self.assertIs(self._observe()["facts"]["reference_duplicate"], False)

    def test_other_vendor_reference_is_not_this_workflow_duplicate(self):
        self._bill(vendor=self.other_vendor)
        self.assertIs(self._observe()["facts"]["reference_duplicate"], False)

    def test_other_company_reference_is_not_this_workflow_duplicate(self):
        foreign_vendor = self.env["res.partner"].create({
            "name": "TCC FOREIGN OBSERVATION VENDOR - SEM VALOR FISCAL",
            "company_id": self.other_company.id, "supplier_rank": 1})
        self._bill(company=self.other_company, vendor=foreign_vendor)
        self.assertIs(self._observe()["facts"]["reference_duplicate"], False)

    def test_refund_is_not_a_vendor_bill_duplicate(self):
        self._bill(move_type="in_refund")
        self.assertIs(self._observe()["facts"]["reference_duplicate"], False)

    def test_post_excludes_only_real_create_receipt_and_move(self):
        action = self._post_action()
        observed = self._observe(action=action)
        self.assertEqual(observed["scope"]["target_move_id"], self.move.id)
        self.assertIs(observed["facts"]["document_duplicate"], False)
        self.assertIs(observed["facts"]["reference_duplicate"], False)

    def test_post_detects_a_new_native_duplicate_beyond_origin(self):
        action = self._post_action(); self._bill()
        observed = self._observe(action=action)
        self.assertIs(observed["facts"]["document_duplicate"], False)
        self.assertIs(observed["facts"]["reference_duplicate"], True)

    def test_post_receipt_blocks_new_evaluation_instead_of_fabricating_retry(self):
        action = self._post_action(); self._posted()
        observed = self._observe(action=action)
        self.assertIs(observed["facts"]["document_duplicate"], True)
        self.assertIs(observed["facts"]["reference_duplicate"], False)

    def test_post_wrong_candidate_target_is_rejected_not_repaired(self):
        action = self._post_action(); action["target_move_id"] += 1000000
        self._error(lambda: self._observe(action=action), code="TARGET_MISMATCH")
        self.assertNotEqual(action["target_move_id"], self.move.id)

    def test_post_without_real_origin_is_rejected(self):
        action = {**self.draft_command["action"], "action": "POST_VENDOR_BILL",
            "executor_mode": "POST_APPROVED", "target_move_id": 123}
        self._error(lambda: self._observe(action=action), code="ORIGIN_NOT_FOUND",
            error_type=registered_post.RegisteredPostError)

    def test_post_unaudited_origin_cannot_be_adopted(self):
        self._prepare_post(audited=False)
        self._error(lambda: self._observe(action=self.registered_action), code="ORIGIN_INVALID",
            error_type=registered_post.RegisteredPostError)

    def test_service_only_lock_exception_never_opens_executor_period(self):
        self.company.fiscalyear_lock_date = "2026-09-30"
        exception = self.env["account.lock_exception"].create({
            "company_id": self.company.id, "user_id": SUPERUSER_ID, "fiscalyear_lock_date": False,
            "reason": "TCC OBSERVATION SERVICE-ONLY EXCEPTION - SEM VALOR FISCAL"})
        self.assertEqual(exception.state, "active")
        self.assertFalse(self.company.with_user(SUPERUSER_ID).sudo()._get_violated_lock_dates(
            date(2026, 9, 30), False, self.journal))
        self.assertIs(self._observe()["facts"]["accounting_period_open"], False)

    def test_executor_specific_lock_exception_is_observed_for_that_uid(self):
        self.company.fiscalyear_lock_date = "2026-09-30"
        exception = self.env["account.lock_exception"].create({
            "company_id": self.company.id, "user_id": self.executor_user.id, "fiscalyear_lock_date": False,
            "reason": "TCC OBSERVATION EXECUTOR-ONLY EXCEPTION - SEM VALOR FISCAL"})
        self.assertEqual(exception.state, "active")
        self.assertTrue(self.company.with_user(SUPERUSER_ID).sudo()._get_violated_lock_dates(
            date(2026, 9, 30), False, self.journal))
        self.assertIs(self._observe()["facts"]["accounting_period_open"], True)

    def test_purchase_journal_lock_is_observed_without_global_lock(self):
        self.company.purchase_lock_date = "2026-09-30"
        self.assertIs(self._observe()["facts"]["accounting_period_open"], False)

    def test_restricted_executor_sudo_does_not_become_administrative_origin(self):
        for sudo in (False, True):
            with self.subTest(sudo=sudo), self.assertRaises(AccessError):
                self._observe(env=self.env(user=self.executor_user.id, su=sudo))

    def test_employee_sudo_does_not_become_administrative_origin(self):
        for sudo in (False, True):
            with self.subTest(sudo=sudo), self.assertRaises(AccessError):
                self._observe(env=self.env(user=self.employee.id, su=sudo))

    def test_hostile_context_does_not_change_read_scope(self):
        self._bill()
        env = self.env(context={**self.env.context, "allowed_company_ids": [self.other_company.id],
            "force_company": self.other_company.id, "default_ref": "SENSITIVE-CONTEXT",
            "default_company_id": self.other_company.id, "default_state": "cancel"})
        observed = self._observe(env=env)
        self.assertEqual(observed["scope"]["company_id"], self.company.id)
        self.assertIs(observed["facts"]["reference_duplicate"], True)

    def test_scope_document_scenario_and_version_are_not_overridden(self):
        for name, value in {"document_sha256": "e" * 64, "scenario_id": "TCC-OTHER-SCENARIO",
                            "policy_version": "policy-v0.0.0"}.items():
            with self.subTest(name=name):
                self._error(lambda name=name, value=value: self._observe(
                    action={**self.draft_command["action"], name: value}), code="WORKFLOW_BINDING_MISMATCH")

    def test_structural_candidates_and_extra_fields_are_not_repaired(self):
        for action in ({**self.draft_command["action"], "target_move_id": 123},
                       {**self.draft_command["action"], "context": {}},
                       {**self.draft_command["action"], "amount": "SENSITIVE"},
                       {**self.draft_command["action"], "invoice_date": "2026-02-30"}):
            with self.subTest(action=action):
                self._error(lambda action=action: self._observe(action=action), code="ACTION_INVALID")

    def test_provenance_drift_is_not_a_new_registration(self):
        self._error(lambda: self._observe(provenance=replace(self.provenance, code_commit="e" * 40)),
            code="REGISTRATION_PROVENANCE_MISMATCH", error_type=workflow_registry.WorkflowRegistryError)

    def test_bool_registration_identifier_is_not_cast(self):
        self._error(lambda: self._observe(registration_id=True), code="CONTRACT_INVALID",
            error_type=workflow_registry.WorkflowRegistryError)

    def test_file_storage_is_explicit_audit_unavailability_without_repair(self):
        self.env["ir.config_parameter"].sudo().set_param("ir_attachment.location", "file")
        observed = self._observe()
        self.assertEqual(observed["preflight"], {"state": "AVAILABLE", "audit": "UNAVAILABLE"})
        self.assertEqual(self.env["ir.attachment"]._storage(), "file")

    def test_audit_default_is_explicit_unavailability_without_deleting_default(self):
        self.env["ir.default"].set("ap.security.audit.event", "status", "DENIED", company_id=self.company.id)
        observed = self._observe()
        self.assertEqual(observed["preflight"]["audit"], "UNAVAILABLE")
        self.assertEqual(self.env["ir.default"]._get("ap.security.audit.event", "status", company_id=self.company.id), "DENIED")

    def test_audit_acl_drift_is_explicit_unavailability_without_acl_repair(self):
        acl = self.env["ir.model.access"].create({
            "name": "TCC OBSERVATION SYNTHETIC AUDIT ACL DRIFT", "active": True,
            "model_id": self.env["ir.model"]._get_id("ap.security.audit.event"),
            "group_id": self.env.ref("ap_security_executor.group_executor").id,
            "perm_read": True, "perm_write": False, "perm_create": False, "perm_unlink": False})
        self.assertEqual(self._observe()["preflight"]["audit"], "UNAVAILABLE")
        self.assertTrue(acl.active and acl.perm_read)

    def test_audit_read_failure_is_unavailable_not_available_default(self):
        with patch.object(type(self.env["ir.attachment"]), "_storage", side_effect=RuntimeError("SENSITIVE")):
            self.assertEqual(self._observe()["preflight"]["audit"], "UNAVAILABLE")

    def test_indexation_pending_install_is_unavailable_without_configuration_repair(self):
        module = self.env["ir.module.module"].search([("name", "=", "attachment_indexation")], limit=1)
        self.assertTrue(module)
        module.state = "to install"
        self.assertEqual(self._observe()["preflight"]["audit"], "UNAVAILABLE")
        self.assertEqual(module.state, "to install")

    def test_state_read_failure_prevents_observation_without_favorable_facts(self):
        with patch.object(operational_observation, "_duplicates", side_effect=RuntimeError("SENSITIVE")):
            self._error(lambda: self._observe(), code="STATE_UNAVAILABLE")

    def test_direct_postgresql_error_propagates_for_full_retry(self):
        with patch.object(operational_observation, "_duplicates", side_effect=SerializationFailure()):
            with self.assertRaises(SerializationFailure):
                self._observe()

    def test_audit_preflight_postgresql_error_is_not_swallowed(self):
        with patch.object(type(self.env["ir.attachment"]), "_storage", side_effect=SerializationFailure()):
            with self.assertRaises(SerializationFailure):
                self._observe()

    def test_read_fault_after_real_observations_leaves_no_side_effects(self):
        with patch.object(operational_observation, "_after_observation_read", side_effect=RuntimeError("SENSITIVE")):
            self._error(lambda: self._observe(), code="STATE_UNAVAILABLE")

    def test_registry_is_revalidated_after_read_before_return(self):
        def corrupt_registration():
            self.env.cr.execute("UPDATE ap_security_workflow_registration SET registration_sha256=%s WHERE id=%s",
                ("sha256:" + "e" * 64, self.registration.registration_id))
            self.env["ap.security.workflow.registration"].invalidate_model(flush=False)
        with patch.object(operational_observation, "_after_observation_read", side_effect=corrupt_registration):
            self._error(lambda: self._observe(), code="REGISTRATION_INTEGRITY_INVALID",
                error_type=workflow_registry.WorkflowRegistryError)

    def test_post_origin_is_revalidated_after_read_before_return(self):
        action = self._post_action()
        event = self._event(self.created_result)
        def corrupt_origin():
            payload = copy.deepcopy(event.event_payload)
            payload["subject"]["command_sha256"] = "sha256:" + "e" * 64
            self.env.cr.execute("UPDATE ap_security_draft_receipt SET command_sha256=%s WHERE id=%s",
                ("sha256:" + "e" * 64, self.draft_receipt.id))
            self.env.cr.execute("UPDATE ap_security_audit_event SET event_payload=%s, event_sha256=%s WHERE id=%s",
                (Json(payload), audit_digest(payload), event.id))
            self.env["ap.security.draft.receipt"].invalidate_model(flush=False)
            self.env["ap.security.audit.event"].invalidate_model(flush=False)
        with patch.object(operational_observation, "_after_observation_read", side_effect=corrupt_origin):
            self._error(lambda: self._observe(action=action), code="ORIGIN_CHANGED")

    def test_public_executor_remains_closed_after_observation(self):
        self._observe()
        result = self.env["ap.security.executor"].with_user(self.executor_user).execute(self.draft_command)
        self.assertIs(result["effect_applied"], False)
        self.assertEqual(result["executor_status"], "SCAFFOLD_NOT_READY")
