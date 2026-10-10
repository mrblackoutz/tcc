# SPDX-License-Identifier: LGPL-3.0-or-later
"""Private registered POST over real synthetic accounting records.

Only private fault seams/server clock are patched; runtime MACs are genuine.
TransactionCase does not prove an external commit or independent-cursor state.
"""

import copy
from dataclasses import asdict, replace
from datetime import timedelta
from unittest.mock import patch

from psycopg2.errors import SerializationFailure
from psycopg2.extras import Json

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from .. import audit_kernel, post_kernel, registered_post, workflow_registry
from ..audit_contracts import audit_digest
from ..document_contracts import SourceDocument
from ..workflow_contracts import WorkflowProvenance
from .test_audit_kernel import AuditFixtureMixin
from .test_workflow_registry import TestWorkflowRegistration


@tagged("post_install", "-at_install", "c1_workflow")
class TestRegisteredPostExecution(AuditFixtureMixin, TransactionCase):
    _financial_projection = TestWorkflowRegistration._financial_projection

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "TCC REGISTERED POST EMPLOYEE - SEM VALOR FISCAL",
            "login": "tcc-registered-post-employee", "company_id": cls.company.id,
            "company_ids": [Command.set(cls.company.ids)],
            "group_ids": [Command.set([cls.env.ref("base.group_user").id])],
        })

    def setUp(self):
        super().setUp()
        self.provenance = WorkflowProvenance(**{name: getattr(self.audit, name) for name in (
            "code_commit", "code_sha256", "configuration_sha256")})
        self.registration = workflow_registry.register_draft_workflow(self.env,
            workflow=self.draft_workflow, document=self.document, provenance=self.provenance)
        # The existing audited wrapper is a deliberately equivalent origin;
        # this does not pretend its event attests the registered entrypoint.
        self._prepare_post()

    def _post_registered(self, *, env=None, clock=None, **changes):
        arguments = dict(registration_id=self.registration.registration_id,
            expected_company_id=self.company.id, expected_executor_user_id=self.executor_user.id,
            expected_scenario_id=self.draft_workflow.scenario_id, command=self.command,
            audit=self.audit, document=self.document, authority=self.authority, key=self.key)
        arguments.update(changes)
        with patch.object(post_kernel, "_utc_now", side_effect=clock or (lambda: self.now)):
            return registered_post.post_registered_bill_audited(
                self.env if env is None else env, **arguments)

    def _error(self, operation, *, code, registry=False):
        before = self._financial_projection()
        error_type = workflow_registry.WorkflowRegistryError if registry else registered_post.RegisteredPostError
        with self.assertRaises(error_type) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn("SENSITIVE", str(caught.exception))
        self.assertEqual(self._financial_projection(), before)

    def _posted_registered(self, **changes):
        envelope = self._post_registered(**changes)
        result = envelope["result"]
        self.assertEqual(result["status"], "POSTED")
        self.assertIs(result["effect_applied"], True)
        self.assertIs(result["audit_complete"], True)
        self.move.invalidate_recordset()
        self.assertEqual(self.move.state, "posted")
        return envelope

    def _denied_registered(self, *, reason, **changes):
        private = workflow_registry._private(self.env, self.company.id)
        before = audit_kernel._financial_snapshot(private, self.draft_workflow, self.move.id)
        result = self._post_registered(**changes)["result"]
        self.assertEqual(result["status"], "DENIED")
        self.assertIs(result["effect_applied"], False)
        self.assertIn(reason, result["reason_codes"])
        self.assertIs(result["audit_complete"], True)
        self.assertEqual(audit_kernel._financial_snapshot(private, self.draft_workflow, self.move.id), before)
        self.assertFalse(self._post_receipts())
        self.assertFalse(self._ledger().search([("company_id", "=", self.company.id)]))
        self.assertEqual(self._event(result).status, "DENIED")
        return result

    def test_valid_post_derives_exact_origin_and_returns_pending_transaction(self):
        envelope = self._posted_registered()
        self.assertEqual(set(envelope), {"schema_version", "registration", "origin", "result", "caller_transaction_pending"})
        self.assertEqual(envelope["schema_version"], "registered-post-execution/v1")
        self.assertIs(envelope["caller_transaction_pending"], True)
        self.assertEqual(envelope["registration"], {"registration_id": self.registration.registration_id,
            "registration_sha256": self.registration.registration_sha256})
        origin = envelope["origin"]
        self.assertEqual(set(origin), {"create_receipt_id", "create_event_id", "create_event_sha256",
                                      "target_move_id", "origin_sha256"})
        self.assertEqual(origin["create_receipt_id"], self.draft_receipt.id)
        self.assertEqual(origin["create_event_id"], self.created_result["audit_event"]["event_id"])
        self.assertEqual(origin["create_event_sha256"], self.created_result["audit_event"]["event_sha256"])
        self.assertEqual(origin["target_move_id"], self.move.id)
        self.assertRegex(origin["origin_sha256"], r"^sha256:[0-9a-f]{64}$")
        event = self._event(envelope["result"])
        self.assertEqual(event.event_payload["context"], asdict(self.audit))
        self.assertEqual(event.attachment_id, self._event(self.created_result).attachment_id)
        self.assertEqual(event.receipt_id.move_id, self.move)
        ledger = self._ledger().browse(envelope["result"]["receipt"]["approval_ledger_id"])
        self.assertEqual(ledger.state, "consumed")
        self.assertEqual(ledger.command_sha256, event.event_payload["subject"]["command_sha256"])

    def test_replay_after_expiry_preserves_origin_receipt_nonce_and_attachment(self):
        first = self._posted_registered()
        effects = self._effects()
        replay = self._post_registered(audit=replace(self.audit, attempt_id="e" * 32),
            clock=lambda: self.now + timedelta(minutes=20))
        result = replay["result"]
        self.assertEqual(result["status"], "REPLAY")
        self.assertIs(result["effect_applied"], False)
        self.assertEqual(result["receipt"], first["result"]["receipt"])
        self.assertEqual(replay["origin"], first["origin"])
        self.assertEqual(result["audit_event"]["original_event_id"], first["result"]["audit_event"]["event_id"])
        self.assertEqual(self._effects(), effects)

    def test_restricted_c1_cannot_post_even_with_sudo(self):
        before = self._financial_projection()
        for sudo in (False, True):
            with self.subTest(sudo=sudo), self.assertRaises(AccessError):
                self._post_registered(env=self.env(user=self.executor_user.id, su=sudo))
        self.assertEqual(self._financial_projection(), before)

    def test_employee_cannot_post_even_with_sudo(self):
        before = self._financial_projection()
        for sudo in (False, True):
            with self.subTest(sudo=sudo), self.assertRaises(AccessError):
                self._post_registered(env=self.env(user=self.employee.id, su=sudo))
        self.assertEqual(self._financial_projection(), before)

    def test_executor_group_drift_does_not_make_c1_a_registrar(self):
        self.executor_user.write({"group_ids": [Command.link(self.env.ref("base.group_system").id)]})
        with self.assertRaises(AccessError):
            self._post_registered(env=self.env(user=self.executor_user.id, su=True))
        self.move.invalidate_recordset()
        self.assertEqual(self.move.state, "draft")

    def test_actual_administrator_identity_is_preserved_in_post_audit(self):
        admin = self.env.ref("base.user_admin")
        result = self._posted_registered(env=self.env(user=admin.id, su=False))["result"]
        self.assertEqual(self._event(result).event_payload["outcome"]["administrative_caller_id"], admin.id)

    def test_hostile_context_does_not_supply_target_or_company_defaults(self):
        env = self.env(context={**self.env.context, "allowed_company_ids": [self.other_company.id],
            "force_company": self.other_company.id, "default_state": "draft",
            "default_ref": "SENSITIVE-CONTEXT-MARKER"})
        result = self._posted_registered(env=env)["result"]
        self.assertEqual(result["receipt"]["move_id"], self.move.id)
        self.assertNotEqual(self.move.ref, "SENSITIVE-CONTEXT-MARKER")

    def test_expected_company_executor_scenario_are_not_overridden(self):
        for changes in ({"expected_company_id": self.other_company.id},
                        {"expected_executor_user_id": self.employee.id},
                        {"expected_scenario_id": "TCC-OTHER-SCENARIO"}):
            with self.subTest(changes=changes):
                self._error(lambda changes=changes: self._post_registered(**changes),
                    code="REGISTRATION_BINDING_MISMATCH", registry=True)

    def test_boolean_registration_id_is_not_cast_to_integer(self):
        self._error(lambda: self._post_registered(registration_id=True), code="CONTRACT_INVALID", registry=True)

    def test_unknown_registration_is_not_created_implicitly(self):
        self._error(lambda: self._post_registered(registration_id=999999999), code="REGISTRATION_NOT_FOUND", registry=True)

    def test_code_and_configuration_provenance_must_remain_identical(self):
        for field, value in {"code_commit": "d" * 40, "code_sha256": "sha256:" + "d" * 64,
                             "configuration_sha256": "sha256:" + "d" * 64}.items():
            with self.subTest(field=field):
                self._error(lambda field=field, value=value: self._post_registered(
                    audit=replace(self.audit, **{field: value})),
                    code="REGISTRATION_PROVENANCE_MISMATCH", registry=True)

    def test_corrupted_frozen_audit_context_is_rejected(self):
        audit = replace(self.audit)
        object.__setattr__(audit, "code_commit", "SENSITIVE-AUDIT-MARKER")
        self._error(lambda: self._post_registered(audit=audit), code="CONTRACT_INVALID")

    def test_document_bytes_mime_and_hash_are_rechecked(self):
        for document, code in ((SourceDocument(raw=self.document.raw + b"SYNTHETIC", mimetype="application/pdf"),
                                "DOCUMENT_HASH_MISMATCH"),
                               (SourceDocument(raw=self.document.raw, mimetype="text/plain"), "DOCUMENT_MIME_INVALID")):
            with self.subTest(code=code):
                self._error(lambda document=document: self._post_registered(document=document), code=code, registry=True)

    def test_missing_create_receipt_is_not_inferred_from_bill_reference(self):
        self.draft_receipt.document_sha256 = "d" * 64
        self._error(self._post_registered, code="ORIGIN_NOT_FOUND")

    def test_unaudited_receipt_is_not_promoted_to_an_origin(self):
        # Controlled trusted test corruption of immutable storage only.
        self.env.cr.execute("DELETE FROM ap_security_audit_event WHERE id=%s",
                            (self.created_result["audit_event"]["event_id"],))
        self.env["ap.security.audit.event"].invalidate_model()
        self._error(self._post_registered, code="ORIGIN_INVALID")

    def test_origin_receipt_financial_ids_and_idempotency_are_checked(self):
        for field, value in (("vendor_id", self.other_vendor.id), ("executor_user_id", self.employee.id),
                             ("idempotency_key", "sha256:" + "d" * 64), ("purchase_line_ids", [Command.clear()])):
            with self.subTest(field=field):
                with self.env.cr.savepoint():
                    original = self.draft_receipt[field]
                    self.draft_receipt.write({field: value})
                    self._error(self._post_registered, code="ORIGIN_INVALID")
                    restore = [Command.set(original.ids)] if field == "purchase_line_ids" else (
                        original.id if field.endswith("_id") else original)
                    self.draft_receipt.write({field: restore})

    def test_origin_receipt_payload_extra_field_is_rejected(self):
        self.draft_receipt.receipt_payload = dict(self.draft_receipt.receipt_payload, extra="SENSITIVE-ORIGIN-MARKER")
        self._error(self._post_registered, code="ORIGIN_INVALID")

    def test_origin_event_hash_corruption_is_not_repaired(self):
        self.env.cr.execute("UPDATE ap_security_audit_event SET event_sha256=%s WHERE id=%s",
            ("sha256:" + "d" * 64, self.created_result["audit_event"]["event_id"]))
        self.env["ap.security.audit.event"].invalidate_model()
        self._error(self._post_registered, code="ORIGIN_INVALID")

    def test_origin_provenance_cannot_be_replaced_with_new_registration_declaration(self):
        event = self._event(self.created_result)
        payload = copy.deepcopy(event.event_payload)
        payload["context"]["code_commit"] = "d" * 40
        self.env.cr.execute("UPDATE ap_security_audit_event SET event_payload=%s,event_sha256=%s WHERE id=%s",
                            (Json(payload), audit_digest(payload), event.id))
        self.env["ap.security.audit.event"].invalidate_model()
        self._error(self._post_registered, code="ORIGIN_INVALID")

    def test_original_attachment_bytes_are_revalidated_before_post(self):
        self._event(self.created_result).attachment_id.raw = self.document.raw + b"SYNTHETIC"
        self._error(self._post_registered, code="ORIGIN_INVALID")

    def test_create_command_is_not_promoted_to_post(self):
        self._error(lambda: self._post_registered(command=self.draft_command), code="UNSUPPORTED_EXECUTOR_MODE")

    def test_missing_approval_is_structural_failure_without_effect(self):
        command = copy.deepcopy(self.command)
        command.pop("approval")
        self._error(lambda: self._post_registered(command=command), code="COMMAND_INVALID")

    def test_extra_target_receipt_or_workflow_override_is_not_a_command(self):
        for field in ("target_move_id", "create_receipt_id", "workflow"):
            command = copy.deepcopy(self.command)
            command[field] = "SENSITIVE-OVERRIDE-MARKER"
            with self.subTest(field=field):
                self._error(lambda command=command: self._post_registered(command=command), code="COMMAND_INVALID")

    def test_wrong_target_does_not_select_another_move_even_with_valid_signature(self):
        self._denied_registered(reason="TARGET_MISMATCH",
            command=self._signed_command(action_changes={"target_move_id": self.move.id + 999999}))

    def test_changed_amount_is_not_repaired_or_promoted_by_real_signature(self):
        self._denied_registered(reason="PERSISTED_STATE_MISMATCH", command=self._signed_command(action_changes={
            "amount": "124.50", "lines": [{"item_code": self.product.default_code,
                                            "quantity": "1.00", "unit_price": "124.50"}]}))

    def test_wrong_scenario_document_and_policy_fail_before_financial_kernel(self):
        for changes in ({"scenario_id": "TCC-OTHER-SCENARIO"}, {"document_sha256": "d" * 64},
                        {"policy_version": "policy-other-v1"}):
            command = self._signed_command(action_changes=changes)
            if "scenario_id" in changes:
                command["approval"]["scenario_id"] = changes["scenario_id"]
            if "policy_version" in changes:
                command["policy_decision"]["policy_version"] = changes["policy_version"]
            with self.subTest(changes=changes):
                self._error(lambda command=command: self._post_registered(command=command), code="WORKFLOW_BINDING_MISMATCH")

    def test_invalid_signature_is_audited_without_post_or_nonce_consumption(self):
        command = copy.deepcopy(self.command)
        command["approval"]["signature"] = "hmac-sha256/v1:" + "0" * 64
        self._denied_registered(reason="SIGNATURE_INVALID", command=command)

    def test_expired_and_not_yet_valid_approvals_are_not_consumed(self):
        for instant, reason in ((self.now + timedelta(minutes=20), "EXPIRED"),
                                (self.now - timedelta(minutes=20), "NOT_YET_VALID")):
            with self.subTest(reason=reason):
                self._denied_registered(reason=reason, clock=lambda instant=instant: instant)

    def test_audit_writer_unavailable_returns_incomplete_operational_failure(self):
        before = self._financial_projection()
        with patch.object(audit_kernel, "_append_event", side_effect=RuntimeError("SENSITIVE-WRITER-MARKER")):
            result = self._post_registered()["result"]
        self.assertEqual(result["status"], "DENIED")
        self.assertEqual(result["reason_codes"], ["AUDIT_UNAVAILABLE"])
        self.assertIs(result["audit_complete"], False)
        self.assertEqual(result["deny_class"], "FAIL_CLOSED_UNAVAILABILITY")
        self.assertEqual(self._financial_projection(), before)

    def test_fault_after_actual_post_rolls_back_receipt_nonce_event_and_keeps_create(self):
        seen = []
        def fail(result):
            self.assertEqual(result["status"], "POSTED")
            self.assertEqual(self.env["account.move"].browse(result["receipt"]["move_id"]).state, "posted")
            self.assertEqual(self._ledger().browse(result["receipt"]["approval_ledger_id"]).state, "consumed")
            seen.append(True)
            raise RuntimeError("SENSITIVE-AFTER-POST-MARKER")
        with patch.object(registered_post, "_after_registered_post", side_effect=fail):
            self._error(self._post_registered, code="EXECUTION_UNAVAILABLE")
        self.assertEqual(seen, [True])
        self.assertTrue(self.draft_receipt.exists())
        self.assertEqual(self._event(self.created_result).attachment_id.raw, self.document.raw)

    def test_origin_receipt_change_after_real_post_reverts_entire_effect(self):
        def corrupt(result):
            self.assertEqual(result["status"], "POSTED")
            self.draft_receipt.vendor_id = self.other_vendor
        with patch.object(registered_post, "_after_registered_post", side_effect=corrupt):
            self._error(self._post_registered, code="ORIGIN_INVALID")
        self.assertEqual(self.draft_receipt.vendor_id, self.vendor)

    def test_origin_fingerprint_change_after_real_post_is_not_accepted(self):
        def corrupt(result):
            self.assertEqual(result["status"], "POSTED")
            event = self._event(self.created_result)
            payload = copy.deepcopy(event.event_payload)
            payload["context"]["run_id"] = "TCC-ALTERED-CREATE-RUN"
            self.env.cr.execute("UPDATE ap_security_audit_event SET run_id=%s,event_payload=%s,event_sha256=%s WHERE id=%s",
                (payload["context"]["run_id"], Json(payload), audit_digest(payload), event.id))
            self.env["ap.security.audit.event"].invalidate_model()
        with patch.object(registered_post, "_after_registered_post", side_effect=corrupt):
            self._error(self._post_registered, code="ORIGIN_CHANGED")

    def test_post_receipt_financial_binding_cannot_change_after_kernel(self):
        def corrupt(result):
            self.assertEqual(result["status"], "POSTED")
            self.env["ap.security.draft.receipt"].browse(result["receipt"]["receipt_id"]).vendor_id = self.other_vendor
        with patch.object(registered_post, "_after_registered_post", side_effect=corrupt):
            self._error(self._post_registered, code="EXECUTION_RESULT_INVALID")

    def test_actual_nonce_metadata_cannot_change_after_kernel(self):
        def corrupt(result):
            self.assertEqual(result["status"], "POSTED")
            self.env.cr.execute("UPDATE ap_security_approval_nonce SET fixture_id=%s WHERE id=%s",
                ("TCC-ALTERED-FIXTURE", result["receipt"]["approval_ledger_id"]))
            self.env["ap.security.approval.nonce"].invalidate_model()
        with patch.object(registered_post, "_after_registered_post", side_effect=corrupt):
            self._error(self._post_registered, code="EXECUTION_RESULT_INVALID")

    def test_consumed_nonce_cannot_be_reported_reserved_after_real_post(self):
        def corrupt(result):
            self.env.cr.execute("UPDATE ap_security_approval_nonce SET state='reserved',consumed_at=NULL WHERE id=%s",
                                (result["receipt"]["approval_ledger_id"],))
            self.env["ap.security.approval.nonce"].invalidate_model()
        with patch.object(registered_post, "_after_registered_post", side_effect=corrupt):
            self._error(self._post_registered, code="EXECUTION_RESULT_INVALID")

    def test_changed_audit_event_or_result_after_real_post_reverts_effect(self):
        def corrupt(result):
            self.assertEqual(result["status"], "POSTED")
            result["audit_event"]["event_sha256"] = "sha256:" + "d" * 64
        with patch.object(registered_post, "_after_registered_post", side_effect=corrupt):
            self._error(self._post_registered, code="EXECUTION_RESULT_INVALID")

    def test_replay_cannot_link_to_create_event_instead_of_successful_post_event(self):
        self._posted_registered()
        def corrupt(result):
            self.assertEqual(result["status"], "REPLAY")
            event = self._event(result)
            payload = copy.deepcopy(event.event_payload)
            payload["original_event_id"] = self.created_result["audit_event"]["event_id"]
            digest = audit_digest(payload)
            self.env.cr.execute("UPDATE ap_security_audit_event SET original_event_id=%s,event_payload=%s,event_sha256=%s WHERE id=%s",
                                (payload["original_event_id"], Json(payload), digest, event.id))
            self.env["ap.security.audit.event"].invalidate_model()
            result["audit_event"].update(event_sha256=digest, original_event_id=payload["original_event_id"])
        with patch.object(registered_post, "_after_registered_post", side_effect=corrupt):
            self._error(self._post_registered, code="EXECUTION_RESULT_INVALID")

    def test_duplicate_valid_pdf_cannot_replace_original_create_attachment_after_post(self):
        def corrupt(result):
            self.assertEqual(result["status"], "POSTED")
            event = self._event(result)
            attachment = event.attachment_id.copy({"name": event.attachment_id.name})
            payload = copy.deepcopy(event.event_payload)
            payload["attachment"]["attachment_id"] = attachment.id
            private = workflow_registry._private(self.env, self.company.id)
            payload["outcome"]["after_sha256"] = audit_kernel._financial_snapshot(private, self.draft_workflow, self.move.id)
            digest = audit_digest(payload)
            self.env.cr.execute("UPDATE ap_security_audit_event SET attachment_id=%s,event_payload=%s,event_sha256=%s WHERE id=%s",
                                (attachment.id, Json(payload), digest, event.id))
            self.env["ap.security.audit.event"].invalidate_model()
            result["audit_event"]["event_sha256"] = digest
        with patch.object(registered_post, "_after_registered_post", side_effect=corrupt):
            self._error(self._post_registered, code="EXECUTION_RESULT_INVALID")

    def test_hidden_post_cannot_be_reported_as_incomplete_audit_denial(self):
        original = audit_kernel.post_bill_audited
        def hide(env, **arguments):
            self.assertEqual(original(env, **arguments)["status"], "POSTED")
            return audit_kernel._unavailable("POST_APPROVED")
        with patch.object(audit_kernel, "post_bill_audited", side_effect=hide):
            self._error(self._post_registered, code="EXECUTION_RESULT_INVALID")

    def test_changed_registration_after_real_post_rolls_back(self):
        def corrupt(result):
            self.assertEqual(result["status"], "POSTED")
            self.env.cr.execute("UPDATE ap_security_workflow_registration SET registration_sha256=%s WHERE id=%s",
                ("sha256:" + "d" * 64, self.registration.registration_id))
            self.env["ap.security.workflow.registration"].invalidate_model()
        with patch.object(registered_post, "_after_registered_post", side_effect=corrupt):
            self._error(self._post_registered, code="REGISTRATION_INTEGRITY_INVALID", registry=True)

    def test_serialization_after_real_post_propagates_and_reverts_effect(self):
        before = self._financial_projection()
        with patch.object(registered_post, "_after_registered_post",
                          side_effect=SerializationFailure("SYNTHETIC-SERIALIZATION")):
            with self.assertRaises(SerializationFailure):
                self._post_registered()
        self.assertEqual(self._financial_projection(), before)

    def test_outer_savepoint_rollback_preserves_only_original_create(self):
        before = self._financial_projection()
        class DeliberateRollback(Exception):
            pass
        try:
            with self.env.cr.savepoint():
                self._posted_registered()
                raise DeliberateRollback()
        except DeliberateRollback:
            pass
        self.assertEqual(self._financial_projection(), before)

    def test_fault_does_not_replace_or_clear_callers_postcommit_queue(self):
        pending = self.env.cr.postcommit
        def own_callback():
            return None
        pending.add(own_callback)
        before = tuple(pending._funcs)
        with patch.object(registered_post, "_after_registered_post", side_effect=RuntimeError("SYNTHETIC-FAULT")):
            self._error(self._post_registered, code="EXECUTION_UNAVAILABLE")
        self.assertIs(self.env.cr.postcommit, pending)
        self.assertEqual(tuple(pending._funcs)[:len(before)], before)

    def test_public_execute_remains_closed_after_registered_post(self):
        self._posted_registered()
        before = self._financial_projection()
        result = self.env["ap.security.executor"].with_user(self.executor_user).execute(self.command)
        self.assertEqual(result["executor_status"], "SCAFFOLD_NOT_READY")
        self.assertIs(result["effect_applied"], False)
        self.assertEqual(self._financial_projection(), before)
