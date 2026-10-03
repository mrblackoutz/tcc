"""Synthetic C1-09 administrative contracts; no Odoo, API or financial effects.

The digest is an integrity identifier, not authenticated provenance or a full
scientific RunRecord. All values here are explicitly invented development data.
"""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, asdict, fields, replace
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[2]
ADDON = ROOT / "odoo/addons/ap_security_executor"
PACKAGE = "_tcc_audit_contracts_offline"
_package = ModuleType(PACKAGE)
_package.__path__ = [str(ADDON)]
sys.modules[PACKAGE] = _package


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contracts = _load(PACKAGE + ".contracts", ADDON / "contracts.py")
audit = _load(PACKAGE + ".audit_contracts", ADDON / "audit_contracts.py")


def _context(**changes):
    values = {
        "run_id": "TCC-SYNTHETIC-AUDIT-001", "attempt_id": "a" * 32,
        "code_commit": "b" * 40, "code_sha256": "sha256:" + "c" * 64,
        "configuration_sha256": "sha256:" + "d" * 64,
    }
    values.update(changes)
    return audit.TrustedAuditContext(**values)


def _invalid_context(**changes):
    with pytest.raises(audit.AuditContractError) as caught:
        _context(**changes)
    assert str(caught.value) == "Invalid operational audit contract."


def test_metadata_is_explicit_closed_frozen_and_has_no_secret_slot():
    value = _context()
    assert {field.name for field in fields(value)} == {
        "run_id", "attempt_id", "code_commit", "code_sha256", "configuration_sha256",
    }
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        value.run_id = "ANOTHER-RUN"
    with pytest.raises(TypeError):
        audit.TrustedAuditContext(**asdict(value), approval={})


@pytest.mark.parametrize("field", [
    "run_id", "attempt_id", "code_commit", "code_sha256", "configuration_sha256",
])
def test_every_metadata_field_is_required(field):
    values = asdict(_context())
    del values[field]
    with pytest.raises(TypeError):
        audit.TrustedAuditContext(**values)


@pytest.mark.parametrize("field,value", [
    ("run_id", None), ("run_id", True), ("run_id", 1), ("run_id", []),
    ("run_id", ""), ("run_id", "lowercase"), ("run_id", "_START"),
    ("run_id", "RUN/ONE"), ("run_id", "RUN ONE"), ("run_id", " RUN"),
    ("run_id", "RUN "), ("run_id", "RUN\n"), ("run_id", "RUN\u202e"),
    ("run_id", "A" * 65),
    ("attempt_id", None), ("attempt_id", 1), ("attempt_id", "A" * 32),
    ("attempt_id", "a" * 31), ("attempt_id", "a" * 33),
    ("attempt_id", "g" * 32), ("attempt_id", "a" * 32 + "\n"),
    ("code_commit", False), ("code_commit", {}), ("code_commit", "B" * 40),
    ("code_commit", "b" * 39), ("code_commit", "b" * 41),
    ("code_commit", "b" * 40 + "\n"),
    ("code_sha256", None), ("code_sha256", "c" * 64),
    ("code_sha256", "sha256:" + "C" * 64),
    ("code_sha256", "sha256:" + "c" * 63),
    ("code_sha256", "sha256:" + "c" * 65),
    ("code_sha256", "sha512:" + "c" * 64),
    ("configuration_sha256", True), ("configuration_sha256", "d" * 64),
    ("configuration_sha256", "sha256:" + "D" * 64),
    ("configuration_sha256", "sha256:" + "d" * 64 + "\n"),
    ("configuration_sha256", "SENSITIVE-MARKER"),
])
def test_metadata_rejects_coercion_noncanonical_text_and_unbounded_ids(field, value):
    _invalid_context(**{field: value})


def test_exact_ascii_metadata_boundaries_are_valid():
    value = _context(
        run_id="0" + ".-_A9" * 12 + "ABC", attempt_id="0" * 32,
        code_commit="f" * 40, code_sha256="sha256:" + "0" * 64,
        configuration_sha256="sha256:" + "f" * 64,
    )
    assert len(value.run_id) == 64
    assert value.attempt_id == "0" * 32
    assert _context(run_id="A").run_id == "A"


@pytest.mark.parametrize("field", [
    "run_id", "attempt_id", "code_commit", "code_sha256", "configuration_sha256",
])
def test_reconstruction_revalidates_even_tampered_frozen_slots(field):
    original = _context()
    object.__setattr__(original, field, "SENSITIVE-MARKER/INVALID")
    with pytest.raises(audit.AuditContractError) as caught:
        audit.TrustedAuditContext(**asdict(original))
    assert "SENSITIVE-MARKER" not in str(caught.value)


def test_dataclass_replacement_validates_without_mutating_original():
    original = _context()
    updated = replace(original, run_id="ANOTHER-SYNTHETIC-RUN")
    assert updated.run_id == "ANOTHER-SYNTHETIC-RUN"
    assert original.run_id == "TCC-SYNTHETIC-AUDIT-001"
    with pytest.raises(audit.AuditContractError):
        replace(original, attempt_id="invalid")


def test_exact_string_subclasses_are_not_promoted_to_trusted_metadata():
    class String(str):
        pass

    _invalid_context(run_id=String("VALID-LOOKING-RUN"))


def test_audit_hash_matches_independent_domain_separated_canonical_preimage():
    payload = {"schema_version": "development-audit/v1", "state": {"posted": False}, "ids": [11, 22]}
    expected = "sha256:" + hashlib.sha256(
        b"tcc-operational-audit/v1\0"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert audit.audit_digest(payload) == expected
    assert audit.audit_digest(payload) != "sha256:" + hashlib.sha256(contracts._bytes(payload)).hexdigest()


def test_hash_is_deterministic_under_key_order_and_does_not_mutate_payload():
    payload = {"z": [1, True, None], "a": {"b": "SEM-VALOR-FISCAL", "a": "ç"}}
    before = json.loads(json.dumps(payload))
    reordered = {"a": {"a": "ç", "b": "SEM-VALOR-FISCAL"}, "z": [1, True, None]}
    assert audit.audit_digest(payload) == audit.audit_digest(reordered)
    assert payload == before
    payload["z"].append(2)
    assert audit.audit_digest(payload) != audit.audit_digest(reordered)


def test_hash_keeps_list_order_and_exact_scalar_types():
    assert audit.audit_digest({"value": [1, 2]}) != audit.audit_digest({"value": [2, 1]})
    assert audit.audit_digest({"value": 1}) != audit.audit_digest({"value": "1"})
    assert audit.audit_digest({"value": True}) != audit.audit_digest({"value": 1})
    assert audit.audit_digest({"value": None}) != audit.audit_digest({"value": False})


@pytest.mark.parametrize("payload", [None, True, 1, "SENSITIVE-MARKER", [], (), object()])
def test_digest_requires_an_exact_dict_root(payload):
    with pytest.raises(audit.AuditContractError) as caught:
        audit.audit_digest(payload)
    assert str(caught.value) == "Invalid operational audit contract."


@pytest.mark.parametrize("value", [
    1.0, float("nan"), float("inf"), float("-inf"), b"SENSITIVE-MARKER",
    (1, 2), {1, 2}, object(), " bad", "bad ", "bad\n", "bad\u202e", "e\u0301", "\ud800",
])
def test_digest_rejects_unsupported_json_types_and_unsafe_text(value):
    with pytest.raises(audit.AuditContractError) as caught:
        audit.audit_digest({"value": value})
    assert str(caught.value) == "Invalid operational audit contract."


@pytest.mark.parametrize("key", [1, None, " bad", "bad ", "bad\n", "bad\u202e", "e\u0301"])
def test_digest_rejects_noncanonical_or_nonstring_dict_keys(key):
    with pytest.raises(audit.AuditContractError):
        audit.audit_digest({key: "SENSITIVE-MARKER"})


def test_digest_rejects_custom_json_classes_without_invoking_their_hooks():
    class DangerousDict(dict):
        def items(self):
            raise AssertionError("Caller dict hook was executed.")

    class DangerousList(list):
        def __iter__(self):
            raise AssertionError("Caller list hook was executed.")

    class DangerousInt(int):
        def __str__(self):
            raise AssertionError("Caller integer hook was executed.")

    for payload in (DangerousDict(), {"v": DangerousDict()}, {"v": DangerousList()}, {"v": DangerousInt(1)}):
        with pytest.raises(audit.AuditContractError):
            audit.audit_digest(payload)


def test_digest_rejects_cyclic_json_without_recursion_or_sensitive_echo():
    payload = {}
    payload["self"] = payload
    with pytest.raises(audit.AuditContractError) as caught:
        audit.audit_digest(payload)
    assert str(caught.value) == "Invalid operational audit contract."


@pytest.mark.parametrize("payload", [
    {"oversized": "X" * contracts.MAX_COMMAND_BYTES},
    {"oversized": [None] * contracts.MAX_COMMAND_BYTES},
    {"oversized": "ç" * (contracts.MAX_COMMAND_BYTES // 2)},
    {"oversized": "\\" * (contracts.MAX_COMMAND_BYTES // 2)},
    {"oversized": 1 << (contracts.MAX_COMMAND_BYTES * 4 + 1)},
])
def test_digest_enforces_byte_budget_before_unbounded_serialization(payload):
    with pytest.raises(audit.AuditContractError):
        audit.audit_digest(payload)


def test_digest_enforces_depth_budget_on_closed_json_trees():
    payload = {"leaf": True}
    for _ in range(contracts.MAX_COMMAND_DEPTH + 1):
        payload = {"nested": payload}
    with pytest.raises(audit.AuditContractError):
        audit.audit_digest(payload)


def test_empty_json_object_is_a_valid_integrity_preimage_not_a_valid_event():
    # Event semantics belong to the private writer, not this general digest.
    assert audit.audit_digest({}).startswith("sha256:")
    assert len(audit.audit_digest({})) == 71


def test_audit_contracts_remain_stdlib_only_without_odoo_io_or_gateway_imports():
    tree = ast.parse((ADDON / "audit_contracts.py").read_text(encoding="utf-8"))
    forbidden = {"odoo", "tcc_gateway", "requests", "httpx", "socket", "subprocess", "jsonschema"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not ({alias.name.split(".")[0] for alias in node.names} & forbidden)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            assert node.module.split(".")[0] not in forbidden
