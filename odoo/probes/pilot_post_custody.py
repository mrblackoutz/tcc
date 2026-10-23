# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-075 bounded Odoo-only tmpfs capsule; never a persistent artifact.

No Odoo imports, implicit issuance, key selection from a token, or logging.
Explicit root/uid arguments exist for isolated filesystem tests; native callers
always use the fixed mount and current process identity.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import stat


PRIVATE_ROOT = Path("/run/pilot-approval-private")
MAX_CAPSULE_BYTES = 32 * 1024
VERSION = "pilot-a3a-post-capsule/v1"
CAPSULE_KEYS = {"schema_version", "clone_binding", "git_base", "source_bundle_sha256", "cohort_sha256",
    "codebook_sha256", "scenario_id", "document_sha256", "company_id", "executor_user_id", "registration_id",
    "registration_sha256", "origin", "create_result", "command", "authority", "key_material",
    "before_projection_sha256", "identity_sha256"}
CLONE_KEYS = {"schema_version", "source_database", "target_database", "original_manifest_sha256",
    "rewritten_manifest_sha256", "snapshot_manifest_sha256", "seed_sha256", "catalog_sha256",
    "origin_input_sha256", "fixture_ref"}
ORIGIN_KEYS = {"create_receipt_id", "create_event_id", "create_event_sha256", "target_move_id", "origin_sha256"}
AUTHORITY_KEYS = {"company_id", "executor_user_id", "fixture_id", "scenario_id", "approver_ref", "nonce",
                  "issued_at", "expires_at", "key_id"}


def _require(value):
    if not value:
        raise ValueError("PILOT_POST_CUSTODY_INVALID")


def _closed(value, keys):
    _require(type(value) is dict and set(value) == keys)


def _match(value, expression):
    _require(type(value) is str and re.fullmatch(expression, value) is not None)


def _id(value):
    _require(type(value) is int and value > 0)


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise ValueError("PILOT_POST_CUSTODY_INVALID") from None


def validate_capsule(value):
    _closed(value, CAPSULE_KEYS)
    _require(value["schema_version"] == VERSION)
    _match(value["git_base"], r"[0-9a-f]{40}")
    for name in ("source_bundle_sha256", "cohort_sha256", "codebook_sha256", "document_sha256", "identity_sha256"):
        _match(value[name], r"[0-9a-f]{64}")
    for name in ("registration_sha256", "before_projection_sha256"):
        _match(value[name], r"sha256:[0-9a-f]{64}")
    _match(value["scenario_id"], r"[A-Z0-9][A-Z0-9._-]{0,63}")
    for name in ("company_id", "executor_user_id", "registration_id"):
        _id(value[name])
    clone, origin, authority = (value[name] for name in ("clone_binding", "origin", "authority"))
    _closed(clone, CLONE_KEYS)
    _require(clone["schema_version"] == "pilot-reset-clone-binding/v1")
    for name in ("source_database", "target_database"):
        _match(clone[name], r"tcc_runner_[0-9a-f]{12}")
    _require(clone["source_database"] != clone["target_database"])
    for name in CLONE_KEYS - {"schema_version", "source_database", "target_database", "fixture_ref"}:
        _match(clone[name], r"[0-9a-f]{64}")
    _match(clone["fixture_ref"], r"[A-Z0-9][A-Z0-9._ /-]{0,95}")
    _closed(origin, ORIGIN_KEYS)
    for name in ("create_receipt_id", "create_event_id", "target_move_id"):
        _id(origin[name])
    for name in ("create_event_sha256", "origin_sha256"):
        _match(origin[name], r"sha256:[0-9a-f]{64}")
    _closed(authority, AUTHORITY_KEYS)
    _require(authority["company_id"] == value["company_id"]
             and authority["executor_user_id"] == value["executor_user_id"]
             and authority["scenario_id"] == value["scenario_id"])
    _id(authority["company_id"])
    _id(authority["executor_user_id"])
    for name in AUTHORITY_KEYS - {"company_id", "executor_user_id"}:
        _require(type(authority[name]) is str and 0 < len(authority[name]) <= 128)
    _match(value["key_material"], r"[0-9a-f]{64}")
    command = value["command"]
    _closed(command, {"schema_version", "action", "policy_decision", "idempotency_key", "approval"})
    _require(command["schema_version"] == "capability-command/v1")
    _match(command["idempotency_key"], r"sha256:[0-9a-f]{64}")
    _closed(command["action"], {"canonicalization_version", "action_schema_version", "policy_version", "action",
        "executor_mode", "scenario_id", "document_sha256", "vendor_ref", "purchase_order_ref", "document_ref",
        "invoice_date", "currency", "amount", "recipient_bank_ref", "lines", "target_move_id"})
    action = command["action"]
    _id(action["target_move_id"])
    _require(action["action"] == "POST_VENDOR_BILL" and action["executor_mode"] == "POST_APPROVED"
             and action["target_move_id"] == origin["target_move_id"]
             and action["scenario_id"] == value["scenario_id"] and action["document_sha256"] == value["document_sha256"])
    _require(type(action["lines"]) is list and 0 < len(action["lines"]) <= 100)
    for line in action["lines"]:
        _closed(line, {"item_code", "quantity", "unit_price"})
    _closed(command["policy_decision"], {"schema_version", "decision", "reason_codes", "proposed_action_hash",
        "input_sha256", "policy_version", "allowed_executor", "deny_class", "evaluated_at", "expires_at"})
    _require(command["policy_decision"]["decision"] == "REVIEW")
    _closed(command["approval"], {"fixture_id", "scenario_id", "approver_ref", "decision", "canonical_action_hash",
        "nonce", "issued_at", "expires_at", "key_id", "signature"})
    approval = command["approval"]
    _require(approval["decision"] == "APPROVE" and all(approval[name] == authority[name] for name in
             AUTHORITY_KEYS - {"company_id", "executor_user_id"}))
    created = value["create_result"]
    _closed(created, {"schema_version", "status", "effect_applied", "reason_codes", "receipt", "audit_complete",
                      "audit_event", "deny_class"})
    _require(created["schema_version"] == "draft-kernel-result/v1" and created["status"] == "CREATED"
             and created["effect_applied"] is True and created["audit_complete"] is True and created["deny_class"] is None)
    _closed(created["receipt"], {"receipt_id", "move_id", "idempotency_key", "action_hash"})
    _closed(created["audit_event"], {"event_id", "event_sha256", "original_event_id"})
    _id(created["receipt"]["receipt_id"])
    _id(created["receipt"]["move_id"])
    _id(created["audit_event"]["event_id"])
    _require(created["receipt"]["receipt_id"] == origin["create_receipt_id"]
             and created["receipt"]["move_id"] == origin["target_move_id"]
             and created["audit_event"]["event_id"] == origin["create_event_id"]
             and created["audit_event"]["event_sha256"] == origin["create_event_sha256"]
             and created["audit_event"]["original_event_id"] is None)
    _require(0 < len(_canonical(value)) <= MAX_CAPSULE_BYTES)
    return deepcopy(value)


def parse_capsule(raw):
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_CAPSULE_BYTES)
    def pairs(items):
        result = {}
        for name, item in items:
            _require(name not in result)
            result[name] = item
        return result
    def constant(_value):
        _require(False)
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        nodes = 0
        def bounded(item, depth):
            nonlocal nodes
            nodes += 1
            _require(depth <= 20 and nodes <= 5_000)
            if type(item) is dict:
                for child in item.values():
                    bounded(child, depth + 1)
            elif type(item) is list:
                for child in item:
                    bounded(child, depth + 1)
        bounded(value, 0)
        return validate_capsule(value)
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        raise ValueError("PILOT_POST_CUSTODY_INVALID") from None


def _metadata(info, uid, mode, *, directory=False):
    _require((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
             and info.st_uid == uid and stat.S_IMODE(info.st_mode) == mode
             and (directory or info.st_nlink == 1))


def _path(database, root, expected_uid):
    _match(database, r"tcc_runner_[0-9a-f]{12}")
    root = PRIVATE_ROOT if root is None else Path(root)
    _require(root.is_absolute())
    for part in [*reversed(root.parents), root]:
        info = part.lstat()
        _require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
                 and not getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    if expected_uid is None:
        getter = getattr(os, "getuid", None)
        _require(callable(getter))
        expected_uid = getter()
    _require(type(expected_uid) is int and expected_uid >= 0)
    _metadata(root.stat(), expected_uid, 0o750, directory=True)
    return root / (database + ".json"), expected_uid


def write_capsule(database, value, *, root=None, expected_uid=None):
    body = validate_capsule(value)
    _require(body["clone_binding"]["target_database"] == database)
    path, uid = _path(database, root, expected_uid)
    raw = _canonical(body)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        _metadata(os.fstat(stream.fileno()), uid, 0o600)
        stream.write(raw)
        stream.flush()
        info = os.fstat(stream.fileno())
        _metadata(info, uid, 0o600)
        _require(info.st_size == len(raw))


def read_capsule(database, *, root=None, expected_uid=None):
    path, uid = _path(database, root, expected_uid)
    initial = path.lstat()
    _require(not stat.S_ISLNK(initial.st_mode)
             and not getattr(initial, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    _metadata(initial, uid, 0o600)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        _metadata(info, uid, 0o600)
        _require((initial.st_dev, initial.st_ino) == (info.st_dev, info.st_ino))
        _require(0 < info.st_size <= MAX_CAPSULE_BYTES)
        raw = stream.read(MAX_CAPSULE_BYTES + 1)
        after = os.fstat(stream.fileno())
        _metadata(after, uid, 0o600)
        _require(len(raw) == info.st_size == after.st_size and
                 (info.st_dev, info.st_ino, info.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_mtime_ns))
    body = parse_capsule(raw)
    _require(body["clone_binding"]["target_database"] == database)
    return body
