"""Synthetic C1-07 issuer/verifier parity; no reusable grant is stored.

Keys, nonces and MACs exist only in test memory. These tests do not authorize
the public executor, consume a nonce or represent a final experimental corpus.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, fields, replace
from datetime import datetime, timedelta, timezone, tzinfo
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import secrets
import sys
from types import ModuleType

import pytest

from tcc_gateway.approval import ApprovalKey, issue_approval_fixture
from tcc_gateway.policy_contracts import CanonicalAction


ROOT = Path(__file__).resolve().parents[2]
ADDON = ROOT / "odoo/addons/ap_security_executor"
PACKAGE = "_tcc_approval_offline"
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
draft = _load(PACKAGE + ".draft_contracts", ADDON / "draft_contracts.py")
approval = _load(PACKAGE + ".approval", ADDON / "approval.py")
DOMAIN = b"tcc-approval-fixture/hmac-sha256/v1\0"


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _snapshot_hash(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _action(**changes):
    vector = json.loads((ROOT / "gateway/tests/fixtures/canonical_action_v1.vector.json").read_text(encoding="utf-8"))
    data = vector["action"]
    data.update(action="POST_VENDOR_BILL", executor_mode="POST_APPROVED", target_move_id=123)
    data.update(changes)
    return CanonicalAction.from_mapping(data)


def _fixture(*, size=32, fractional=False):
    action = _action()
    material = secrets.token_bytes(size)
    key = ApprovalKey(company_id=11, key_id="tcc-synthetic-approval-v1", material=material)
    issued = "2026-10-01T12:00:00.123456Z" if fractional else "2026-10-01T12:00:00Z"
    expires = "2026-10-01T12:10:00.654321Z" if fractional else "2026-10-01T12:10:00Z"
    data = {
        "company_id": 11, "executor_user_id": 22, "fixture_id": "TCC-APR-001",
        "scenario_id": action.scenario_id, "approver_ref": "TCC-SYNTHETIC-APPROVER",
        "nonce": secrets.token_urlsafe(24), "issued_at": issued, "expires_at": expires,
        "key_id": key.key_id,
    }
    authority = approval.ApprovalAuthority(**data)
    fixture = issue_approval_fixture(
        action, company_id=data["company_id"], fixture_id=data["fixture_id"],
        approver_ref=data["approver_ref"], nonce=data["nonce"], issued_at=issued,
        expires_at=expires, key=key,
    )
    command = {
        "schema_version": "capability-command/v1", "action": action.to_mapping(),
        "idempotency_key": "sha256:" + "c" * 64,
        "policy_decision": {
            "schema_version": "policy-decision/v1", "decision": "REVIEW",
            "reason_codes": ["CRITICAL_ACTION_REQUIRES_APPROVAL"],
            "proposed_action_hash": action.action_hash, "input_sha256": "sha256:" + "d" * 64,
            "policy_version": action.policy_version, "allowed_executor": "post_bill_executor",
            "deny_class": None, "evaluated_at": issued, "expires_at": expires,
        },
        "approval": fixture.to_mapping(),
    }
    return {
        "action": action, "command": command, "authority": authority,
        "gateway_key": key, "key": approval.ApprovalKey(**asdict(key)),
        "now": datetime(2026, 10, 1, 12, 5, tzinfo=timezone.utc),
    }


def _verify(value, **changes):
    args = {
        "trusted_action": value["action"].to_mapping(), "authority": value["authority"],
        "key": value["key"], "now": value["now"],
    }
    args.update(changes)
    return approval.verify_approval(value["command"], **args)


def _denied(value, *, code=None, **changes):
    with pytest.raises(approval.ApprovalVerificationError) as caught:
        _verify(value, **changes)
    assert caught.value.code in {
        "CONTRACT_INVALID", "BINDING_MISMATCH", "SIGNATURE_INVALID",
        "NOT_YET_VALID", "EXPIRED", "DEPENDENCY_UNAVAILABLE",
    }
    if code is not None:
        assert caught.value.code == code
    assert "SENSITIVE-MARKER" not in str(caught.value)


@pytest.mark.parametrize("size", [32, 48, 64])
def test_runtime_issuer_authenticates_with_independent_addon_and_exact_preimage(size):
    value = _fixture(size=size)
    body = value["command"]["approval"]
    unsigned = {name: item for name, item in body.items() if name != "signature"}
    expected = "hmac-sha256/v1:" + hmac.new(
        value["gateway_key"].material, DOMAIN + _json_bytes({"company_id": 11, "approval": unsigned}), hashlib.sha256,
    ).hexdigest()
    # A boolean assertion cannot print a reusable MAC if a regression fails.
    assert hmac.compare_digest(expected, body["signature"])
    verified = _verify(value)
    assert verified.action_hash == value["action"].action_hash
    assert verified.command_sha256 == draft.canonical_command_sha256(value["command"])
    assert verified.key_id == value["key"].key_id
    assert verified.fixture_id == "TCC-APR-001"
    assert verified.scenario_id == value["action"].scenario_id
    assert verified.approver_ref == "TCC-SYNTHETIC-APPROVER"
    assert verified.issued_at == body["issued_at"]
    assert verified.expires_at == body["expires_at"]
    assert verified.approval_sha256.startswith("sha256:")
    assert verified.nonce_sha256.startswith("sha256:")
    assert not ({"signature", "nonce", "material", "key"} & {field.name for field in fields(verified)})
    assert "signature" not in repr(verified)


def test_verification_is_deterministic_read_only_and_does_not_consume_nonce():
    value = _fixture()
    before = _snapshot_hash(value["command"])
    first = _verify(value)
    second = _verify(value)
    assert first == second
    assert _snapshot_hash(value["command"]) == before
    assert contracts.canonical_action_bytes(value["command"]["action"]) == value["action"].canonical_bytes


@pytest.mark.parametrize("name,replacement", [
    ("fixture_id", "TCC-APR-CHANGED"), ("scenario_id", "TCC-SCN-CHANGED"),
    ("approver_ref", "TCC-OTHER-APPROVER"), ("decision", "DENY"),
    ("canonical_action_hash", "sha256:" + "e" * 64), ("nonce", "OTHER-SYNTHETIC-NONCE"),
    ("issued_at", "2026-10-01T12:00:01Z"), ("expires_at", "2026-10-01T12:10:01Z"),
    ("key_id", "other-key-v1"),
])
def test_each_signed_claim_cannot_be_altered_without_a_new_mac(name, replacement):
    value = _fixture()
    value["command"]["approval"][name] = replacement
    _denied(value)


@pytest.mark.parametrize("name,replacement", [
    ("fixture_id", "TCC-APR-CHANGED"), ("scenario_id", "TCC-SCN-CHANGED"),
    ("approver_ref", "TCC-OTHER-APPROVER"), ("nonce", "OTHER-SYNTHETIC-NONCE"),
    ("issued_at", "2026-10-01T12:00:01Z"), ("expires_at", "2026-10-01T12:10:01Z"),
    ("key_id", "other-key-v1"), ("company_id", 12),
])
def test_valid_mac_does_not_replace_frozen_manifest_authority(name, replacement):
    value = _fixture()
    _denied(value, authority=replace(value["authority"], **{name: replacement}))


@pytest.mark.parametrize("changes", [
    {"vendor_ref": "TCC-OTHER-VENDOR"}, {"purchase_order_ref": "TCC-OTHER-PO"},
    {"document_ref": "TCC-OTHER-NF-SEM-VALOR-FISCAL"}, {"invoice_date": "2026-10-01"},
    {"currency": "USD"}, {"recipient_bank_ref": "TCC-OTHER-BANK"}, {"target_move_id": 124},
    {"document_sha256": "f" * 64}, {"scenario_id": "TCC-OTHER-SCN"},
    {"policy_version": "policy-v1.0.1"},
    {"amount": "126.50", "lines": [{"item_code": "TCC-SERVICE-001", "quantity": "1.00", "unit_price": "126.50"}]},
    {"amount": "251.00", "lines": [{"item_code": "TCC-SERVICE-001", "quantity": "2.00", "unit_price": "125.50"}]},
    {"lines": [{"item_code": "TCC-OTHER-ITEM", "quantity": "1.00", "unit_price": "125.50"}]},
])
def test_trusted_full_action_cannot_be_substituted_by_a_signed_proposal(changes):
    value = _fixture()
    _denied(value, trusted_action=_action(**changes).to_mapping(), code="BINDING_MISMATCH")


@pytest.mark.parametrize("signature", [
    "SENSITIVE-MARKER", "hmac-sha256/v2:" + "0" * 64,
    "none/v1:" + "0" * 64, "hmac-sha256/v1:" + "0" * 63,
    "hmac-sha256/v1:" + "0" * 65, "hmac-sha256/v1:" + "A" * 64,
    "hmac-sha256/v1:" + "g" * 64, "hmac-sha256/v1:" + "0" * 64 + "=",
    "hmac-sha256/v1:" + "0" * 64 + "\n", " hmac-sha256/v1:" + "0" * 64,
])
def test_only_exact_versioned_lower_hex_mac_is_accepted(signature):
    value = _fixture()
    value["command"]["approval"]["signature"] = signature
    _denied(value)


def test_wrong_runtime_key_and_company_signature_domain_are_rejected():
    value = _fixture()
    wrong_key = approval.ApprovalKey(company_id=11, key_id=value["key"].key_id, material=secrets.token_bytes(32))
    _denied(value, key=wrong_key, code="SIGNATURE_INVALID")
    body = value["command"]["approval"]
    unsigned = {name: item for name, item in body.items() if name != "signature"}
    body["signature"] = "hmac-sha256/v1:" + hmac.new(
        value["gateway_key"].material, DOMAIN + _json_bytes({"company_id": 12, "approval": unsigned}), hashlib.sha256,
    ).hexdigest()
    _denied(value, code="SIGNATURE_INVALID")


@pytest.mark.parametrize("now,code", [
    (datetime(2026, 10, 1, 11, 59, 59, 999999, tzinfo=timezone.utc), "NOT_YET_VALID"),
    (datetime(2026, 10, 1, 12, 10, tzinfo=timezone.utc), "EXPIRED"),
    (datetime(2026, 10, 1, 12, 10, 0, 1, tzinfo=timezone.utc), "EXPIRED"),
])
def test_approval_time_is_half_open_without_implicit_clock_skew(now, code):
    _denied(_fixture(), now=now, code=code)


@pytest.mark.parametrize("now", [
    datetime(2026, 10, 1, 12, tzinfo=timezone.utc),
    datetime(2026, 10, 1, 12, 9, 59, 999999, tzinfo=timezone.utc),
])
def test_approval_time_includes_issuance_but_not_expiration(now):
    value = _fixture()
    assert _verify(value, now=now).fixture_id == "TCC-APR-001"


def test_fractional_utc_boundaries_preserve_microsecond_precision():
    value = _fixture(fractional=True)
    assert _verify(value, now=datetime(2026, 10, 1, 12, 0, 0, 123456, tzinfo=timezone.utc)).fixture_id == "TCC-APR-001"
    _denied(value, now=datetime(2026, 10, 1, 12, 0, 0, 123455, tzinfo=timezone.utc), code="NOT_YET_VALID")
    _denied(value, now=datetime(2026, 10, 1, 12, 10, 0, 654321, tzinfo=timezone.utc), code="EXPIRED")


@pytest.mark.parametrize("name,replacement,code", [
    ("evaluated_at", "2026-10-01T12:06:00Z", "NOT_YET_VALID"),
    ("expires_at", "2026-10-01T12:05:00Z", "EXPIRED"),
])
def test_policy_decision_window_is_checked_independently_of_token(name, replacement, code):
    value = _fixture()
    value["command"]["policy_decision"][name] = replacement
    _denied(value, code=code)


@pytest.mark.parametrize("now", [None, "2026-10-01T12:05:00Z", 1, True, datetime(2026, 10, 1, 12, 5), datetime(2026, 10, 1, 14, 5, tzinfo=timezone(timedelta(hours=2)))])
def test_missing_untyped_naive_or_non_utc_clock_fails_closed(now):
    _denied(_fixture(), now=now, code="DEPENDENCY_UNAVAILABLE")


@pytest.mark.parametrize("field,value", [
    ("fixture_id", None), ("scenario_id", True), ("approver_ref", []),
    ("nonce", ""), ("nonce", "x" * 129), ("nonce", "has space"),
    ("signature", None), ("signature", []), ("signature", "x" * 4097),
    ("issued_at", "2026-10-01T12:00:00+00:00"), ("issued_at", "2026-02-30T12:00:00Z"),
    ("issued_at", "2026-10-01T12:00:00.1234567Z"), ("expires_at", "2026-10-01T12:00:00Z"),
    ("expires_at", "2026-10-01T11:00:00Z"), ("key_id", "UPPERCASE"),
    ("approver_ref", "TCC-APPROVER\u200b"), ("fixture_id", "TCC-APR\u202e"),
])
def test_malformed_token_is_structurally_denied_without_echo(field, value):
    data = _fixture()
    data["command"]["approval"][field] = value
    _denied(data, code="CONTRACT_INVALID")


@pytest.mark.parametrize("extra", ["schema_version", "algorithm", "context", "key", "issuer"])
def test_unknown_token_fields_and_schema_are_not_silently_ignored(extra):
    value = _fixture()
    value["command"]["approval"][extra] = "SENSITIVE-MARKER"
    _denied(value, code="CONTRACT_INVALID")


@pytest.mark.parametrize("value", [None, {}, [], object()])
def test_missing_or_untyped_trusted_dependencies_fail_closed(value):
    data = _fixture()
    _denied(data, key=value, code="DEPENDENCY_UNAVAILABLE")
    _denied(data, authority=value, code="DEPENDENCY_UNAVAILABLE")


def test_frozen_authority_and_key_are_revalidated_after_object_tampering():
    value = _fixture()
    with pytest.raises(FrozenInstanceError):
        value["authority"].company_id = 999
    with pytest.raises(FrozenInstanceError):
        value["key"].company_id = 999
    object.__setattr__(value["key"], "material", b"")
    _denied(value, code="DEPENDENCY_UNAVAILABLE")
    value = _fixture()
    object.__setattr__(value["authority"], "executor_user_id", True)
    _denied(value, code="DEPENDENCY_UNAVAILABLE")


def test_clock_exception_is_sanitized_as_dependency_unavailability():
    class UnavailableClock(tzinfo):
        def utcoffset(self, dt):
            raise RuntimeError("SENSITIVE-MARKER")

    _denied(
        _fixture(), now=datetime(2026, 10, 1, 12, 5, tzinfo=UnavailableClock()),
        code="DEPENDENCY_UNAVAILABLE",
    )


@pytest.mark.parametrize("dependency,attribute", [("key", "material"), ("authority", "nonce")])
def test_deleted_frozen_configuration_slot_is_sanitized(dependency, attribute):
    value = _fixture()
    object.__delattr__(value[dependency], attribute)
    _denied(value, code="DEPENDENCY_UNAVAILABLE")


@pytest.mark.parametrize("key_changes", [{"company_id": True}, {"company_id": 0}, {"key_id": "UPPER"}, {"material": b""}, {"material": bytes(31)}, {"material": bytes(65)}, {"material": bytearray(32)}, {"material": "SENSITIVE-MARKER"}])
def test_key_types_lengths_and_identity_are_validated_by_both_implementations(key_changes):
    values = {"company_id": 11, "key_id": "tcc-synthetic-approval-v1", "material": secrets.token_bytes(32)}
    values.update(key_changes)
    for cls in (ApprovalKey, approval.ApprovalKey):
        with pytest.raises(ValueError) as caught:
            cls(**values)
        assert "SENSITIVE-MARKER" not in str(caught.value)


def test_repr_hides_runtime_key_material_and_issuer_rejects_company_key_substitution():
    value = _fixture()
    assert "material=" not in repr(value["gateway_key"])
    assert "material=" not in repr(value["key"])
    with pytest.raises(ValueError):
        issue_approval_fixture(
            value["action"], company_id=12, fixture_id="TCC-APR-001", approver_ref="TCC-SYNTHETIC-APPROVER",
            nonce=secrets.token_urlsafe(24), issued_at="2026-10-01T12:00:00Z", expires_at="2026-10-01T12:10:00Z", key=value["gateway_key"],
        )


def test_whole_command_version_cycles_oversize_and_missing_approval_are_rejected():
    for mutation in ("version", "cycle", "oversize", "missing", "create"):
        value = _fixture()
        if mutation == "version":
            value["command"]["schema_version"] = "capability-command/v999"
        elif mutation == "cycle":
            value["command"]["loop"] = value["command"]
        elif mutation == "oversize":
            value["command"]["approval"]["signature"] = "x" * 65_537
        elif mutation == "missing":
            value["command"].pop("approval")
        else:
            value["command"]["action"].update(action="CREATE_DRAFT_BILL", executor_mode="CREATE_DRAFT")
            value["command"]["action"].pop("target_move_id")
        _denied(value, code="CONTRACT_INVALID")


def test_addon_verifier_is_stdlib_only_and_has_no_io_or_gateway_dependency():
    import ast

    tree = ast.parse((ADDON / "approval.py").read_text(encoding="utf-8"))
    forbidden = {"odoo", "tcc_gateway", "jsonschema", "requests", "httpx", "socket", "subprocess"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not ({alias.name.split(".")[0] for alias in node.names} & forbidden)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            assert node.module.split(".")[0] not in forbidden
