"""DEC-079 private capsule checks with synthetic, temporary fixtures only.

The parser checks custody/bindings, not a grant's cryptographic authenticity.
Windows POSIX-mode/ctime projection is an explicit filesystem double: its
fstat/lstat creation-time views are not the Linux change-time contract. Native
Linux proof must exercise actual metadata. No Docker or provider is called.
"""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from test_pilot_approval_native import fixture as approval_fixture
from tcc_gateway.linux_clock_domain import _from_fingerprints, _ZERO_OFFSETS_SHA256
from tcc_gateway.linux_clock_scope import build_clock_scope


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("_gateway_post_custody_test", ROOT / "odoo/probes/gateway_post_custody.py")
custody = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(custody)
ERROR = "^GATEWAY_POST_CUSTODY_INVALID$"
MATRIX = tuple((variant, condition) for variant in ("exact", "tampered") for condition in ("C0", "C1"))


def fixture(variant="exact", condition="C0"):
    command, options = approval_fixture()
    proof = "a" * 32
    run_id = hashlib.sha256((proof + ":" + variant + ":" + condition).encode("ascii")).hexdigest()[:32]
    generation = 1 + 2 * MATRIX.index((variant, condition))
    binding = {"proof_run_id": proof, "run_id": run_id,
        "database": "tcc_state_" + proof[:12] + f"_{generation:03d}", "variant": variant, "condition": condition,
        "git_base": "b" * 40, "source_bundle_sha256": "c" * 64, "configuration_sha256": "d" * 64,
        "fixture_manifest_sha256": "e" * 64, "company_id": 11, "principal_id": 22}
    origin = {"create_receipt_id": 91, "create_event_id": 99, "target_move_id": 123,
        "create_event_sha256": "sha256:" + "8" * 64, "origin_sha256": "sha256:" + "9" * 64}
    preissued = {"schema_version": "gateway-post-preissued/v1",
        **{key: binding[key] for key in ("proof_run_id", "run_id", "database", "variant", "condition", "git_base",
                                        "source_bundle_sha256", "principal_id")},
        "clock_domain": _from_fingerprints("1" * 64, "2" * 64, _ZERO_OFFSETS_SHA256),
        "preissued_at_ns": 1000, "preissued_at_utc": "2026-10-01T12:05:00.000000Z",
        "reference_action": deepcopy(command["action"]), "reference_command_sha256": custody._digest(command),
        "approval_sha256": custody._digest(command["approval"]), "original_create_authenticated": True}
    preissued["clock_scope"] = build_clock_scope(preissued["clock_domain"], {
        "schema_version": "local-linux-runtime/v1", "daemon_sha256": "1" * 64, "kernel_sha256": "2" * 64,
        "runtime": "runc", "endpoint_kind": "local-npipe", "os_type": "linux", "platform": "linux/amd64"})
    return {"schema_version": custody.VERSION, "binding": binding, "preissued": preissued, "origin": origin,
        "create_result": {"schema_version": "draft-kernel-result/v1", "status": "CREATED", "effect_applied": True,
            "reason_codes": ["DRAFT_CONSISTENT"], "audit_complete": True, "deny_class": None,
            "receipt": {"receipt_id": 91, "move_id": 123, "idempotency_key": command["idempotency_key"],
                        "action_hash": "sha256:" + "f" * 64},
            "audit_event": {"event_id": 99, "event_sha256": origin["create_event_sha256"], "original_event_id": None}},
        "reference_command": command, "authority": asdict(options["authority"]), "key_material": options["key"].material.hex()}


def rehash(value):
    command = value["reference_command"]
    value["preissued"]["reference_command_sha256"] = custody._digest(command)
    value["preissued"]["approval_sha256"] = custody._digest(command["approval"])
    return value


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    uid = root.stat().st_uid
    if os.name == "nt":
        original = custody._metadata
        original_identity = custody._file_identity

        def projected(info, expected_uid, *, directory=False):
            mode = 0o700 if directory else 0o600
            fake = SimpleNamespace(st_mode=stat.S_IFMT(info.st_mode) | mode,
                st_uid=info.st_uid, st_nlink=info.st_nlink,
                st_file_attributes=getattr(info, "st_file_attributes", 0))
            return original(fake, expected_uid, directory=directory)

        monkeypatch.setattr(custody, "_metadata", projected)
        # Inode, size, mtime and actual file I/O stay real. Production keeps its
        # full Linux ctime guard, checked independently without this fixture.
        monkeypatch.setattr(custody, "_file_identity", lambda info: (*original_identity(info)[:-1], 0))
    return root, uid


@pytest.mark.parametrize("variant,condition", MATRIX)
def test_four_closed_capsules_roundtrip_with_detached_original_reference(variant, condition):
    value = fixture(variant, condition)
    checked = custody.validate_capsule(value)
    assert checked is not value
    assert custody._digest(checked) == custody._digest(value)
    parsed = custody.parse_capsule(custody._canonical(checked))
    assert custody._digest(parsed) == custody._digest(value)
    checked["reference_command"]["action"]["amount"] = "999.00"
    assert custody._digest(checked) != custody._digest(value)


@pytest.mark.parametrize("field", sorted(custody.CAPSULE_KEYS))
def test_every_top_level_field_is_required(field):
    value = fixture()
    del value[field]
    with pytest.raises(ValueError, match=ERROR):
        custody.validate_capsule(value)


@pytest.mark.parametrize("parent,keys", [
    ("binding", custody.BINDING_KEYS), ("preissued", custody.PREISSUED_KEYS),
    ("origin", custody.ORIGIN_KEYS), ("authority", custody.AUTHORITY_KEYS),
])
def test_nested_contracts_reject_unknown_fields(parent, keys):
    value = fixture()
    assert set(value[parent]) == keys
    value[parent]["unexpected"] = "SYNTHETIC-PRIVATE-MARKER"
    with pytest.raises(ValueError, match=ERROR):
        custody.validate_capsule(value)


@pytest.mark.parametrize("location,key,new", [
    ((), "schema_version", "pilot-a3a-post-capsule/v1"),
    (("binding",), "run_id", "0" * 32), (("binding",), "proof_run_id", "0" * 32),
    (("binding",), "database", "tcc_state_aaaaaaaaaaaa_003"),
    (("binding",), "database", "tcc_state_bbbbbbbbbbbb_001"),
    (("binding",), "variant", "other"), (("binding",), "condition", "C2"),
    (("binding",), "company_id", True), (("binding",), "principal_id", 0),
    (("binding",), "git_base", "0" * 39), (("binding",), "source_bundle_sha256", "not-a-hash"),
    (("preissued",), "run_id", "0" * 32), (("preissued",), "principal_id", 23),
    (("preissued",), "original_create_authenticated", False),
    (("preissued",), "preissued_at_ns", True), (("preissued",), "preissued_at_ns", -1),
    (("preissued",), "preissued_at_utc", "2026-10-01T12:11:00Z"),
    (("preissued",), "reference_command_sha256", "sha256:" + "0" * 64),
    (("preissued",), "approval_sha256", "sha256:" + "0" * 64),
    (("preissued", "clock_domain"), "implementation", "QueryPerformanceCounter()"),
    (("preissued", "clock_scope"), "clock_id", "monotonic-foreign"),
    (("preissued", "clock_scope"), "boot_sha256", "0" * 64),
    (("origin",), "target_move_id", 124), (("origin",), "create_receipt_id", 92),
    (("origin",), "create_event_id", 100), (("origin",), "create_event_sha256", "sha256:" + "0" * 64),
    (("authority",), "company_id", 12), (("authority",), "executor_user_id", 23),
    (("authority",), "nonce", "OTHER-SYNTHETIC-NONCE"),
    (("create_result",), "status", "REPLAY"), (("create_result",), "effect_applied", False),
    (("create_result",), "audit_complete", False),
    (("create_result", "receipt"), "idempotency_key", "sha256:" + "0" * 64),
    (("create_result", "audit_event"), "original_event_id", 88),
])
def test_foreign_bindings_timing_and_origin_cannot_be_transplanted(location, key, new):
    value = fixture()
    target = value
    for part in location:
        target = target[part]
    target[key] = new
    with pytest.raises(ValueError, match=ERROR):
        custody.validate_capsule(value)


@pytest.mark.parametrize("location,key,new", [
    (("reference_command", "policy_decision"), "decision", "ALLOW"),
    (("reference_command", "policy_decision"), "proposed_action_hash", "sha256:" + "0" * 64),
    (("reference_command", "policy_decision"), "expires_at", "2026-10-01T12:00:00Z"),
    (("reference_command", "approval"), "canonical_action_hash", "sha256:" + "0" * 64),
    (("reference_command", "approval"), "nonce", "OTHER-SYNTHETIC-NONCE"),
    (("reference_command", "approval"), "signature", "bad-signature-format"),
])
def test_repaired_hashes_do_not_repair_a_changed_grant_reference(location, key, new):
    value = fixture()
    target = value
    for part in location:
        target = target[part]
    target[key] = new
    with pytest.raises(ValueError, match=ERROR):
        custody.validate_capsule(rehash(value))


def test_custody_parser_is_not_a_cryptographic_verifier():
    value = fixture()
    signature = value["reference_command"]["approval"]["signature"]
    value["reference_command"]["approval"]["signature"] = signature[:-1] + ("1" if signature[-1] == "0" else "0")
    repaired = rehash(value)
    # A producer that rehashes a bad MAC still needs the independent native
    # verifier. A closed parser does not claim it authenticated the signature.
    assert custody._digest(custody.validate_capsule(repaired)) == custody._digest(repaired)


@pytest.mark.parametrize("kind", ["cycle", "custom", "large-int", "huge-string", "deep", "nonfinite"])
def test_python_values_are_bounded_before_serialization(kind):
    value = fixture()
    if kind == "cycle":
        value["loop"] = value
    elif kind == "custom":
        value["key_material"] = object()
    elif kind == "large-int":
        value["binding"]["company_id"] = 2 ** 80
    elif kind == "huge-string":
        value["key_material"] = "x" * (custody.MAX_CAPSULE_BYTES + 1)
    elif kind == "deep":
        child = value
        for _ in range(25):
            child["nested"] = {}
            child = child["nested"]
    else:
        value["key_material"] = float("nan")
    with pytest.raises(ValueError, match=ERROR):
        custody.validate_capsule(value)


@pytest.mark.parametrize("raw", [b"", b"[]", b"{}", b"\xff", b'{"x":1,"x":2}', b'{"x":Infinity}',
    b" " * (32 * 1024 + 1), b"[" * 25 + b"0" + b"]" * 25],
    ids=["empty", "list", "object", "encoding", "duplicate", "nonfinite", "oversize", "deep"])
def test_raw_parser_rejects_invalid_or_ambiguous_json(raw):
    with pytest.raises(ValueError, match=ERROR):
        custody.parse_capsule(raw)


@pytest.mark.parametrize("mode,owner,links,allowed", [
    (stat.S_IFREG | 0o600, 10001, 1, True), (stat.S_IFREG | 0o640, 10001, 1, False),
    (stat.S_IFREG | 0o600, 10002, 1, False), (stat.S_IFREG | 0o600, 10001, 2, False),
    (stat.S_IFDIR | 0o600, 10001, 1, False), (stat.S_IFLNK | 0o600, 10001, 1, False),
])
def test_posix_file_owner_mode_type_and_single_link(mode, owner, links, allowed):
    metadata = SimpleNamespace(st_mode=mode, st_uid=owner, st_nlink=links)
    if allowed:
        custody._metadata(metadata, 10001)
    else:
        with pytest.raises(ValueError, match=ERROR):
            custody._metadata(metadata, 10001)


def test_production_file_identity_includes_both_linux_timestamps():
    original = SimpleNamespace(st_dev=1, st_ino=2, st_size=100, st_mtime_ns=200, st_ctime_ns=300)
    baseline = custody._file_identity(original)
    assert baseline == (1, 2, 100, 200, 300)
    for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"):
        changed = SimpleNamespace(**vars(original))
        setattr(changed, field, getattr(changed, field) + 1)
        assert custody._file_identity(changed) != baseline


@pytest.mark.parametrize("mode,owner,allowed", [(0o1777, 0, True), (0o1777, 10001, True),
    (0o1777, 10002, False), (0o777, 0, False), (0o700, 10001, True),
    (0o750, 10001, True), (0o750, 0, False), (0o755, 10001, False)])
def test_private_root_or_sticky_root_owned_tmp_are_the_only_directory_profiles(mode, owner, allowed):
    metadata = SimpleNamespace(st_mode=stat.S_IFDIR | mode, st_uid=owner)
    if allowed:
        custody._metadata(metadata, 10001, directory=True)
    else:
        with pytest.raises(ValueError, match=ERROR):
            custody._metadata(metadata, 10001, directory=True)


def test_real_filesystem_exclusive_roundtrip_does_not_overwrite(store):
    root, uid = store
    value = fixture()
    run_id = value["binding"]["run_id"]
    custody.write_capsule(run_id, value, root=root, expected_uid=uid)
    result = custody.read_capsule(run_id, root=root, expected_uid=uid)
    assert custody._digest(result) == custody._digest(value)
    path = root / ("tcc-gateway-post-" + run_id + ".json")
    before = hashlib.sha256(path.read_bytes()).digest()
    with pytest.raises(ValueError, match=ERROR):
        custody.write_capsule(run_id, value, root=root, expected_uid=uid)
    assert hashlib.sha256(path.read_bytes()).digest() == before
    assert len(list(root.iterdir())) == 1


@pytest.mark.parametrize("run_id", ["wrong", "../capsule", "A" * 32, True, "b" * 32])
def test_invalid_or_different_run_does_not_create_a_capsule(store, run_id):
    root, uid = store
    with pytest.raises(ValueError, match=ERROR):
        custody.write_capsule(run_id, fixture(), root=root, expected_uid=uid)
    assert list(root.iterdir()) == []


def test_even_identical_physical_ids_do_not_admit_another_run(store):
    root, uid = store
    value = fixture()
    other = fixture("tampered", "C1")["binding"]["run_id"]
    path = root / ("tcc-gateway-post-" + other + ".json")
    path.write_bytes(custody._canonical(value))
    path.chmod(0o600)
    with pytest.raises(ValueError, match=ERROR):
        custody.read_capsule(other, root=root, expected_uid=uid)


def test_real_hardlink_is_rejected(store):
    root, uid = store
    value = fixture()
    run_id = value["binding"]["run_id"]
    custody.write_capsule(run_id, value, root=root, expected_uid=uid)
    os.link(root / ("tcc-gateway-post-" + run_id + ".json"), root / "other-link")
    with pytest.raises(ValueError, match=ERROR):
        custody.read_capsule(run_id, root=root, expected_uid=uid)


def test_oversized_file_is_not_returned_or_modified(store):
    root, uid = store
    run_id = fixture()["binding"]["run_id"]
    path = root / ("tcc-gateway-post-" + run_id + ".json")
    raw = b"x" * (custody.MAX_CAPSULE_BYTES + 1)
    path.write_bytes(raw)
    path.chmod(0o600)
    with pytest.raises(ValueError, match=ERROR):
        custody.read_capsule(run_id, root=root, expected_uid=uid)
    assert path.stat().st_size == len(raw)


def test_reader_rejects_metadata_changes_during_a_bounded_read(store, monkeypatch):
    root, uid = store
    value = fixture()
    run_id = value["binding"]["run_id"]
    custody.write_capsule(run_id, value, root=root, expected_uid=uid)
    original, calls = custody.os.fstat, []

    def changed(descriptor):
        info = original(descriptor)
        calls.append(True)
        if len(calls) == 2:
            return SimpleNamespace(st_mode=info.st_mode, st_uid=info.st_uid, st_nlink=info.st_nlink,
                st_dev=info.st_dev, st_ino=info.st_ino, st_size=info.st_size,
                st_mtime_ns=info.st_mtime_ns + 1, st_ctime_ns=info.st_ctime_ns,
                st_file_attributes=getattr(info, "st_file_attributes", 0))
        return info

    monkeypatch.setattr(custody.os, "fstat", changed)
    with pytest.raises(ValueError, match=ERROR):
        custody.read_capsule(run_id, root=root, expected_uid=uid)


@pytest.mark.parametrize("kind", ["symlink", "reparse"])
def test_root_link_or_reparse_is_rejected_before_open(store, monkeypatch, kind):
    root, uid = store
    original = Path.lstat

    def fake(path, *args, **kwargs):
        if path == root:
            return SimpleNamespace(st_mode=stat.S_IFLNK | 0o700 if kind == "symlink" else stat.S_IFDIR | 0o700,
                st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", fake)
    with pytest.raises(ValueError, match=ERROR):
        custody.read_capsule(fixture()["binding"]["run_id"], root=root, expected_uid=uid)


def test_directory_swap_detected_after_actual_write(store, monkeypatch):
    root, uid = store
    value = fixture()
    original = custody._chain
    calls = []

    def swapped(path):
        result = original(path)
        calls.append(path)
        return result if len(calls) == 1 else [(0, 0)]

    monkeypatch.setattr(custody, "_chain", swapped)
    with pytest.raises(ValueError, match=ERROR):
        custody.write_capsule(value["binding"]["run_id"], value, root=root, expected_uid=uid)
    assert len(list(root.iterdir())) == 1  # Never unlink evidence after a failure.


def test_capsule_has_no_native_or_schema_dependency_imports():
    import ast
    tree = ast.parse((ROOT / "odoo/probes/gateway_post_custody.py").read_text(encoding="utf-8"))
    dependencies = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    dependencies.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
    assert not any(name and (name.startswith("odoo") or name.startswith("jsonschema")
        or name.startswith("tcc_gateway") and name != "tcc_gateway.linux_clock_scope") for name in dependencies)


def test_physical_domain_and_shared_scope_are_both_required_and_cannot_be_relabelled():
    value = fixture()
    del value["preissued"]["clock_scope"]
    with pytest.raises(ValueError, match=ERROR):
        custody.validate_capsule(value)
    value = fixture()
    value["preissued"]["clock_domain"] = value["preissued"]["clock_scope"]
    with pytest.raises(ValueError, match=ERROR):
        custody.validate_capsule(value)


def test_exact_zero_scope_does_not_erase_another_valid_physical_namespace():
    value = fixture()
    original = deepcopy(value["preissued"]["clock_domain"])
    different = _from_fingerprints(original["boot_sha256"], "3" * 64, original["offsets_sha256"])
    value["preissued"]["clock_domain"] = different
    checked = custody.validate_capsule(value)
    assert checked["preissued"]["clock_domain"] == different != original
    assert checked["preissued"]["clock_scope"] == fixture()["preissued"]["clock_scope"]
