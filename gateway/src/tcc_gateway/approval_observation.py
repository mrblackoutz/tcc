"""DEC-076 bounded, sanitized approval observations (stdlib only).

This parser authenticates neither the administrative producer nor a signature.
It preserves declared uncertain timing for the separate attribution assessor.
Financial canonical validation remains in the existing native/gateway helpers.
No approval token, raw nonce, key or secret authority belongs to this envelope.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import re
import unicodedata


VERSION = "approval-observation/v1"
MAX_OBSERVATION_BYTES = 65_536
REJECTED_REASON_CODES = frozenset({"CONTRACT_INVALID", "BINDING_MISMATCH", "SIGNATURE_INVALID",
                                   "NOT_YET_VALID", "EXPIRED", "NONCE_REUSED"})
INDETERMINATE_REASON_CODES = frozenset({"DEPENDENCY_UNAVAILABLE", "IDENTITY_INVALID",
                                      "RESERVATION_INVALID", "DECISION_WINDOW_MISMATCH"})
REASON_CODES = REJECTED_REASON_CODES | INDETERMINATE_REASON_CODES | {"APPROVAL_ABSENT"}
_FIELDS = frozenset({"schema_version", "binding", "reference_action", "verification",
                     "nonce_available", "timing", "decision_window"})
_BINDING = frozenset({"run_id", "condition", "company_id", "executor_user_id", "scenario_id",
    "document_sha256", "code_commit", "configuration_sha256", "before_capture_sha256",
    "host_id", "clock_id"})
_ACTION = frozenset({"canonicalization_version", "action_schema_version", "policy_version",
    "action", "executor_mode", "scenario_id", "document_sha256", "vendor_ref",
    "purchase_order_ref", "document_ref", "invoice_date", "currency", "amount",
    "recipient_bank_ref", "lines", "target_move_id"})
_METADATA = frozenset({"action_hash", "approval_sha256", "nonce_sha256", "command_sha256",
    "key_id", "fixture_id", "scenario_id", "approver_ref", "issued_at", "expires_at"})
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", re.ASCII)
_SCENARIO = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,63}", re.ASCII)
_VERSION = re.compile(r"[a-z][a-z0-9._/-]{0,63}", re.ASCII)
_REFERENCE = re.compile(r"[A-Z0-9][A-Z0-9._ /-]{0,95}", re.ASCII)
_UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z", re.ASCII)


class ApprovalObservationError(ValueError):
    """Finite message; never echo the received value or secret-bearing inputs."""


def _fail():
    raise ApprovalObservationError("invalid sanitized approval observation") from None


def _closed(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        _fail()


def _matched(value, pattern):
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail()


def _digest(value, *, length=64, prefixed=False):
    expression = ("sha256:" if prefixed else "") + r"[0-9a-f]{%d}" % length
    if type(value) is not str or re.fullmatch(expression, value, re.ASCII) is None:
        _fail()


def _positive_id(value):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        _fail()


def _utc(value):
    _matched(value, _UTC)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail()


def _snapshot(value):
    """Reject cyclic/custom values before serialization; return a detached tree."""
    budget = [0]
    ancestors = set()

    def visit(item, depth):
        budget[0] += 1
        if depth > 12 or budget[0] > MAX_OBSERVATION_BYTES:
            _fail()
        if type(item) is str:
            if len(item) > MAX_OBSERVATION_BYTES:
                _fail()
            if (unicodedata.normalize("NFC", item) != item
                    or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in item)):
                _fail()
            budget[0] += len(item.encode("utf-8"))
        elif item is None or type(item) is bool:
            pass
        elif type(item) is int:
            if item.bit_length() > 63:
                _fail()
        elif type(item) in {dict, list}:
            identity = id(item)
            if identity in ancestors:
                _fail()
            ancestors.add(identity)
            try:
                if type(item) is dict:
                    for key, child in item.items():
                        if type(key) is not str:
                            _fail()
                        visit(key, depth + 1)
                        visit(child, depth + 1)
                else:
                    for child in item:
                        visit(child, depth + 1)
            finally:
                ancestors.remove(identity)
        else:
            _fail()
        if budget[0] > MAX_OBSERVATION_BYTES:
            _fail()

    if type(value) is not dict:
        _fail()
    visit(value, 0)
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_OBSERVATION_BYTES:
        _fail()
    return json.loads(encoded)


def _reference_action(action):
    """Structural shape only; existing canonicalizers validate financial facts."""
    _closed(action, _ACTION)
    if (action["canonicalization_version"] != "canon/v1"
            or action["action_schema_version"] != "vendor-bill-action-proposal/v2"
            or action["action"] != "POST_VENDOR_BILL" or action["executor_mode"] != "POST_APPROVED"):
        _fail()
    _positive_id(action["target_move_id"])
    _matched(action["policy_version"], _VERSION)
    _matched(action["scenario_id"], _SCENARIO)
    _digest(action["document_sha256"])
    for name in ("vendor_ref", "purchase_order_ref", "document_ref", "recipient_bank_ref"):
        _matched(action[name], _REFERENCE)
    for name in ("invoice_date", "currency", "amount"):
        if type(action[name]) is not str or not 1 <= len(action[name]) <= 32:
            _fail()
    if type(action["lines"]) is not list or not 1 <= len(action["lines"]) <= 50:
        _fail()
    for line in action["lines"]:
        _closed(line, {"item_code", "quantity", "unit_price"})
        _matched(line["item_code"], _REFERENCE)
        for field in ("quantity", "unit_price"):
            if type(line[field]) is not str or not 1 <= len(line[field]) <= 32:
                _fail()


def reference_action_sha256(value):
    """Hash a detached structurally closed action; this is not authentication."""
    try:
        action = _snapshot(value)
        _reference_action(action)
        encoded = json.dumps(action, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                             allow_nan=False).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError, RuntimeError):
        _fail()


def parse_approval_observation(value):
    """Validate closed metadata and return a detached sanitized mapping.

    Partial, reversed or out-of-window call intervals remain evidence, not an
    implicitly valid authorization. The attribution assessor decides that gate.
    """
    try:
        result = _snapshot(value)
        _closed(result, _FIELDS)
        if result["schema_version"] != VERSION:
            _fail()
        binding = result["binding"]
        _closed(binding, _BINDING)
        _digest(binding["run_id"], length=32)
        _digest(binding["code_commit"], length=40)
        for name in ("document_sha256", "configuration_sha256", "before_capture_sha256"):
            _digest(binding[name])
        for name in ("company_id", "executor_user_id"):
            _positive_id(binding[name])
        for name in ("host_id", "clock_id"):
            _matched(binding[name], _IDENTIFIER)
        _matched(binding["scenario_id"], _SCENARIO)
        if type(binding["condition"]) is not str or binding["condition"] not in {"C0", "C1"}:
            _fail()
        action = result["reference_action"]
        _reference_action(action)
        if any(action[name] != binding[name] for name in ("scenario_id", "document_sha256")):
            _fail()
        verification = result["verification"]
        _closed(verification, {"status", "reason_code", "metadata"})
        status, reason, metadata = (verification[name] for name in ("status", "reason_code", "metadata"))
        if type(status) is not str or status not in {"VERIFIED", "REJECTED", "ABSENT", "INDETERMINATE"}:
            _fail()
        if status == "VERIFIED":
            if reason is not None:
                _fail()
            _closed(metadata, _METADATA)
            for name in ("action_hash", "approval_sha256", "nonce_sha256", "command_sha256"):
                _digest(metadata[name], prefixed=True)
            if metadata["action_hash"] != reference_action_sha256(action):
                _fail()
            _matched(metadata["key_id"], _VERSION)
            for name in ("fixture_id", "approver_ref"):
                _matched(metadata[name], _REFERENCE)
            if metadata["scenario_id"] != binding["scenario_id"]:
                _fail()
            if _utc(metadata["issued_at"]) >= _utc(metadata["expires_at"]):
                _fail()
        else:
            permitted = {"REJECTED": REJECTED_REASON_CODES, "INDETERMINATE": INDETERMINATE_REASON_CODES,
                         "ABSENT": {"APPROVAL_ABSENT"}}[status]
            if metadata is not None or type(reason) is not str or reason not in permitted:
                _fail()
        if result["nonce_available"] is not None and type(result["nonce_available"]) is not bool:
            _fail()
        timing = result["timing"]
        _closed(timing, {"checked_at", "call_started_at", "call_finished_at", "started_ns", "finished_ns"})
        _utc(timing["checked_at"])
        for name in ("call_started_at", "call_finished_at"):
            if timing[name] is not None:
                _utc(timing[name])
        for name in ("started_ns", "finished_ns"):
            if timing[name] is not None and (type(timing[name]) is not int or timing[name] < 0):
                _fail()
        window = result["decision_window"]
        _closed(window, {"evaluated_at", "expires_at"})
        if _utc(window["evaluated_at"]) >= _utc(window["expires_at"]):
            _fail()
        return result
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError, RuntimeError):
        _fail()
