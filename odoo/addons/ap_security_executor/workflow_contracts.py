# SPDX-License-Identifier: LGPL-3.0-or-later
"""Closed declaration of a private documentary workflow, never authority.

Provenance is supplied by trusted administrative code, not authenticated by
these hashes. Raw PDF bytes, proposals, approval data and labels are excluded.
"""

from dataclasses import asdict, dataclass, fields
import hashlib
import re

from .contracts import ExecutorContractError, _bytes, _snapshot
from .document_contracts import DocumentContractError, VerifiedSourceDocument
from .draft_contracts import TrustedDraftWorkflow


REGISTRATION_SCHEMA_VERSION = "draft-workflow-registration/v1"
REGISTRATION_HASH_DOMAIN = b"tcc-draft-workflow-registration/v1\0"


class WorkflowContractError(ValueError):
    """Finite, content-free contract diagnostic."""

    def __init__(self):
        super().__init__("Invalid private workflow registration contract.")


def _match(value, pattern):
    if type(value) is not str or re.fullmatch(pattern, value) is None:
        raise WorkflowContractError()


def _positive_id(value):
    if type(value) is not int or value <= 0:
        raise WorkflowContractError()


def reconstruct(value, cls):
    """Recheck exact objects rather than trusting frozen dataclass instances."""
    if type(value) is not cls:
        raise WorkflowContractError()
    try:
        return cls(**{item.name: getattr(value, item.name) for item in fields(cls)})
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise WorkflowContractError() from None


@dataclass(frozen=True, slots=True)
class WorkflowProvenance:
    code_commit: str
    code_sha256: str
    configuration_sha256: str

    def __post_init__(self):
        _match(self.code_commit, r"[0-9a-f]{40}")
        _match(self.code_sha256, r"sha256:[0-9a-f]{64}")
        _match(self.configuration_sha256, r"sha256:[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class ResolvedDraftRegistration:
    registration_id: int
    registration_sha256: str
    workflow: TrustedDraftWorkflow
    provenance: WorkflowProvenance
    document_metadata: VerifiedSourceDocument

    def __post_init__(self):
        _positive_id(self.registration_id)
        _match(self.registration_sha256, r"sha256:[0-9a-f]{64}")
        reconstruct(self.workflow, TrustedDraftWorkflow)
        reconstruct(self.provenance, WorkflowProvenance)
        document = reconstruct(self.document_metadata, VerifiedSourceDocument)
        if document.document_sha256 != self.workflow.document_sha256:
            raise WorkflowContractError()


def registration_payload(*, workflow, document_metadata, provenance, registrar_user_id):
    """Detached canonical declaration; the registrar is part of replay identity."""
    workflow = reconstruct(workflow, TrustedDraftWorkflow)
    metadata = reconstruct(document_metadata, VerifiedSourceDocument)
    provenance = reconstruct(provenance, WorkflowProvenance)
    _positive_id(registrar_user_id)
    if metadata.document_sha256 != workflow.document_sha256:
        raise WorkflowContractError()
    values = asdict(workflow)
    values["purchase_line_ids"] = list(workflow.purchase_line_ids)
    values["allowed_bank_ids"] = list(workflow.allowed_bank_ids)
    return {
        "schema_version": REGISTRATION_SCHEMA_VERSION,
        "workflow": values,
        "document": asdict(metadata),
        "provenance": asdict(provenance),
        "registrar_user_id": registrar_user_id,
    }


def validate_registration_payload(payload):
    """Return reconstructed closed objects after strict bounded JSON checks."""
    try:
        if type(payload) is not dict:
            raise WorkflowContractError()
        detached = _snapshot(payload)
        if set(detached) != {
            "schema_version", "workflow", "document", "provenance", "registrar_user_id",
        } or detached["schema_version"] != REGISTRATION_SCHEMA_VERSION:
            raise WorkflowContractError()
        workflow_values = detached["workflow"]
        metadata_values = detached["document"]
        provenance_values = detached["provenance"]
        for values, cls in (
            (workflow_values, TrustedDraftWorkflow),
            (metadata_values, VerifiedSourceDocument),
            (provenance_values, WorkflowProvenance),
        ):
            if type(values) is not dict or set(values) != {item.name for item in fields(cls)}:
                raise WorkflowContractError()
        for name in ("purchase_line_ids", "allowed_bank_ids"):
            if type(workflow_values[name]) is not list:
                raise WorkflowContractError()
            workflow_values[name] = tuple(workflow_values[name])
        workflow = TrustedDraftWorkflow(**workflow_values)
        metadata = VerifiedSourceDocument(**metadata_values)
        provenance = WorkflowProvenance(**provenance_values)
        registrar = detached["registrar_user_id"]
        _positive_id(registrar)
        if metadata.document_sha256 != workflow.document_sha256:
            raise WorkflowContractError()
        return workflow, metadata, provenance, registrar
    except (ExecutorContractError, DocumentContractError, AttributeError,
            TypeError, ValueError, OverflowError, RecursionError):
        raise WorkflowContractError() from None


def registration_sha256(payload):
    """Domain-separated integrity hash, not proof of administrator authenticity."""
    try:
        workflow, metadata, provenance, registrar = validate_registration_payload(payload)
        canonical = registration_payload(workflow=workflow, document_metadata=metadata,
            provenance=provenance, registrar_user_id=registrar)
        return "sha256:" + hashlib.sha256(REGISTRATION_HASH_DOMAIN + _bytes(canonical)).hexdigest()
    except (ExecutorContractError, TypeError, ValueError, OverflowError, RecursionError):
        raise WorkflowContractError() from None
