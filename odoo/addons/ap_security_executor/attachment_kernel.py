# SPDX-License-Identifier: LGPL-3.0-or-later
"""Private DB-only attachment primitive, called inside the audit savepoint.

There is no commit, import mixin, filename/path input, RPC method or filestore
fallback here. SQL rollback covers the native DB blob; caller-owned financial
locks/savepoints and audit integrity remain mandatory.
"""

import hashlib
import re

from psycopg2.errors import DeadlockDetected, SerializationFailure

from odoo import SUPERUSER_ID, api

from .draft_kernel import _context
from .document_contracts import (
    MAXIMUM_DOCUMENT_BYTES, DocumentContractError, SourceDocument,
    VerifiedSourceDocument, validate_source_document,
)


_HASH = re.compile(r"[0-9a-f]{64}\Z")
_METADATA_KEYS = frozenset({
    "schema_version", "attachment_id", "move_id", "document_sha256",
    "byte_count", "mimetype", "storage",
})
_ERROR_CODES = frozenset({
    "ATTACHMENT_CONFIG_INVALID", "ATTACHMENT_INTEGRITY_INVALID", "ATTACHMENT_UNAVAILABLE",
})


class AttachmentError(ValueError):
    """Finite safe failure, without native exception or input data."""

    def __init__(self, code="ATTACHMENT_UNAVAILABLE"):
        self.code = code if type(code) is str and code in _ERROR_CODES else "ATTACHMENT_UNAVAILABLE"
        super().__init__("Private document attachment rejected.")


def _private_environment(env, company_id):
    if (type(company_id) is not int or company_id <= 0
            or env.uid != SUPERUSER_ID or not env.su):
        raise AttachmentError("ATTACHMENT_CONFIG_INVALID")
    return api.Environment(env.cr, SUPERUSER_ID, _context(company_id), su=True)


def assert_attachment_environment(env, company_id):
    """Fail closed on configuration without changing global storage/defaults."""
    try:
        private = _private_environment(env, company_id)
        company = private["res.company"].browse(company_id).exists()
        if not company or not company.active or private["ir.attachment"]._storage() != "db":
            raise AttachmentError("ATTACHMENT_CONFIG_INVALID")
        if private["ir.module.module"].search_count([
                ("name", "=", "attachment_indexation"),
                ("state", "in", ["installed", "to upgrade", "to remove", "to install"]),
        ], limit=1):
            raise AttachmentError("ATTACHMENT_CONFIG_INVALID")
        if private["ir.default"].search_count([
                ("field_id.model", "=", "ir.attachment"),
                ("user_id", "in", [False, SUPERUSER_ID]),
                ("company_id", "in", [False, company_id]),
        ], limit=1):
            raise AttachmentError("ATTACHMENT_CONFIG_INVALID")
    except (SerializationFailure, DeadlockDetected, AttachmentError):
        raise
    except Exception:
        raise AttachmentError("ATTACHMENT_UNAVAILABLE") from None


def _after_attachment_create(attachment):
    """Private fault-injection seam after actual native ORM creation."""
    return None


def _filename(document_sha256):
    return "NF-SINTETICA-" + document_sha256 + ".pdf"


def _metadata(metadata, *, move_id, document_sha256):
    if (type(metadata) is not dict or set(metadata) != _METADATA_KEYS
            or type(metadata["schema_version"]) is not str or metadata["schema_version"] != "document-attachment/v1"
            or type(move_id) is not int or move_id <= 0
            or type(document_sha256) is not str or not _HASH.fullmatch(document_sha256)
            or type(metadata["attachment_id"]) is not int or metadata["attachment_id"] <= 0
            or type(metadata["move_id"]) is not int or metadata["move_id"] != move_id
            or type(metadata["document_sha256"]) is not str or metadata["document_sha256"] != document_sha256
            or type(metadata["byte_count"]) is not int
            or not 1 <= metadata["byte_count"] <= MAXIMUM_DOCUMENT_BYTES
            or type(metadata["mimetype"]) is not str or metadata["mimetype"] != "application/pdf"
            or type(metadata["storage"]) is not str or metadata["storage"] != "db"):
        raise AttachmentError("ATTACHMENT_INTEGRITY_INVALID")


def verify_document_attachment(env, metadata, *, company_id, move_id, document_sha256, lock=False):
    """Re-read the precise original record and immutable bytes, optionally lock.

    Caller must acquire its financial PO/target locks before ``lock=True``.
    Native SHA-1 is checked for storage consistency, never as document identity.
    """
    try:
        _metadata(metadata, move_id=move_id, document_sha256=document_sha256)
        if type(lock) is not bool:
            raise AttachmentError("ATTACHMENT_INTEGRITY_INVALID")
        assert_attachment_environment(env, company_id)
        private = _private_environment(env, company_id)
        move = private["account.move"].browse(move_id).exists()
        if not move or move.company_id.id != company_id or move.move_type != "in_invoice":
            raise AttachmentError("ATTACHMENT_INTEGRITY_INVALID")
        model = private["ir.attachment"]
        model.flush_model()
        if lock:
            private.cr.execute("SELECT id FROM ir_attachment WHERE id = %s FOR UPDATE", (metadata["attachment_id"],))
            if private.cr.fetchone() is None:
                raise AttachmentError("ATTACHMENT_INTEGRITY_INVALID")
        attachment = model.browse(metadata["attachment_id"]).exists()
        if not attachment:
            raise AttachmentError("ATTACHMENT_INTEGRITY_INVALID")
        attachment.invalidate_recordset()
        if (attachment.store_fname or attachment.res_model != "account.move" or attachment.res_id != move_id
                or attachment.company_id.id != company_id or attachment.type != "binary"
                or attachment.mimetype != "application/pdf" or attachment.public
                or attachment.access_token or attachment.url or attachment.res_field
                or attachment.name != _filename(document_sha256)
                or attachment.description != "SEM VALOR FISCAL" or attachment.index_content):
            raise AttachmentError("ATTACHMENT_INTEGRITY_INVALID")
        raw = attachment.raw
        if (type(raw) is not bytes or not raw or len(raw) > MAXIMUM_DOCUMENT_BYTES
                or not raw.startswith(b"%PDF-")
                or hashlib.sha256(raw).hexdigest() != document_sha256
                or len(raw) != metadata["byte_count"] or attachment.file_size != len(raw)
                or attachment.checksum != hashlib.sha1(raw).hexdigest()
                or attachment.db_datas != raw):
            raise AttachmentError("ATTACHMENT_INTEGRITY_INVALID")
        return attachment
    except (SerializationFailure, DeadlockDetected, AttachmentError):
        raise
    except Exception:
        raise AttachmentError("ATTACHMENT_UNAVAILABLE") from None


def create_document_attachment(env, *, move_id, company_id, document, verified):
    """Create and verify one native private DB blob; never commit the caller."""
    try:
        if type(document) is not SourceDocument or type(verified) is not VerifiedSourceDocument:
            raise AttachmentError("ATTACHMENT_INTEGRITY_INVALID")
        checked = validate_source_document(document, document_sha256=verified.document_sha256)
        if checked != verified:
            raise AttachmentError("ATTACHMENT_INTEGRITY_INVALID")
        assert_attachment_environment(env, company_id)
        private = _private_environment(env, company_id)
        if type(move_id) is not int or move_id <= 0:
            raise AttachmentError("ATTACHMENT_INTEGRITY_INVALID")
        move = private["account.move"].browse(move_id).exists()
        if not move or move.company_id.id != company_id or move.move_type != "in_invoice":
            raise AttachmentError("ATTACHMENT_INTEGRITY_INVALID")
        attachment = private["ir.attachment"].create({
            "name": _filename(checked.document_sha256), "description": "SEM VALOR FISCAL",
            "company_id": company_id, "type": "binary", "res_model": "account.move",
            "res_id": move_id, "raw": document.raw, "mimetype": "application/pdf",
            "public": False, "access_token": False, "url": False, "res_field": False,
        })
        _after_attachment_create(attachment)
        metadata = {"schema_version": "document-attachment/v1", "attachment_id": attachment.id,
            "move_id": move_id, "document_sha256": checked.document_sha256,
            "byte_count": checked.byte_count, "mimetype": checked.mimetype, "storage": "db"}
        verify_document_attachment(private, metadata, company_id=company_id, move_id=move_id,
                                   document_sha256=checked.document_sha256)
        return attachment, metadata
    except (SerializationFailure, DeadlockDetected, AttachmentError):
        raise
    except DocumentContractError:
        raise AttachmentError("ATTACHMENT_INTEGRITY_INVALID") from None
    except Exception:
        raise AttachmentError("ATTACHMENT_UNAVAILABLE") from None
