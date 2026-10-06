# SPDX-License-Identifier: LGPL-3.0-or-later
"""Offline, synthetic registry contracts; no Odoo or authority claims."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, fields, replace
import hashlib
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[2]
ADDON = ROOT / "odoo/addons/ap_security_executor"
PACKAGE = "_tcc_workflow_registry_contract_offline"
package = ModuleType(PACKAGE)
package.__path__ = [str(ADDON)]
sys.modules[PACKAGE] = package
contract = importlib.import_module(PACKAGE + ".workflow_contracts")
draft = importlib.import_module(PACKAGE + ".draft_contracts")
document = importlib.import_module(PACKAGE + ".document_contracts")

RAW = b"%PDF-1.4\nTCC WORKFLOW SINTETICO SEM VALOR FISCAL\n%%EOF\n"
RAW_HASH = hashlib.sha256(RAW).hexdigest()


def workflow():
    return draft.TrustedDraftWorkflow(
        company_id=1, executor_user_id=2, purchase_order_id=3, vendor_id=4,
        journal_id=5, expense_account_id=6, purchase_line_ids=(7,), allowed_bank_ids=(8,),
        scenario_id="TCC-SCN-001", document_sha256=RAW_HASH,
        policy_version="policy-v1.0.0", phase="DRAFT_INTAKE",
        invoice_date_min="2026-09-01", invoice_date_max="2026-09-30",
        quantity_scale=2, monetary_tolerance="0.00")


def provenance():
    return contract.WorkflowProvenance(code_commit="a" * 40,
        code_sha256="sha256:" + "b" * 64, configuration_sha256="sha256:" + "c" * 64)


def metadata():
    return document.VerifiedSourceDocument(RAW_HASH, len(RAW), "application/pdf")


def payload():
    return contract.registration_payload(workflow=workflow(), document_metadata=metadata(),
        provenance=provenance(), registrar_user_id=1)


def invalid_payload(value):
    with pytest.raises(contract.WorkflowContractError) as caught:
        contract.validate_registration_payload(value)
    assert "SENSITIVE" not in str(caught.value)
    assert RAW_HASH not in str(caught.value)
    return str(caught.value)


def resolved():
    value = payload()
    return contract.ResolvedDraftRegistration(registration_id=9,
        registration_sha256=contract.registration_sha256(value), workflow=workflow(),
        provenance=provenance(), document_metadata=metadata())


def test_registration_payload_closed_roundtrip_and_json_compatible():
    value = payload()
    assert set(value) == {"schema_version", "workflow", "document", "provenance", "registrar_user_id"}
    assert value["schema_version"] == "draft-workflow-registration/v1"
    rebuilt = contract.validate_registration_payload(json.loads(json.dumps(value)))
    assert rebuilt == (workflow(), metadata(), provenance(), 1)
    assert value["document"] == asdict(metadata())
    assert value["provenance"] == asdict(provenance())
    assert value["workflow"]["purchase_line_ids"] == [7]
    assert value["workflow"]["allowed_bank_ids"] == [8]
    assert len(value["workflow"]) == len(fields(draft.TrustedDraftWorkflow))


def test_registration_digest_is_stable_order_independent_and_domain_separated():
    value = payload()
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    digest = contract.registration_sha256(value)
    assert digest.startswith("sha256:") and len(digest) == 71
    assert digest != "sha256:" + hashlib.sha256(encoded).hexdigest()
    assert digest == contract.registration_sha256(dict(reversed(list(value.items()))))
    changed = deepcopy(value)
    changed["provenance"]["configuration_sha256"] = "sha256:" + "d" * 64
    assert contract.registration_sha256(changed) != digest
    assert value == payload()


def test_payload_is_detached_from_inputs_and_validation_is_nonmutating():
    value = payload(); original = deepcopy(value)
    contract.validate_registration_payload(value)
    assert value == original
    value["workflow"]["purchase_line_ids"].append(99)
    assert workflow().purchase_line_ids == (7,)


def test_resolved_registration_fields_are_exact_frozen_and_slot_only():
    value = resolved()
    assert {field.name for field in fields(value)} == {
        "registration_id", "registration_sha256", "workflow", "provenance", "document_metadata"}
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        value.registration_id = 10
    with pytest.raises(TypeError):
        contract.ResolvedDraftRegistration(**asdict(value), proposed_action={})


def test_provenance_fields_are_exact_frozen_and_slot_only():
    value = provenance()
    assert {field.name for field in fields(value)} == {"code_commit", "code_sha256", "configuration_sha256"}
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        value.code_commit = "d" * 40
    with pytest.raises(TypeError):
        contract.WorkflowProvenance(**asdict(value), token="SENSITIVE-MARKER")


@pytest.mark.parametrize("field", ["code_commit", "code_sha256", "configuration_sha256"])
@pytest.mark.parametrize("value", [None, True, 7, [], {}, "", "SENSITIVE-INVALID", "A" * 64])
def test_provenance_invalid_types_and_formats_do_not_echo(field, value):
    values = asdict(provenance()); values[field] = value
    with pytest.raises(contract.WorkflowContractError) as caught:
        contract.WorkflowProvenance(**values)
    assert "SENSITIVE" not in str(caught.value)


@pytest.mark.parametrize("value", [None, True, 0, -1, 1.0, "1", [], {}])
def test_resolved_registration_identity_is_a_strict_positive_integer(value):
    with pytest.raises(contract.WorkflowContractError):
        replace(resolved(), registration_id=value)


@pytest.mark.parametrize("value", [None, True, "a" * 64, "sha256:" + "A" * 64, "SENSITIVE-INVALID"])
def test_resolved_registration_hash_requires_canonical_prefixed_digest(value):
    with pytest.raises(contract.WorkflowContractError) as caught:
        replace(resolved(), registration_sha256=value)
    assert "SENSITIVE" not in str(caught.value)


@pytest.mark.parametrize("field", ["workflow", "provenance", "document_metadata"])
@pytest.mark.parametrize("value", [None, True, 3, {}, []])
def test_resolved_registration_rejects_untyped_or_mutable_components(field, value):
    with pytest.raises(contract.WorkflowContractError):
        replace(resolved(), **{field: value})


@pytest.mark.parametrize("key", ["raw", "document_bytes", "proposal", "label", "attack_family", "approval", "token", "signature", "nonce"])
def test_external_and_sensitive_top_level_keys_are_forbidden(key):
    value = payload(); value[key] = "SENSITIVE-MARKER"
    invalid_payload(value)


@pytest.mark.parametrize("key", ["schema_version", "workflow", "document", "provenance", "registrar_user_id"])
def test_required_top_level_keys_cannot_be_omitted(key):
    value = payload(); del value[key]
    invalid_payload(value)


@pytest.mark.parametrize("section", ["workflow", "document", "provenance"])
def test_unknown_nested_keys_fail_closed(section):
    value = payload(); value[section]["extra"] = "SENSITIVE-MARKER"
    invalid_payload(value)


@pytest.mark.parametrize("value", [None, True, 0, -1, 1.0, "1"])
def test_registrar_identity_strictly_positive_integer(value):
    data = payload(); data["registrar_user_id"] = value
    invalid_payload(data)


@pytest.mark.parametrize("field,value", [
    ("phase", "POST_REVIEW"), ("policy_version", "policy-v2.0.0"),
    ("invoice_date_min", "2026-09-31"), ("invoice_date_max", "2026-08-01"),
    ("quantity_scale", True), ("quantity_scale", 1),
    ("monetary_tolerance", "0.001"), ("company_id", True),
    ("purchase_line_ids", [7, 7]), ("purchase_line_ids", []),
    ("allowed_bank_ids", [8, 8]), ("allowed_bank_ids", []),
    ("purchase_line_ids", [8, 7]), ("allowed_bank_ids", [9, 8]),
    ("purchase_line_ids", list(range(1, 52))), ("allowed_bank_ids", list(range(1, 52))),
])
def test_workflow_semantic_contract_is_revalidated(field, value):
    data = payload(); data["workflow"][field] = value
    invalid_payload(data)


@pytest.mark.parametrize("field,value", [
    ("document_sha256", "d" * 64), ("byte_count", 0),
    ("byte_count", 1_048_577), ("byte_count", True), ("mimetype", "text/plain"),
])
def test_verified_document_metadata_is_revalidated_and_bound(field, value):
    data = payload(); data["document"][field] = value
    invalid_payload(data)


@pytest.mark.parametrize("value", [None, True, [], "SENSITIVE-MARKER"])
def test_nonobject_registration_payloads_have_finite_errors(value):
    invalid_payload(value)


def test_registration_version_is_closed_and_no_binary_or_authorization_is_stored():
    value = payload(); value["schema_version"] = "draft-workflow-registration/v2"
    invalid_payload(value)
    encoded = json.dumps(payload(), sort_keys=True)
    assert "SEM VALOR FISCAL" not in encoded
    assert "%PDF" not in encoded
    assert all(key not in payload() for key in ("raw", "proposal", "label", "approval", "signature", "nonce"))


@pytest.mark.parametrize("component,field,value", [
    ("workflow", "company_id", True), ("workflow", "phase", "POST_REVIEW"),
    ("provenance", "code_commit", "SENSITIVE-MARKER"),
    ("document_metadata", "byte_count", True),
])
def test_frozen_instances_are_reconstructed_after_low_level_mutation(component, field, value):
    data = {"workflow": workflow(), "provenance": provenance(), "document_metadata": metadata()}
    object.__setattr__(data[component], field, value)
    with pytest.raises(contract.WorkflowContractError) as caught:
        contract.registration_payload(**data, registrar_user_id=1)
    assert "SENSITIVE" not in str(caught.value)


def test_verified_document_maximum_byte_count_is_inclusive():
    value = payload(); value["document"]["byte_count"] = 1_048_576
    rebuilt = contract.validate_registration_payload(value)
    assert rebuilt[1].byte_count == 1_048_576


def test_payload_size_and_depth_are_bounded_before_schema_reconstruction():
    oversized = payload(); oversized["workflow"]["scenario_id"] = "SENSITIVE-" + "x" * 65_536
    invalid_payload(oversized)
    deep = "SENSITIVE-MARKER"
    for _ in range(10):
        deep = {"nested": deep}
    invalid_payload({"workflow": deep})
