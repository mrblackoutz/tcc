# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-079 bounded private POST capsule in the existing Odoo /tmp tmpfs.

Standard library clock contracts only: no Odoo, schema engine, issuance or logging. Native
callers use the fixed directory and current UID. Explicit directory/UID options
exist for isolated filesystem tests, never to choose authority from a token.
These checks preserve custody and bindings; the native verifier must still
authenticate the grant and the Linux clock contract must validate its domain.
"""

from datetime import datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat


PRIVATE_ROOT = Path("/tmp")
MAX_CAPSULE_BYTES = 32 * 1024
VERSION = "gateway-post-capsule/v1"
CAPSULE_KEYS = {"schema_version", "binding", "preissued", "origin", "create_result",
                "reference_command", "authority", "key_material"}
BINDING_KEYS = {"proof_run_id", "run_id", "database", "variant", "condition", "git_base",
                "source_bundle_sha256", "configuration_sha256", "fixture_manifest_sha256",
                "company_id", "principal_id"}
PREISSUED_KEYS = {"schema_version", "proof_run_id", "run_id", "database", "variant", "condition",
    "git_base", "source_bundle_sha256", "clock_domain", "clock_scope", "preissued_at_ns", "preissued_at_utc",
    "reference_action", "reference_command_sha256", "approval_sha256", "principal_id",
    "original_create_authenticated"}
ORIGIN_KEYS = {"create_receipt_id", "create_event_id", "create_event_sha256", "target_move_id", "origin_sha256"}
AUTHORITY_KEYS = {"company_id", "executor_user_id", "fixture_id", "scenario_id", "approver_ref",
                  "nonce", "issued_at", "expires_at", "key_id"}
ACTION_KEYS = {"canonicalization_version", "action_schema_version", "policy_version", "action",
    "executor_mode", "scenario_id", "document_sha256", "vendor_ref", "purchase_order_ref", "document_ref",
    "invoice_date", "currency", "amount", "recipient_bank_ref", "lines", "target_move_id"}
POLICY_KEYS = {"schema_version", "decision", "reason_codes", "proposed_action_hash", "input_sha256",
               "policy_version", "allowed_executor", "deny_class", "evaluated_at", "expires_at"}
APPROVAL_KEYS = {"fixture_id", "scenario_id", "approver_ref", "decision", "canonical_action_hash",
                 "nonce", "issued_at", "expires_at", "key_id", "signature"}
CLOCK_KEYS = {"schema_version", "boot_sha256", "time_namespace_sha256", "offsets_sha256",
              "implementation", "host_id", "clock_id", "domain_sha256"}


def _fail():
    raise ValueError("GATEWAY_POST_CUSTODY_INVALID") from None


def _require(value):
    if not value:
        _fail()


def _closed(value, fields):
    _require(type(value) is dict and set(value) == fields)


def _match(value, pattern):
    _require(type(value) is str and re.fullmatch(pattern, value) is not None)


def _id(value):
    _require(type(value) is int and value > 0)


def _text(value, maximum=128):
    _require(type(value) is str and 0 < len(value) <= maximum and not any(ord(c) < 32 for c in value))


def _utc(value):
    _match(value, r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require(parsed.utcoffset() == timedelta(0))
    return parsed


def _bounded(value):
    """Reject custom Python objects/cycles before serialization or copying."""
    nodes, text_bytes, ancestors = 0, 0, set()

    def visit(item, depth):
        nonlocal nodes, text_bytes
        nodes += 1
        _require(nodes <= 5_000 and depth <= 20)
        if type(item) in {dict, list}:
            _require(id(item) not in ancestors)
            ancestors.add(id(item))
            if type(item) is dict:
                _require(all(type(key) is str and len(key) <= 128 for key in item))
                children = item.values()
            else:
                children = item
            for child in children:
                visit(child, depth + 1)
            ancestors.remove(id(item))
        else:
            _require(item is None or type(item) in {str, int, bool}
                     or type(item) is float and math.isfinite(item))
            if type(item) is str:
                _require(len(item) <= MAX_CAPSULE_BYTES)
                text_bytes += len(item.encode("utf-8"))
                _require(text_bytes <= MAX_CAPSULE_BYTES)
            elif type(item) is int:
                _require(item.bit_length() <= 63)
    visit(value, 0)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _digest(value):
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _codes(value):
    _require(type(value) is list and 0 < len(value) <= 32)
    for code in value:
        _match(code, r"[A-Z][A-Z0-9_]{0,63}")


def _validate(value):
    _bounded(value)
    _closed(value, CAPSULE_KEYS)
    _require(value["schema_version"] == VERSION)
    binding, preissued, origin, authority = (value[name] for name in ("binding", "preissued", "origin", "authority"))
    _closed(binding, BINDING_KEYS)
    for name in ("proof_run_id", "run_id"):
        _match(binding[name], r"[0-9a-f]{32}")
    _require(binding["variant"] in {"exact", "tampered"} and binding["condition"] in {"C0", "C1"})
    matrix = tuple((variant, condition) for variant in ("exact", "tampered") for condition in ("C0", "C1"))
    generation = 1 + 2 * matrix.index((binding["variant"], binding["condition"]))
    _require(binding["database"] == "tcc_state_" + binding["proof_run_id"][:12] + f"_{generation:03d}")
    _require(binding["run_id"] == hashlib.sha256((binding["proof_run_id"] + ":" + binding["variant"]
             + ":" + binding["condition"]).encode("ascii")).hexdigest()[:32])
    _match(binding["git_base"], r"[0-9a-f]{40}")
    for name in ("source_bundle_sha256", "configuration_sha256", "fixture_manifest_sha256"):
        _match(binding[name], r"[0-9a-f]{64}")
    for name in ("company_id", "principal_id"):
        _id(binding[name])
    _closed(preissued, PREISSUED_KEYS)
    _require(preissued["schema_version"] == "gateway-post-preissued/v1"
             and preissued["original_create_authenticated"] is True)
    for name in ("proof_run_id", "run_id", "database", "variant", "condition", "git_base",
                 "source_bundle_sha256", "principal_id"):
        _require(type(preissued[name]) is type(binding[name]) and preissued[name] == binding[name])
    _require(type(preissued["preissued_at_ns"]) is int and preissued["preissued_at_ns"] >= 0)
    preissued_time = _utc(preissued["preissued_at_utc"])
    clock = preissued["clock_domain"]
    _closed(clock, CLOCK_KEYS)
    _require(clock["schema_version"] == "linux-clock-domain/v1"
             and clock["implementation"] == "clock_gettime(CLOCK_MONOTONIC)")
    for name in ("boot_sha256", "time_namespace_sha256", "offsets_sha256", "domain_sha256"):
        _match(clock[name], r"[0-9a-f]{64}")
    _match(clock["host_id"], r"kernel-[0-9a-f]{24}")
    _match(clock["clock_id"], r"monotonic-[0-9a-f]{40}")
    # This stdlib-only contract retains physical identity independently; it
    # proves value equivalence only under the explicitly bound local runtime.
    from tcc_gateway.linux_clock_scope import parse_clock_scope, require_clock_in_scope
    scope = parse_clock_scope(preissued["clock_scope"])
    _require(require_clock_in_scope(clock, scope) == scope)
    for name in ("reference_command_sha256", "approval_sha256"):
        _match(preissued[name], r"sha256:[0-9a-f]{64}")
    _closed(origin, ORIGIN_KEYS)
    for name in ("create_receipt_id", "create_event_id", "target_move_id"):
        _id(origin[name])
    for name in ("create_event_sha256", "origin_sha256"):
        _match(origin[name], r"sha256:[0-9a-f]{64}")
    _closed(authority, AUTHORITY_KEYS)
    _id(authority["company_id"])
    _id(authority["executor_user_id"])
    _require(authority["company_id"] == binding["company_id"]
             and authority["executor_user_id"] == binding["principal_id"])
    for name in AUTHORITY_KEYS - {"company_id", "executor_user_id"}:
        _text(authority[name])
    _require(_utc(authority["issued_at"]) <= preissued_time < _utc(authority["expires_at"]))
    _match(value["key_material"], r"[0-9a-f]{64}")
    command = value["reference_command"]
    _closed(command, {"schema_version", "action", "policy_decision", "idempotency_key", "approval"})
    _require(command["schema_version"] == "capability-command/v1")
    _match(command["idempotency_key"], r"sha256:[0-9a-f]{64}")
    action = command["action"]
    _closed(action, ACTION_KEYS)
    _id(action["target_move_id"])
    _require(action["action"] == "POST_VENDOR_BILL" and action["executor_mode"] == "POST_APPROVED"
             and action["target_move_id"] == origin["target_move_id"]
             and action["scenario_id"] == authority["scenario_id"]
             and type(preissued["reference_action"]) is dict and preissued["reference_action"] == action)
    _match(action["scenario_id"], r"[A-Z0-9][A-Z0-9._-]{0,63}")
    _match(action["document_sha256"], r"[0-9a-f]{64}")
    for name in ACTION_KEYS - {"lines", "target_move_id"}:
        _text(action[name], 256)
    _require(type(action["lines"]) is list and 0 < len(action["lines"]) <= 100)
    for line in action["lines"]:
        _closed(line, {"item_code", "quantity", "unit_price"})
        for item in line.values():
            _text(item)
    policy, approval = command["policy_decision"], command["approval"]
    _closed(policy, POLICY_KEYS)
    _require(policy["schema_version"] == "policy-decision/v1" and policy["decision"] == "REVIEW"
             and policy["allowed_executor"] == "post_bill_executor" and policy["deny_class"] is None
             and policy["policy_version"] == action["policy_version"])
    _codes(policy["reason_codes"])
    _match(policy["input_sha256"], r"sha256:[0-9a-f]{64}")
    _require(policy["proposed_action_hash"] == _digest(action)
             and _utc(policy["evaluated_at"]) <= preissued_time < _utc(policy["expires_at"]))
    _closed(approval, APPROVAL_KEYS)
    _require(approval["decision"] == "APPROVE" and approval["canonical_action_hash"] == _digest(action)
             and all(approval[name] == authority[name] for name in AUTHORITY_KEYS - {"company_id", "executor_user_id"}))
    _match(approval["signature"], r"hmac-sha256/v1:[0-9a-f]{64}")
    _require(preissued["reference_command_sha256"] == _digest(command)
             and preissued["approval_sha256"] == _digest(approval))
    created = value["create_result"]
    _closed(created, {"schema_version", "status", "effect_applied", "reason_codes", "receipt", "audit_complete",
                      "audit_event", "deny_class"})
    _require(created["schema_version"] == "draft-kernel-result/v1" and created["status"] == "CREATED"
             and created["effect_applied"] is True and created["audit_complete"] is True and created["deny_class"] is None)
    _codes(created["reason_codes"])
    receipt, event = created["receipt"], created["audit_event"]
    _closed(receipt, {"receipt_id", "move_id", "idempotency_key", "action_hash"})
    _closed(event, {"event_id", "event_sha256", "original_event_id"})
    for number in (receipt["receipt_id"], receipt["move_id"], event["event_id"]):
        _id(number)
    for digest in (receipt["idempotency_key"], receipt["action_hash"], event["event_sha256"]):
        _match(digest, r"sha256:[0-9a-f]{64}")
    _require(receipt["receipt_id"] == origin["create_receipt_id"] and receipt["move_id"] == origin["target_move_id"]
             and receipt["idempotency_key"] == command["idempotency_key"]
             and event["event_id"] == origin["create_event_id"] and event["event_sha256"] == origin["create_event_sha256"]
             and event["original_event_id"] is None)
    raw = _canonical(value)
    _require(0 < len(raw) <= MAX_CAPSULE_BYTES)
    return json.loads(raw)


def validate_capsule(value):
    """Return a detached closed capsule, without authenticating its producer."""
    try:
        return _validate(value)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        _fail()


def parse_capsule(raw):
    try:
        _require(type(raw) is bytes and 0 < len(raw) <= MAX_CAPSULE_BYTES)
        def pairs(items):
            result = {}
            for key, item in items:
                _require(key not in result)
                result[key] = item
            return result
        return validate_capsule(json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _value: _fail()))
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        _fail()


def _metadata(info, uid, *, directory=False):
    _require(not stat.S_ISLNK(info.st_mode)
             and not getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    if directory:
        mode = stat.S_IMODE(info.st_mode)
        _require(stat.S_ISDIR(info.st_mode)
                 and ((mode == 0o1777 and info.st_uid in {0, uid})
                      or mode in {0o700, 0o750} and info.st_uid == uid))
    else:
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == uid
                 and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1)


def _chain(root):
    found = []
    for part in [*reversed(root.parents), root]:
        info = part.lstat()
        _require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                 and not getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
        found.append((info.st_dev, info.st_ino))
    return found


def _path(run_id, root, expected_uid):
    _match(run_id, r"[0-9a-f]{32}")
    root = PRIVATE_ROOT if root is None else Path(root)
    _require(root.is_absolute() and ".." not in root.parts)
    chain = _chain(root)
    if expected_uid is None:
        getter = getattr(os, "getuid", None)
        _require(callable(getter))
        expected_uid = getter()
    _require(type(expected_uid) is int and expected_uid >= 0)
    _metadata(root.lstat(), expected_uid, directory=True)
    return root / ("tcc-gateway-post-" + run_id + ".json"), expected_uid, chain


def _file_identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _directory_unchanged(path, uid, chain):
    _require(_chain(path.parent) == chain)
    _metadata(path.parent.lstat(), uid, directory=True)


def write_capsule(run_id, value, *, root=None, expected_uid=None):
    """Exclusive 0600 write; failures never overwrite, expose or unlink a file."""
    try:
        body = validate_capsule(value)
        _require(body["binding"]["run_id"] == run_id)
        path, uid, chain = _path(run_id, root, expected_uid)
        raw = _canonical(body)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            _metadata(os.fstat(stream.fileno()), uid)
            _require(stream.write(raw) == len(raw))
            stream.flush()
            os.fsync(stream.fileno())
            info = os.fstat(stream.fileno())
            _metadata(info, uid)
            _require(info.st_size == len(raw))
            final = path.lstat()
            _metadata(final, uid)
            # Writes legitimately update timestamps; Windows may expose final
            # creation/change metadata only after closing the writer handle.
            # Keep object/type/owner/link/size checks here, then verify all
            # bytes through the stable bounded reader after closing it.
            _require((info.st_dev, info.st_ino, info.st_size) == (final.st_dev, final.st_ino, final.st_size))
        _directory_unchanged(path, uid, chain)
        final = path.lstat()
        _metadata(final, uid)
        _require((info.st_dev, info.st_ino, info.st_size) == (final.st_dev, final.st_ino, final.st_size))
        _require(_canonical(read_capsule(run_id, root=path.parent, expected_uid=uid)) == raw)
        _directory_unchanged(path, uid, chain)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        _fail()


def read_capsule(run_id, *, root=None, expected_uid=None):
    """Bounded complete read with exact ownership and stable inode/metadata."""
    try:
        path, uid, chain = _path(run_id, root, expected_uid)
        initial = path.lstat()
        _metadata(initial, uid)
        _require(0 < initial.st_size <= MAX_CAPSULE_BYTES)
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            _metadata(info, uid)
            _require(_file_identity(initial) == _file_identity(info))
            raw = stream.read(MAX_CAPSULE_BYTES + 1)
            after = os.fstat(stream.fileno())
            _metadata(after, uid)
            final = path.lstat()
            _metadata(final, uid)
            _require(len(raw) == info.st_size == after.st_size
                     and _file_identity(info) == _file_identity(after) == _file_identity(final))
        _directory_unchanged(path, uid, chain)
        body = parse_capsule(raw)
        _require(body["binding"]["run_id"] == run_id)
        return body
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        _fail()
