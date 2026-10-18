# SPDX-License-Identifier: LGPL-3.0-or-later
"""Real transactional synthetic document attachments, not a public capability.

PDF parsing belongs to the common ingestion stage. These cases verify the
private storage boundary, its strict byte bindings and real rollback effects.
All document contents are synthetic and without fiscal value.
"""

import copy
from dataclasses import replace
import hashlib
import secrets
import unittest
from unittest.mock import patch

from psycopg2.errors import RestrictViolation, SerializationFailure

from odoo import SUPERUSER_ID, api
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from .. import attachment_kernel, audit_kernel
from ..document_contracts import SourceDocument
from ..draft_contracts import bill_idempotency_key
from .test_audit_kernel import AuditFixtureMixin, _synthetic_pdf
from .test_executor import _action_hash
from .test_post_kernel import _bytes


@tagged("post_install", "-at_install", "c1_attachment")
class TestAttachmentKernel(AuditFixtureMixin, TransactionCase):
    def _attachments(self):
        return self.env["ir.attachment"].sudo().search([
            ("company_id", "=", self.company.id), ("res_model", "=", "account.move"),
        ], order="id")

    def _attachment(self, result):
        event = self._event(result)
        self.assertEqual(event.event_payload["schema_version"], "operational-audit/v2")
        metadata = event.event_payload["attachment"]
        self.assertEqual(set(metadata), {"schema_version", "attachment_id", "move_id",
            "document_sha256", "byte_count", "mimetype", "storage"})
        self.assertEqual(metadata["schema_version"], "document-attachment/v1")
        self.assertEqual(metadata["mimetype"], "application/pdf")
        self.assertEqual(metadata["storage"], "db")
        self.assertEqual(metadata["document_sha256"], self.draft_workflow.document_sha256)
        self.assertEqual(metadata["byte_count"], len(self.document_raw))
        self.assertEqual(metadata["move_id"], result["receipt"]["move_id"])
        self.assertEqual(event.attachment_id.id, metadata["attachment_id"])
        attachment = self.env["ir.attachment"].sudo().browse(metadata["attachment_id"])
        self.assertTrue(attachment.exists())
        self.assertEqual(attachment.raw, self.document_raw)
        self.assertEqual(attachment.file_size, len(self.document_raw))
        self.assertEqual(attachment.checksum, hashlib.sha1(self.document_raw).hexdigest())
        self.assertEqual(attachment.mimetype, "application/pdf")
        self.assertEqual(attachment.company_id, self.company)
        self.assertEqual(attachment.res_model, "account.move")
        self.assertEqual(attachment.res_id, result["receipt"]["move_id"])
        self.assertEqual(attachment.type, "binary")
        self.assertFalse(attachment.public or attachment.access_token or attachment.url or attachment.res_field)
        self.assertFalse(attachment.store_fname)
        self.assertEqual(attachment.db_datas, self.document_raw)
        self.assertIn(self.draft_workflow.document_sha256, attachment.name)
        self.assertIs(event.event_payload["provenance"]["document_bytes_verified"], True)
        return attachment

    def _document_denied(self, document, *, reason):
        before = self._state_hash()
        before_attachments = tuple(self._attachments().ids)
        result = self._denied(self._create(document=document), reason=reason)
        # DEC-060: document and attachment failures are technical fail-closed denials.
        self.assertEqual(result["deny_class"], "FAIL_CLOSED_UNAVAILABILITY")
        self.assertEqual(self._state_hash(), before)
        self.assertEqual(tuple(self._attachments().ids), before_attachments)
        event = self._event(result)
        self.assertIsNone(event.event_payload["attachment"])
        self.assertFalse(event.attachment_id)
        return result

    def _corrupt_attachment(self, values, *, operation=None):
        result = self._created()
        attachment = self._attachment(result)
        attachment.write(values)
        self.env.flush_all()
        before = self._state_hash(include_guard=False)
        before_count = len(self._attachments())
        denial = self._denied((operation or self._create)(), reason="ATTACHMENT_INTEGRITY_INVALID")
        self.assertEqual(denial["deny_class"], "FAIL_CLOSED_UNAVAILABILITY")
        self.assertEqual(self._state_hash(include_guard=False), before)
        self.assertEqual(len(self._attachments()), before_count)
        return attachment

    def test_create_stores_exact_private_pdf_in_database_and_audit(self):
        result = self._created()
        self._attachment(result)
        self.assertEqual(len(self._attachments()), 1)
        self.assertEqual(self.env["account.move"].browse(result["receipt"]["move_id"]).state, "draft")

    def test_create_replay_preserves_one_attachment_and_original_receipt(self):
        first = self._created()
        attachment = self._attachment(first)
        before = self._state_hash(include_guard=False)
        replay = self._create(audit=replace(self.audit, attempt_id=secrets.token_hex(16)))
        self.assertEqual(replay["status"], "REPLAY")
        self.assertEqual(replay["receipt"], first["receipt"])
        self.assertEqual(self._attachment(replay), attachment)
        self.assertEqual(len(self._attachments()), 1)
        self.assertEqual(self._state_hash(include_guard=False), before)

    def test_post_and_post_replay_reuse_created_attachment_without_import(self):
        self._prepare_post()
        original_attachment = self._attachment(self.created_result)
        first = self._posted()
        self.assertEqual(self._attachment(first), original_attachment)
        replay = self._post()
        self.assertEqual(replay["status"], "REPLAY")
        self.assertEqual(self._attachment(replay), original_attachment)
        self.assertEqual(replay["receipt"], first["receipt"])
        self.assertEqual(len(self._attachments()), 1)

    def test_invalid_empty_document_has_safe_audited_denial(self):
        result = self._document_denied(SourceDocument(raw=b"", mimetype="application/pdf"), reason="DOCUMENT_EMPTY")
        self.assertIs(self._event(result).event_payload["provenance"]["document_bytes_verified"], False)

    def test_mime_is_exact_not_a_filename_or_content_type_hint(self):
        for mimetype in ("text/plain", "application/octet-stream", "APPLICATION/PDF", "application/pdf; charset=utf-8"):
            with self.subTest(mimetype=mimetype):
                self._document_denied(SourceDocument(raw=self.document_raw, mimetype=mimetype), reason="DOCUMENT_MIME_INVALID")

    def test_non_pdf_magic_is_rejected_without_persisting_private_marker(self):
        marker = b"TCC-C109-UNTRUSTED-CONTENT-NOT-FOR-AUDIT"
        result = self._document_denied(SourceDocument(raw=marker, mimetype="application/pdf"), reason="DOCUMENT_INVALID")
        self.assertFalse(marker in _bytes(self._event(result).event_payload))

    def test_oversized_document_is_rejected_before_attachment_write(self):
        raw = b"%PDF-1.4\n" + b"X" * 1_048_576
        self._document_denied(SourceDocument(raw=raw, mimetype="application/pdf"), reason="DOCUMENT_TOO_LARGE")

    def test_raw_hash_must_match_the_registered_document(self):
        self._document_denied(SourceDocument(raw=_synthetic_pdf("TCC OUTRO PDF SEM VALOR FISCAL"),
                                            mimetype="application/pdf"), reason="DOCUMENT_HASH_MISMATCH")

    def test_mutable_bytearray_and_string_do_not_become_valid_document_bytes(self):
        for raw in (bytearray(self.document_raw), self.document_raw.decode("latin1"), memoryview(self.document_raw), None):
            with self.subTest(raw_type=type(raw).__name__):
                self._document_denied(SourceDocument(raw=raw, mimetype="application/pdf"), reason="DOCUMENT_INVALID")

    def test_mapping_envelope_is_not_a_trusted_document_contract(self):
        self._document_denied({"raw": self.document_raw, "mimetype": "application/pdf"}, reason="DOCUMENT_INVALID")

    def test_command_document_hash_cannot_substitute_the_registered_hash(self):
        command = copy.deepcopy(self.draft_command)
        command["action"]["document_sha256"] = "f" * 64
        command["policy_decision"]["proposed_action_hash"] = _action_hash(command["action"])
        before = self._state_hash()
        result = self._denied(self._create(command), reason="DOCUMENT_HASH_MISMATCH")
        self.assertEqual(result["deny_class"], "FAIL_CLOSED_UNAVAILABILITY")
        self.assertEqual(self._state_hash(), before)
        self.assertFalse(self._attachments())

    def test_business_denial_verifies_bytes_but_stores_no_attachment(self):
        command = copy.deepcopy(self.draft_command)
        command["action"]["recipient_bank_ref"] = self.other_bank.acc_number
        command["policy_decision"]["proposed_action_hash"] = _action_hash(command["action"])
        result = self._denied(self._create(command))
        event = self._event(result)
        self.assertIs(event.event_payload["provenance"]["document_bytes_verified"], True)
        self.assertIsNone(event.event_payload["attachment"])
        self.assertFalse(self._attachments())

    def test_filestore_configuration_fails_closed_without_creating_a_file(self):
        self.env["ir.config_parameter"].sudo().set_param("ir_attachment.location", "file")
        with patch.object(type(self.env["ir.attachment"]), "_file_write", side_effect=AssertionError("No filestore write permitted")):
            self._document_denied(self.document, reason="ATTACHMENT_CONFIG_INVALID")

    def test_database_storage_does_not_invoke_filestore_writer(self):
        with patch.object(type(self.env["ir.attachment"]), "_file_write", side_effect=AssertionError("No filestore write permitted")):
            self._attachment(self._created())

    def test_attachment_indexation_module_is_rejected_as_untrusted_expansion(self):
        module = self.env["ir.module.module"].sudo().search([("name", "=", "attachment_indexation")])
        self.assertTrue(module, "Pinned source lacks the native module metadata required for this negative case.")
        module.write({"state": "installed"})
        self._document_denied(self.document, reason="ATTACHMENT_CONFIG_INVALID")

    def test_global_attachment_defaults_are_not_consumed_or_removed(self):
        defaults = self.env["ir.default"].sudo()
        defaults.set("ir.attachment", "public", True)
        before_defaults = defaults.search_count([])
        self._document_denied(self.document, reason="ATTACHMENT_CONFIG_INVALID")
        self.assertEqual(defaults.search_count([]), before_defaults)

    def test_service_attachment_defaults_are_rejected(self):
        self.env["ir.default"].sudo().set("ir.attachment", "public", True, user_id=SUPERUSER_ID)
        self._document_denied(self.document, reason="ATTACHMENT_CONFIG_INVALID")

    def test_personal_c1_defaults_and_client_context_cannot_publish_attachment(self):
        self.env["ir.default"].sudo().set("ir.attachment", "public", True, user_id=self.executor_user.id)
        hostile = self.env(context={
            "allowed_company_ids": [self.other_company.id], "force_company": self.other_company.id,
            "default_company_id": self.other_company.id, "default_public": True,
            "default_type": "url", "default_url": "https://example.invalid/synthetic",
            "default_access_token": "TCC-C109-UNTRUSTED-TOKEN", "default_res_field": "message_main_attachment_id",
        })
        self._attachment(self._created(env=hostile))

    def test_audit_foreign_key_prevents_removal_of_original_attachment(self):
        first = self._created()
        attachment = self._attachment(first)
        with unittest.TestCase.assertRaises(self, RestrictViolation):
            with self.env.cr.savepoint():
                attachment.unlink()
        self.assertTrue(attachment.exists())
        before = self._state_hash(include_guard=False)
        replay = self._create()
        self.assertEqual(replay["status"], "REPLAY")
        self.assertEqual(self._attachment(replay), attachment)
        self.assertEqual(replay["receipt"], first["receipt"])
        self.assertEqual(self._state_hash(include_guard=False), before)

    def test_missing_database_blob_blocks_post_without_reconstructing_attachment(self):
        self._prepare_post()
        attachment = self._attachment(self.created_result)
        self.env.cr.execute("UPDATE ir_attachment SET db_datas = NULL WHERE id = %s", (attachment.id,))
        self.env["ir.attachment"].invalidate_model()
        before = self._state_hash()
        self._denied(self._post(), reason="ATTACHMENT_INTEGRITY_INVALID")
        self.assertEqual(self._state_hash(), before)
        self.assertFalse(self._post_receipts() or self._ledger())
        attachment.invalidate_recordset()
        self.assertFalse(attachment.raw)

    def test_altered_stored_bytes_block_replay_without_repair(self):
        changed = _synthetic_pdf("TCC CONTEUDO ALTERADO SEM VALOR FISCAL")
        attachment = self._corrupt_attachment({"raw": changed})
        attachment.invalidate_recordset()
        self.assertEqual(attachment.raw, changed)

    def test_attachment_mime_drift_blocks_replay(self):
        self._corrupt_attachment({"mimetype": "text/plain"})

    def test_public_or_token_attachment_drift_blocks_replay(self):
        self._corrupt_attachment({"public": True, "access_token": "TCC-C109-SYNTHETIC-UNTRUSTED-TOKEN"})

    def test_attachment_resource_field_drift_blocks_replay(self):
        # SQL injects an otherwise unrelated storage feature; it is not a
        # supported mutator and does not grant the candidate any authority.
        result = self._created()
        attachment = self._attachment(result)
        self.env.cr.execute("UPDATE ir_attachment SET res_field = %s WHERE id = %s", ("message_main_attachment_id", attachment.id))
        self.env["ir.attachment"].invalidate_model()
        before = self._state_hash(include_guard=False)
        self._denied(self._create(), reason="ATTACHMENT_INTEGRITY_INVALID")
        self.assertEqual(self._state_hash(include_guard=False), before)

    def test_attachment_target_or_company_drift_blocks_replay(self):
        self._corrupt_attachment({"res_model": "purchase.order", "res_id": self.purchase.id,
                                  "company_id": self.other_company.id})

    def test_native_checksum_corruption_blocks_replay(self):
        result = self._created()
        attachment = self._attachment(result)
        self.env.cr.execute("UPDATE ir_attachment SET checksum = %s WHERE id = %s", ("0" * 40, attachment.id))
        self.env["ir.attachment"].invalidate_model()
        self._denied(self._create(), reason="ATTACHMENT_INTEGRITY_INVALID")

    def test_post_rechecks_stored_bytes_before_action_post_and_nonce(self):
        self._prepare_post()
        attachment = self._attachment(self.created_result)
        attachment.write({"raw": _synthetic_pdf("TCC CORRUPCAO ANTES DE POST SEM VALOR FISCAL")})
        before = self._state_hash()
        observed = []
        with patch.object(audit_kernel, "_after_financial_kernel", side_effect=lambda result: observed.append(result["status"])):
            self._denied(self._post(), reason="ATTACHMENT_INTEGRITY_INVALID")
        self.assertFalse(observed, "Corrupted origin reached the financial kernel.")
        self.assertEqual(self._state_hash(), before)
        self.assertFalse(self._post_receipts())
        self.assertFalse(self._ledger())
        self.move.invalidate_recordset()
        self.assertEqual(self.move.state, "draft")

    def test_attachment_drift_after_real_post_rolls_back_post_nonce_and_bytes(self):
        self._prepare_post()
        attachment = self._attachment(self.created_result)
        before = self._state_hash()
        events_before = tuple(self._events().ids)
        original_callbacks = tuple(self.env.cr.postcommit._funcs)
        observed = []

        def corrupt_after_kernel(result):
            observed.append(result["status"])
            attachment.write({"raw": _synthetic_pdf("TCC DERIVA APOS POST SEM VALOR FISCAL")})

        with patch.object(audit_kernel, "_after_financial_kernel", side_effect=corrupt_after_kernel):
            self._denied(self._post(), reason="ATTACHMENT_INTEGRITY_INVALID")
        self.assertEqual(observed, ["POSTED"])
        self.assertEqual(self._state_hash(), before)
        self.assertFalse(self._post_receipts() or self._ledger())
        self.assertEqual(tuple(self._events().ids)[:len(events_before)], events_before)
        self.assertEqual(tuple(self.env.cr.postcommit._funcs), original_callbacks)
        attachment.invalidate_recordset()
        self.assertEqual(attachment.raw, self.document_raw)
        self._posted()

    def test_fault_after_real_attachment_insert_rolls_back_attachment_and_draft(self):
        observed = []

        def fail(attachment):
            observed.append((bool(attachment.exists()), attachment.raw == self.document_raw))
            raise RuntimeError("TCC-C109-ATTACHMENT-AFTER-CREATE-FAULT")

        with patch.object(attachment_kernel, "_after_attachment_create", side_effect=fail):
            self._document_denied(self.document, reason="ATTACHMENT_UNAVAILABLE")
        self.assertEqual(observed, [(True, True)])
        self.assertFalse(self._attachments())
        self._attachment(self._created())

    def test_audit_fault_after_attachment_creation_rolls_back_pdf_and_receipt(self):
        observed = []

        def fail(event):
            observed.append((event.status, len(self._attachments())))
            raise RuntimeError("TCC-C109-AUDIT-AFTER-ATTACHMENT-FAULT")

        with patch.object(audit_kernel, "_after_audit_append", side_effect=fail):
            self._unavailable(self._create)
        self.assertEqual(observed, [("CREATED", 1)])
        self.assertFalse(self._attachments())
        self._attachment(self._created())

    def test_completion_fault_rolls_back_attachment_before_returning_success(self):
        with patch.object(audit_kernel, "_complete", side_effect=RuntimeError("TCC-C109-COMPLETION-FAULT")):
            self._unavailable(self._create)
        self.assertFalse(self._attachments())
        self._attachment(self._created())

    def test_failed_post_audit_preserves_original_pdf_and_rolls_back_nonce(self):
        self._prepare_post()
        attachment = self._attachment(self.created_result)
        before = attachment.raw
        with patch.object(audit_kernel, "_after_audit_append", side_effect=RuntimeError("TCC-C109-POST-AUDIT-FAULT")):
            self._unavailable(self._post)
        attachment.invalidate_recordset()
        self.assertEqual(attachment.raw, before)
        self.assertEqual(len(self._attachments()), 1)
        self.assertFalse(self._post_receipts())
        self.assertFalse(self._ledger())

    def test_attachment_serialization_failure_propagates_without_partial_effect(self):
        before = self._state_hash()
        with patch.object(attachment_kernel, "_after_attachment_create", side_effect=SerializationFailure("TCC-C109-ATTACHMENT-SERIALIZATION")):
            with unittest.TestCase.assertRaises(self, SerializationFailure):
                self._create()
        self.assertEqual(self._state_hash(), before)
        self.assertFalse(self._attachments())
        self.assertFalse(self._events())

    def test_c1_cannot_read_or_mutate_attachment_by_generic_model_access(self):
        result = self._created()
        attachment = self._attachment(result)
        restricted = api.Environment(self.env.cr, self.executor_user.id, {}, su=False)
        record = restricted["ir.attachment"].browse(attachment.id)
        for operation in (
            lambda: record.read(["raw"]), lambda: record.write({"public": True}), lambda: record.unlink(),
            lambda: restricted["ir.attachment"].create({"name": "TCC-C109-UNAUTHORIZED", "res_model": "account.move",
                "res_id": result["receipt"]["move_id"], "company_id": self.company.id, "raw": self.document_raw}),
        ):
            with unittest.TestCase.assertRaises(self, AccessError):
                operation()
        self._attachment(result)

    def test_event_contains_only_attachment_metadata_not_document_bytes(self):
        result = self._created()
        self._attachment(result)
        payload = _bytes(self._event(result).event_payload)
        self.assertFalse(self.document_raw in payload)
        self.assertFalse(b"DOCUMENTO SINTETICO SEM VALOR FISCAL" in payload)
        self.assertFalse(b"%PDF-" in payload)
