"""DEC-055 local synthetic archive tests, not a PostgreSQL restoration proof."""

from dataclasses import replace
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("snapshot_archive", ROOT / "scripts/snapshot_archive.py")
archive = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = archive
SPEC.loader.exec_module(archive)


def files(tmp_path):
    root = tmp_path / "store"
    (root / "ab").mkdir(parents=True)
    (root / "ab" / ("a" * 40)).write_bytes(b"SYNTHETIC SEM VALOR FISCAL")
    (root / "checklist" / "cd").mkdir(parents=True)
    (root / "checklist" / "cd" / ("c" * 40)).write_bytes(b"")
    (root / "orphan").write_bytes(b"SYNTHETIC ORPHAN")
    dump = tmp_path / "baseline.dump"
    # Header-only stand-in exercises integrity; pg_restore is the separate native gate.
    dump.write_bytes(b"PGDMP\x01\x10\x00synthetic dump, not a valid database")
    return root, dump, tmp_path / "filestore.tar", tmp_path / "snapshot.json"


def capture(tmp_path):
    root, dump, tar, manifest = files(tmp_path)
    descriptor = archive.capture_filestore(root, tar)
    declared = archive.create_manifest(dump, tar, manifest)
    return root, dump, tar, manifest, descriptor, declared


def raw_tar(path, members):
    with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as output:
        for name, kind, data in members:
            member = tarfile.TarInfo(name)
            member.type = kind
            if kind in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
                member.linkname = "../outside"
            member.size = len(data) if kind == tarfile.REGTYPE else 0
            output.addfile(member, io.BytesIO(data) if member.size else None)


def test_roundtrip_preserves_linked_empty_checklist_and_orphan_files(tmp_path):
    root, dump, tar, manifest, descriptor, declared = capture(tmp_path)
    assert descriptor["file_count"] == 3
    assert descriptor["entry_count"] == 6
    assert archive.verify_manifest(dump, tar, manifest) == declared
    target = tmp_path / "restored"
    assert archive.restore_filestore(tar, target, expected_sha256=descriptor["sha256"]) == descriptor
    assert {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()} == {
        str(path.relative_to(target)): path.read_bytes() for path in target.rglob("*") if path.is_file()}


def test_capture_is_deterministic_without_uid_mtime_or_absolute_path(tmp_path):
    root, _dump, tar, _manifest = files(tmp_path)
    first = archive.capture_filestore(root, tar)
    for path in root.rglob("*"):
        os.utime(path, (1_234_567_890, 1_234_567_890))
    second = archive.capture_filestore(root, tmp_path / "second.tar")
    assert first == second
    with tarfile.open(tar) as source:
        assert all(member.uid == member.gid == member.mtime == 0 for member in source)


@pytest.mark.parametrize("exists", [False, True])
def test_empty_or_absent_filestore_has_explicit_empty_inventory(tmp_path, exists):
    root = tmp_path / "store"
    if exists:
        root.mkdir()
    tar = tmp_path / "empty.tar"
    descriptor = archive.capture_filestore(root, tar)
    assert descriptor["inventory"] == [] and descriptor["entry_count"] == 0
    target = tmp_path / "fresh"
    archive.restore_filestore(tar, target, expected_sha256=descriptor["sha256"])
    assert target.is_dir() and list(target.iterdir()) == []


@pytest.mark.parametrize("name", ["../outside", "a/../../outside", "/absolute", "a\\outside", "C:outside",
                                  "a//b", "./file", "a/./b", "a/../b", "bad\nname"])
def test_bad_archive_paths_rejected_before_any_target_is_created(tmp_path, name):
    tar = tmp_path / "bad.tar"
    raw_tar(tar, [(name, tarfile.REGTYPE, b"NO")])
    target = tmp_path / "target"
    with pytest.raises(archive.SnapshotArchiveError):
        archive.restore_filestore(tar, target, expected_sha256=hashlib.sha256(tar.read_bytes()).hexdigest())
    assert not target.exists()


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE,
                                  tarfile.FIFOTYPE, tarfile.GNUTYPE_SPARSE])
def test_links_devices_fifo_and_sparse_are_rejected(tmp_path, kind):
    tar = tmp_path / "bad.tar"
    raw_tar(tar, [("entry", kind, b"")])
    with pytest.raises(archive.SnapshotArchiveError):
        archive.verify_archive(tar)


@pytest.mark.parametrize("names", [("a", "a"), ("a", "A"), ("a", "a/b"), ("a/b", "a")])
def test_duplicates_case_collisions_and_file_parent_rejected(tmp_path, names):
    tar = tmp_path / "bad.tar"
    raw_tar(tar, [(name, tarfile.REGTYPE, b"x") for name in names])
    with pytest.raises(archive.SnapshotArchiveError):
        archive.verify_archive(tar)


def test_pax_extended_header_is_rejected(tmp_path):
    tar = tmp_path / "pax.tar"
    with tarfile.open(tar, "w", format=tarfile.PAX_FORMAT) as output:
        member = tarfile.TarInfo("file")
        member.pax_headers = {"comment": "not trusted"}
        output.addfile(member)
    with pytest.raises(archive.SnapshotArchiveError):
        archive.verify_archive(tar)


def test_compressed_archives_are_not_accepted(tmp_path):
    tar = tmp_path / "gzip.tar"
    with tarfile.open(tar, "w:gz") as output:
        output.addfile(tarfile.TarInfo("file"))
    with pytest.raises(archive.SnapshotArchiveError):
        archive.verify_archive(tar)


@pytest.mark.parametrize("limit,value", [("max_entries", 1), ("max_file_bytes", 1),
                                        ("max_total_file_bytes", 1), ("max_archive_bytes", 1),
                                        ("max_path_chars", 1), ("max_path_depth", 1)])
def test_archive_limits_fail_closed(tmp_path, limit, value):
    _root, _dump, tar, _manifest, _descriptor, _declared = capture(tmp_path)
    with pytest.raises(archive.SnapshotArchiveError):
        archive.verify_archive(tar, limits=replace(archive.DEFAULT_LIMITS, **{limit: value}))


@pytest.mark.parametrize("value", [0, -1, True, 1.0, "1"])
def test_limit_types_strict(value):
    with pytest.raises(archive.SnapshotArchiveError):
        archive.Limits(max_entries=value)


@pytest.mark.parametrize("which", ["dump", "archive", "manifest"])
def test_missing_or_corrupted_artifact_rejects_snapshot(tmp_path, which):
    _root, dump, tar, manifest, _descriptor, _declared = capture(tmp_path)
    selected = {"dump": dump, "archive": tar, "manifest": manifest}[which]
    selected.write_bytes(selected.read_bytes() + b"corruption")
    with pytest.raises(archive.SnapshotArchiveError):
        archive.verify_manifest(dump, tar, manifest)
    selected.unlink()
    with pytest.raises((archive.SnapshotArchiveError, OSError)):
        archive.verify_manifest(dump, tar, manifest)


@pytest.mark.parametrize("value", [b"", b"PGDM", b"NOTPGDMP", b"\x1f\x8b"])
def test_dump_requires_custom_pg_magic(tmp_path, value):
    root, dump, tar, manifest = files(tmp_path)
    archive.capture_filestore(root, tar)
    dump.write_bytes(value)
    with pytest.raises(archive.SnapshotArchiveError):
        archive.create_manifest(dump, tar, manifest)
    assert not manifest.exists()


@pytest.mark.parametrize("mutation", ["bool_count", "unknown_key", "wrong_hash", "inventory", "duplicate_key"])
def test_manifest_is_closed_and_reconstructed_not_trusted(tmp_path, mutation):
    _root, dump, tar, manifest, _descriptor, declared = capture(tmp_path)
    if mutation == "duplicate_key":
        manifest.write_text('{"schema_version":"local-state-snapshot/v1",' + manifest.read_text()[1:], encoding="utf-8")
    else:
        if mutation == "bool_count":
            declared["filestore"]["entry_count"] = True
        elif mutation == "unknown_key":
            declared["new"] = "ignored?"
        elif mutation == "wrong_hash":
            declared["dump"]["sha256"] = "0" * 64
        else:
            declared["filestore"]["inventory"][0]["path"] = "invented"
        manifest.write_text(json.dumps(declared), encoding="utf-8")
    with pytest.raises(archive.SnapshotArchiveError):
        archive.verify_manifest(dump, tar, manifest)


def test_outputs_are_exclusive_and_restore_never_deletes_existing_files(tmp_path):
    root, dump, tar, manifest, descriptor, _declared = capture(tmp_path)
    with pytest.raises(archive.SnapshotArchiveError):
        archive.capture_filestore(root, tar)
    with pytest.raises(FileExistsError):
        archive.create_manifest(dump, tar, manifest)
    target = tmp_path / "target"
    target.mkdir()
    sentinel = target / "do-not-delete"
    sentinel.write_bytes(b"PRESERVE")
    with pytest.raises(archive.SnapshotArchiveError):
        archive.restore_filestore(tar, target, expected_sha256=descriptor["sha256"])
    assert sentinel.read_bytes() == b"PRESERVE"


def test_empty_existing_target_permitted_but_bad_expected_hash_is_not(tmp_path):
    _root, _dump, tar, _manifest, descriptor, _declared = capture(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    with pytest.raises(archive.SnapshotArchiveError):
        archive.restore_filestore(tar, target, expected_sha256="0" * 64)
    assert not list(target.iterdir())
    archive.restore_filestore(tar, target, expected_sha256=descriptor["sha256"])
    assert list(target.iterdir())


def test_output_cannot_be_inside_source_tree(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    with pytest.raises(archive.SnapshotArchiveError):
        archive.capture_filestore(root, root / "not-allowed.tar")


def test_source_symlink_is_rejected_if_platform_supports_it(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"PRIVATE")
    try:
        (root / "link").symlink_to(outside)
    except OSError:
        pytest.skip("Host does not permit test symlinks")
    with pytest.raises(archive.SnapshotArchiveError):
        archive.capture_filestore(root, tmp_path / "bad.tar")


def test_source_hardlink_rejected_without_publishing_external_bytes(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"PRIVATE")
    try:
        os.link(outside, root / "linked")
    except OSError:
        pytest.skip("Host does not permit test hardlinks")
    with pytest.raises(archive.SnapshotArchiveError, match="^HARDLINK_REJECTED$"):
        archive.capture_filestore(root, tmp_path / "bad.tar")
    assert not (tmp_path / "bad.tar").exists()


def test_cli_success_and_failure_emit_no_paths_or_artifact_contents(tmp_path, capsys):
    root, dump, tar, manifest = files(tmp_path)
    arguments = ["--archive", str(tar), "--dump", str(dump), "--manifest", str(manifest)]
    assert archive.main(["capture", "--filestore", str(root), *arguments]) == 0
    assert archive.main(["verify", *arguments]) == 0
    assert archive.main(["restore", "--target", str(tmp_path / "restored"), *arguments]) == 0
    assert archive.main(["restore", "--target", str(root), *arguments]) == 1
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.splitlines() == ["SNAPSHOT_ARCHIVE_PASS_CAPTURE", "SNAPSHOT_ARCHIVE_PASS_VERIFY",
                                      "SNAPSHOT_ARCHIVE_PASS_RESTORE", "SNAPSHOT_ARCHIVE_FAILED_RESTORE"]


def test_real_cli_process_failure_has_no_traceback(tmp_path):
    completed = subprocess.run([sys.executable, str(ROOT / "scripts/snapshot_archive.py"), "verify",
                                "--archive", str(tmp_path / "absent"), "--dump", str(tmp_path / "absent"),
                                "--manifest", str(tmp_path / "absent")], capture_output=True, text=True)
    assert completed.returncode == 1
    assert completed.stdout == "SNAPSHOT_ARCHIVE_FAILED_VERIFY\n" and completed.stderr == ""
