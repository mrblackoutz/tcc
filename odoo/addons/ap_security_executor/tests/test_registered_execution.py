# SPDX-License-Identifier: LGPL-3.0-or-later
"""Private registered CREATE against real synthetic ORM records.

Only private fault seams are patched. TransactionCase does not prove an external
commit, an independent SQL connection, or a public/scientific integrated runner.
"""

import copy
from dataclasses import asdict, replace
from unittest.mock import patch

from psycopg2.errors import SerializationFailure

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from .. import audit_kernel, registered_execution, workflow_registry
from ..document_contracts import SourceDocument
from ..workflow_contracts import WorkflowProvenance
from .test_audit_kernel import AuditFixtureMixin
from .test_executor import _action_hash, _command
from .test_workflow_registry import TestWorkflowRegistration


@tagged("post_install", "-at_install", "c1_workflow")
class TestRegisteredDraftExecution(AuditFixtureMixin, TransactionCase):
    # Reuse a hash-only projection, never inherit another class's test cases.
    _financial_projection = TestWorkflowRegistration._financial_projection

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "TCC REGISTERED EMPLOYEE - SEM VALOR FISCAL", "login": "tcc-registered-employee",
            "company_id": cls.company.id, "company_ids": [Command.set(cls.company.ids)],
            "group_ids": [Command.set([cls.env.ref("base.group_user").id])],
        })

    def setUp(self):
        super().setUp()
        self.provenance = WorkflowProvenance(**{name: getattr(self.audit, name) for name in (
            "code_commit", "code_sha256", "configuration_sha256")})
        self.registration = workflow_registry.register_draft_workflow(self.env,
            workflow=self.draft_workflow, document=self.document, provenance=self.provenance)

    def _execute_registered(self, *, env=None, **changes):
        arguments = dict(registration_id=self.registration.registration_id,
            expected_company_id=self.company.id, expected_executor_user_id=self.executor_user.id,
            expected_scenario_id=self.draft_workflow.scenario_id,
            command=self.draft_command, audit=self.audit, document=self.document)
        arguments.update(changes)
        return registered_execution.create_registered_draft_audited(
            self.env if env is None else env, **arguments)

    def _error(self, operation, *, code, registry=False):
        before = self._financial_projection()
        error_type = (workflow_registry.WorkflowRegistryError if registry
                      else registered_execution.RegisteredExecutionError)
        with self.assertRaises(error_type) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn("SENSITIVE", str(caught.exception))
        self.assertEqual(self._financial_projection(), before)

    def _change_action(self, **changes):
        command = copy.deepcopy(self.draft_command)
        command["action"].update(changes)
        command["policy_decision"]["proposed_action_hash"] = _action_hash(command["action"])
        return command

    def test_registered_create_returns_exact_binding_and_pending_transaction(self):
        envelope = self._execute_registered()
        self.assertEqual(set(envelope), {"schema_version", "registration", "result", "caller_transaction_pending"})
        self.assertEqual(envelope["schema_version"], "registered-draft-execution/v1")
        self.assertIs(envelope["caller_transaction_pending"], True)
        self.assertEqual(envelope["registration"], {
            "registration_id": self.registration.registration_id,
            "registration_sha256": self.registration.registration_sha256})
        result = envelope["result"]
        self.assertEqual(result["status"], "CREATED")
        self.assertIs(result["effect_applied"], True)
        event = self._event(result)
        self.assertEqual(event.event_payload["context"], asdict(self.audit))
        self.assertEqual(event.attachment_id.raw, self.document.raw)
        self.assertEqual(event.receipt_id.move_id.state, "draft")
        self.assertEqual(event.receipt_id.move_id.partner_bank_id, self.bank)

    def test_registered_replay_uses_same_receipt_and_no_second_attachment(self):
        first = self._execute_registered()["result"]
        attachments_before = self.env["ir.attachment"].sudo().search_count([])
        replay = self._execute_registered(audit=replace(self.audit, attempt_id="e" * 32))["result"]
        self.assertEqual(replay["status"], "REPLAY")
        self.assertIs(replay["effect_applied"], False)
        self.assertEqual(replay["receipt"], first["receipt"])
        self.assertEqual(replay["audit_event"]["original_event_id"], first["audit_event"]["event_id"])
        self.assertEqual(self.env["ir.attachment"].sudo().search_count([]), attachments_before)

    def test_restricted_c1_cannot_use_registered_entry_even_with_sudo(self):
        before = self._financial_projection()
        for sudo in (False, True):
            with self.subTest(sudo=sudo), self.assertRaises(AccessError):
                self._execute_registered(env=self.env(user=self.executor_user.id, su=sudo))
        self.assertEqual(self._financial_projection(), before)

    def test_employee_cannot_use_registered_entry_even_with_sudo(self):
        before = self._financial_projection()
        for sudo in (False, True):
            with self.subTest(sudo=sudo), self.assertRaises(AccessError):
                self._execute_registered(env=self.env(user=self.employee.id, su=sudo))
        self.assertEqual(self._financial_projection(), before)

    def test_c1_with_administrative_group_drift_remains_rejected(self):
        self.executor_user.write({"group_ids": [Command.link(self.env.ref("base.group_system").id)]})
        before = self._financial_projection()
        with self.assertRaises(AccessError):
            self._execute_registered(env=self.env(user=self.executor_user.id, su=True))
        self.assertEqual(self._financial_projection(), before)

    def test_actual_administrator_can_execute_without_origin_uid_replacement(self):
        admin = self.env.ref("base.user_admin")
        result = self._execute_registered(env=self.env(user=admin.id, su=False))["result"]
        self.assertEqual(result["status"], "CREATED")
        self.assertEqual(self._event(result).event_payload["outcome"]["administrative_caller_id"], admin.id)

    def test_audit_provenance_must_equal_registered_declaration(self):
        for field, value in {"code_commit": "d" * 40, "code_sha256": "sha256:" + "d" * 64,
                             "configuration_sha256": "sha256:" + "d" * 64}.items():
            with self.subTest(field=field):
                self._error(lambda field=field, value=value: self._execute_registered(
                    audit=replace(self.audit, **{field: value})),
                    code="REGISTRATION_PROVENANCE_MISMATCH", registry=True)

    def test_expected_bindings_are_not_overridden_by_registered_or_proposed_values(self):
        for changes in ({"expected_company_id": self.other_company.id},
                        {"expected_executor_user_id": self.employee.id},
                        {"expected_scenario_id": "TCC-OTHER-SCENARIO"}):
            with self.subTest(changes=changes):
                self._error(lambda changes=changes: self._execute_registered(**changes),
                    code="REGISTRATION_BINDING_MISMATCH", registry=True)

    def test_boolean_registration_identity_is_not_cast_to_an_id(self):
        self._error(lambda: self._execute_registered(registration_id=True), code="CONTRACT_INVALID", registry=True)

    def test_unknown_registration_is_not_created_implicitly(self):
        self._error(lambda: self._execute_registered(registration_id=999999999), code="REGISTRATION_NOT_FOUND", registry=True)

    def test_command_scenario_document_and_policy_are_bound_before_financial_effect(self):
        for changes in ({"scenario_id": "TCC-OTHER-SCENARIO"}, {"document_sha256": "d" * 64}):
            with self.subTest(changes=changes):
                self._error(lambda changes=changes: self._execute_registered(command=self._change_action(**changes)),
                    code="WORKFLOW_BINDING_MISMATCH")
        command = self._change_action(policy_version="policy-other-v1")
        command["policy_decision"]["policy_version"] = "policy-other-v1"
        self._error(lambda: self._execute_registered(command=command), code="WORKFLOW_BINDING_MISMATCH")

    def test_full_post_command_is_not_downgraded_to_registered_create(self):
        self._error(lambda: self._execute_registered(command=_command(post=True)), code="UNSUPPORTED_EXECUTOR_MODE")

    def test_v1_proposal_or_extra_workflow_approval_cannot_be_a_command(self):
        for changes in ({"schema_version": "vendor-bill-proposal/v1"},
                        {"workflow": "SENSITIVE-WORKFLOW-MARKER"}, {"approval": "SENSITIVE-APPROVAL-MARKER"}):
            command = copy.deepcopy(self.draft_command); command.update(changes)
            with self.subTest(changes=changes):
                self._error(lambda command=command: self._execute_registered(command=command), code="COMMAND_INVALID")

    def test_document_bytes_mime_and_hash_are_rechecked_against_registration(self):
        self._error(lambda: self._execute_registered(document=SourceDocument(
            raw=self.document.raw + b"SYNTHETIC", mimetype="application/pdf")),
            code="DOCUMENT_HASH_MISMATCH", registry=True)
        self._error(lambda: self._execute_registered(document=SourceDocument(
            raw=self.document.raw, mimetype="text/plain")), code="DOCUMENT_MIME_INVALID", registry=True)

    def test_corrupted_frozen_audit_context_is_not_accepted(self):
        corrupted = replace(self.audit)
        object.__setattr__(corrupted, "code_commit", "SENSITIVE-AUDIT-MARKER")
        self._error(lambda: self._execute_registered(audit=corrupted), code="CONTRACT_INVALID")

    def test_registered_body_hash_corruption_does_not_repair_the_record(self):
        self.env.cr.execute("UPDATE ap_security_workflow_registration SET registration_sha256=%s WHERE id=%s",
                            ("sha256:" + "d" * 64, self.registration.registration_id))
        self.env["ap.security.workflow.registration"].invalidate_model()
        self._error(self._execute_registered, code="REGISTRATION_INTEGRITY_INVALID", registry=True)

    def test_bank_trust_loss_is_rejected_before_execution_and_not_repaired(self):
        self.bank.allow_out_payment = False
        self._error(self._execute_registered, code="BANK_NOT_ALLOWED", registry=True)
        self.assertFalse(self.bank.allow_out_payment)

    def test_hostile_context_does_not_override_binding_or_enable_post(self):
        env = self.env(context={**self.env.context, "allowed_company_ids": [self.other_company.id],
            "force_company": self.other_company.id, "default_company_id": self.other_company.id,
            "default_state": "posted", "default_ref": "SENSITIVE-CONTEXT-MARKER"})
        result = self._execute_registered(env=env)["result"]
        self.assertEqual(result["status"], "CREATED")
        move = self.env["account.move"].sudo().browse(result["receipt"]["move_id"])
        self.assertEqual(move.company_id, self.company)
        self.assertEqual(move.state, "draft")
        self.assertNotEqual(move.ref, "SENSITIVE-CONTEXT-MARKER")

    def test_divergent_amount_is_real_native_denial_not_repaired_proposal(self):
        command = self._change_action(amount="124.50", lines=[{
            "item_code": self.product.default_code, "quantity": "1.00", "unit_price": "124.50"}])
        result = self._execute_registered(command=command)["result"]
        self.assertEqual(result["status"], "DENIED")
        self.assertIs(result["effect_applied"], False)
        self.assertIn("AMOUNT_MISMATCH", result["reason_codes"])
        self.assertIs(result["audit_complete"], True)
        self.assertFalse(self._event(result).receipt_id)
        self.assertEqual(command["action"]["amount"], "124.50")

    def test_divergent_bank_is_real_native_denial_without_beneficiary_effect(self):
        result = self._execute_registered(command=self._change_action(
            recipient_bank_ref="TCC-UNALLOWLISTED-BANK"))["result"]
        self.assertEqual(result["status"], "DENIED")
        self.assertIn("BANK_NOT_ALLOWED", result["reason_codes"])
        self.assertFalse(self._event(result).receipt_id)

    def test_audit_writer_unavailability_is_incomplete_not_defense_success(self):
        before = self._financial_projection()
        with patch.object(audit_kernel, "_append_event", side_effect=RuntimeError("SENSITIVE-WRITER-MARKER")):
            result = self._execute_registered()["result"]
        self.assertEqual(result["status"], "DENIED")
        self.assertIs(result["audit_complete"], False)
        self.assertEqual(result["deny_class"], "FAIL_CLOSED_UNAVAILABILITY")
        self.assertEqual(self._financial_projection(), before)

    def test_fault_after_real_result_rolls_back_move_receipt_attachment_and_event(self):
        seen = []
        def fail(result):
            self.assertEqual(result["status"], "CREATED")
            self.assertTrue(self.env["account.move"].browse(result["receipt"]["move_id"]).exists())
            self.assertTrue(self._event(result).attachment_id)
            seen.append(True)
            raise RuntimeError("SENSITIVE-AFTER-RESULT-MARKER")
        with patch.object(registered_execution, "_after_registered_draft", side_effect=fail):
            self._error(self._execute_registered, code="EXECUTION_UNAVAILABLE")
        self.assertEqual(seen, [True])

    def test_malformed_return_after_actual_effect_is_rolled_back(self):
        def alter(result):
            self.assertEqual(result["status"], "CREATED")
            result["audit_event"]["event_sha256"] = "sha256:" + "d" * 64
        with patch.object(registered_execution, "_after_registered_draft", side_effect=alter):
            self._error(self._execute_registered, code="EXECUTION_RESULT_INVALID")

    def test_hidden_created_effect_cannot_be_reported_as_incomplete_denial(self):
        original = audit_kernel.create_draft_audited
        def hide(env, **arguments):
            self.assertEqual(original(env, **arguments)["status"], "CREATED")
            return audit_kernel._unavailable("CREATE_DRAFT")
        with patch.object(audit_kernel, "create_draft_audited", side_effect=hide):
            self._error(self._execute_registered, code="EXECUTION_RESULT_INVALID")

    def test_changed_registration_after_real_create_rolls_back_all_effects(self):
        def corrupt(result):
            self.assertEqual(result["status"], "CREATED")
            self.env.cr.execute("UPDATE ap_security_workflow_registration SET registration_sha256=%s WHERE id=%s",
                ("sha256:" + "d" * 64, self.registration.registration_id))
            self.env["ap.security.workflow.registration"].invalidate_model()
        with patch.object(registered_execution, "_after_registered_draft", side_effect=corrupt):
            self._error(self._execute_registered, code="REGISTRATION_INTEGRITY_INVALID", registry=True)
        row = self.env["ap.security.workflow.registration"].browse(self.registration.registration_id)
        row.invalidate_recordset()
        self.assertEqual(row.registration_sha256, self.registration.registration_sha256)

    def test_serialization_after_real_create_propagates_and_rolls_back(self):
        before = self._financial_projection()
        with patch.object(registered_execution, "_after_registered_draft",
                          side_effect=SerializationFailure("SYNTHETIC-SERIALIZATION")):
            with self.assertRaises(SerializationFailure):
                self._execute_registered()
        self.assertEqual(self._financial_projection(), before)

    def test_outer_savepoint_rollback_keeps_registration_without_financial_effect(self):
        before = self._financial_projection()
        class DeliberateRollback(Exception):
            pass
        try:
            with self.env.cr.savepoint():
                self.assertEqual(self._execute_registered()["result"]["status"], "CREATED")
                raise DeliberateRollback()
        except DeliberateRollback:
            pass
        self.assertEqual(self._financial_projection(), before)
        self.assertTrue(self.env["ap.security.workflow.registration"].browse(self.registration.registration_id).exists())

    def test_public_execute_remains_closed_after_registered_create(self):
        self._execute_registered(); before = self._financial_projection()
        result = self.env["ap.security.executor"].with_user(self.executor_user).execute(self.draft_command)
        self.assertEqual(result["executor_status"], "SCAFFOLD_NOT_READY")
        self.assertIs(result["effect_applied"], False)
        self.assertEqual(self._financial_projection(), before)
