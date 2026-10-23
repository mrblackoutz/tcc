"""DEC-075 real bounded capsule I/O with synthetic, temporary grants only."""

from copy import deepcopy
from dataclasses import asdict
import importlib.util
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from test_pilot_approval_native import fixture as approval_fixture


ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "odoo/probes/pilot_post_custody.py"
SPEC = importlib.util.spec_from_file_location("_pilot_post_custody_test", ENTRY)
custody = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(custody)
DATABASE = "tcc_runner_aaaaaaaaaaaa"


def capsule():
    command, options = approval_fixture()
    origin = {"create_receipt_id": 91, "create_event_id": 99, "target_move_id": 123,
        "create_event_sha256": "sha256:" + "8" * 64, "origin_sha256": "sha256:" + "9" * 64}
    return {"schema_version": custody.VERSION,
        "clone_binding": {"schema_version": "pilot-reset-clone-binding/v1",
            "source_database": "tcc_runner_bbbbbbbbbbbb", "target_database": DATABASE,
            "original_manifest_sha256": "1" * 64, "rewritten_manifest_sha256": "2" * 64,
            "snapshot_manifest_sha256": "3" * 64, "seed_sha256": "4" * 64,
            "catalog_sha256": "5" * 64, "origin_input_sha256": "6" * 64, "fixture_ref": "FIX-00"},
        "git_base": "a" * 40, "source_bundle_sha256": "b" * 64,
        "cohort_sha256": "c" * 64, "codebook_sha256": "d" * 64,
        "scenario_id": command["action"]["scenario_id"],
        "document_sha256": command["action"]["document_sha256"],
        "company_id": 11, "executor_user_id": 22, "registration_id": 7,
        "registration_sha256": "sha256:" + "e" * 64, "origin": origin,
        "create_result": {"schema_version": "draft-kernel-result/v1", "status": "CREATED",
            "effect_applied": True, "reason_codes": ["DRAFT_CONSISTENT"], "audit_complete": True,
            "deny_class": None, "receipt": {"receipt_id": 91, "move_id": 123,
                "idempotency_key": command["idempotency_key"], "action_hash": "sha256:" + "f" * 64},
            "audit_event": {"event_id": 99, "event_sha256": origin["create_event_sha256"], "original_event_id": None}},
        "command": command, "authority": asdict(options["authority"]),
        "key_material": options["key"].material.hex(),
        "before_projection_sha256": "sha256:" + "0" * 64, "identity_sha256": "1" * 64}


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Windows lacks POSIX mode bits; test that guard separately below.

    All JSON, exclusive open, bounded reads, paths and hard-link checks use the
    real filesystem. Linux-native integration checks the actual 0750/0600 bits.
    """
    root = tmp_path / "private"
    root.mkdir(mode=0o750)
    root.chmod(0o750)
    uid = root.stat().st_uid
    if os.name == "nt":
        original = custody._metadata
        def windows_metadata(info, expected_uid, mode, *, directory=False):
            projected = SimpleNamespace(st_mode=stat.S_IFMT(info.st_mode) | mode,
                                       st_uid=info.st_uid, st_nlink=info.st_nlink)
            return original(projected, expected_uid, mode, directory=directory)
        monkeypatch.setattr(custody, "_metadata", windows_metadata)
    return root, uid


def test_capsule_roundtrip_is_detached_and_retains_original_command_authority():
    value = capsule()
    checked = custody.validate_capsule(value)
    assert checked is not value
    assert custody._canonical(checked) == custody._canonical(value)
    checked["origin"]["target_move_id"] = 999
    assert value["origin"]["target_move_id"] == 123
    parsed = custody.parse_capsule(custody._canonical(value))
    assert custody._canonical(parsed) == custody._canonical(value)


@pytest.mark.parametrize("field", sorted(custody.CAPSULE_KEYS))
def test_all_capsule_top_fields_are_required(field):
    value = capsule()
    del value[field]
    with pytest.raises(ValueError, match="^PILOT_POST_CUSTODY_INVALID$"):
        custody.validate_capsule(value)


@pytest.mark.parametrize("kind", ["company", "executor", "scenario", "target", "document", "receipt",
    "create-event", "create-event-hash", "not-created", "no-effect", "no-audit", "authority-extra", "command-extra"])
def test_capsule_cannot_swap_origin_authority_or_command_bindings(kind):
    value = capsule()
    if kind in {"company", "executor"}:
        value[kind + ("_id" if kind == "company" else "_user_id")] += 1
    elif kind == "scenario":
        value["scenario_id"] = "SCN-OTHER"
    elif kind == "target":
        value["command"]["action"]["target_move_id"] += 1
    elif kind == "document":
        value["document_sha256"] = "0" * 64
    elif kind == "receipt":
        value["create_result"]["receipt"]["receipt_id"] += 1
    elif kind == "create-event":
        value["create_result"]["audit_event"]["event_id"] += 1
    elif kind == "create-event-hash":
        value["create_result"]["audit_event"]["event_sha256"] = "sha256:" + "0" * 64
    elif kind == "not-created":
        value["create_result"]["status"] = "REPLAY"
    elif kind == "no-effect":
        value["create_result"]["effect_applied"] = False
    elif kind == "no-audit":
        value["create_result"]["audit_complete"] = False
    else:
        value["authority" if kind == "authority-extra" else "command"]["extra"] = "PRIVATE-MARKER"
    with pytest.raises(ValueError) as caught:
        custody.validate_capsule(value)
    assert "PRIVATE-MARKER" not in str(caught.value)


@pytest.mark.parametrize("raw", [b"", b"{}", b"[]", b"\xff", b'{"x":1,"x":2}', b'{"x":NaN}',
    b"[" * 30 + b"0" + b"]" * 30, b" " * (32 * 1024 + 1)],
    ids=["empty", "object", "list", "encoding", "duplicate", "nonfinite", "deep", "oversize"])
def test_raw_parser_rejects_bad_json_limits_and_repeated_keys(raw):
    with pytest.raises(ValueError, match="^PILOT_POST_CUSTODY_INVALID$"):
        custody.parse_capsule(raw)


@pytest.mark.parametrize("kind", ["owner", "mode", "hardlink", "directory-instead-of-file", "file-instead-of-directory"])
def test_metadata_security_gate_uses_exact_owner_mode_type_and_link_count(kind):
    info = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=10001, st_nlink=1)
    directory = kind == "file-instead-of-directory"
    if kind == "owner":
        info.st_uid = 10002
    elif kind == "mode":
        info.st_mode = stat.S_IFREG | 0o640
    elif kind == "hardlink":
        info.st_nlink = 2
    elif kind == "directory-instead-of-file":
        info.st_mode = stat.S_IFDIR | 0o600
    with pytest.raises(ValueError):
        custody._metadata(info, 10001, 0o600, directory=directory)


def test_real_file_roundtrip_and_exclusive_creation(isolated_store):
    root, uid = isolated_store
    value = capsule()
    custody.write_capsule(DATABASE, value, root=root, expected_uid=uid)
    read = custody.read_capsule(DATABASE, root=root, expected_uid=uid)
    assert custody._canonical(read) == custody._canonical(value)
    with pytest.raises(FileExistsError):
        custody.write_capsule(DATABASE, value, root=root, expected_uid=uid)
    assert len(list(root.iterdir())) == 1


def test_same_restored_ids_do_not_allow_another_clone_capsule(isolated_store):
    root, uid = isolated_store
    value = capsule()
    other_database = "tcc_runner_cccccccccccc"
    with pytest.raises(ValueError):
        custody.write_capsule(other_database, value, root=root, expected_uid=uid)
    (root / (other_database + ".json")).write_bytes(custody._canonical(value))
    with pytest.raises(ValueError):
        custody.read_capsule(other_database, root=root, expected_uid=uid)


@pytest.mark.parametrize("database", ["postgres", "../capsule", "tcc_runner_AAAAAAAAAAAA", "tcc_runner_aaaaaaaaaaaax"])
def test_unowned_or_traversal_database_names_rejected_before_file_creation(isolated_store, database):
    root, uid = isolated_store
    with pytest.raises(ValueError):
        custody.write_capsule(database, capsule(), root=root, expected_uid=uid)
    assert list(root.iterdir()) == []


def test_reader_rejects_a_real_hard_link(isolated_store):
    root, uid = isolated_store
    custody.write_capsule(DATABASE, capsule(), root=root, expected_uid=uid)
    os.link(root / (DATABASE + ".json"), root / "extra-link")
    with pytest.raises(ValueError):
        custody.read_capsule(DATABASE, root=root, expected_uid=uid)


def test_reader_rejects_an_oversized_real_file_without_returning_contents(isolated_store):
    root, uid = isolated_store
    path = root / (DATABASE + ".json")
    path.write_bytes(b" " * (custody.MAX_CAPSULE_BYTES + 1))
    path.chmod(0o600)
    with pytest.raises(ValueError, match="^PILOT_POST_CUSTODY_INVALID$"):
        custody.read_capsule(DATABASE, root=root, expected_uid=uid)


def test_root_symlink_metadata_is_rejected_before_a_capsule_is_opened(isolated_store, monkeypatch):
    root, uid = isolated_store
    original = Path.lstat
    def lstat(path, *args, **kwargs):
        if path == root:
            return SimpleNamespace(st_mode=stat.S_IFLNK | 0o750, st_file_attributes=0)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(ValueError):
        custody.read_capsule(DATABASE, root=root, expected_uid=uid)
