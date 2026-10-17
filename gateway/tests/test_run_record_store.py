"""DEC-056: local synthetic records; no provider, Docker or real raw data."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from tcc_gateway import run_record_store as store
from tcc_gateway.run_record import RunRecord, parse_run_record
from tcc_gateway.state import canonical_json_bytes


@pytest.fixture
def record():
    from test_run_record import valid_record

    value = valid_record()
    return value if type(value) is RunRecord else parse_run_record(value)


@pytest.fixture
def root(tmp_path):
    value = tmp_path / ".runtime" / "records"
    value.mkdir(parents=True)
    return value


def manifest_path(root, record):
    return root / record.run_id / store.MANIFEST_NAME


def record_path(root, record):
    return root / record.run_id / store.RECORD_NAME


def rewrite_manifest(root, record, transform):
    path = manifest_path(root, record)
    value = json.loads(path.read_bytes())
    transform(value)
    path.write_bytes(canonical_json_bytes(value))


def rewrite_record(root, record, raw):
    record_path(root, record).write_bytes(raw)
    rewrite_manifest(root, record, lambda value: value.update({
        "record_bytes": len(raw), "record_sha256": hashlib.sha256(raw).hexdigest(),
    }))


def test_round_trip_is_canonical_bound_and_exclusive(root, record):
    receipt = store.write_run_record(root, record)
    raw = record_path(root, record).read_bytes()
    manifest_raw = manifest_path(root, record).read_bytes()
    manifest = json.loads(manifest_raw)
    assert store.read_run_record(root, record.run_id).to_mapping() == record.to_mapping()
    assert raw == canonical_json_bytes(record.to_mapping())
    assert manifest_raw == canonical_json_bytes(manifest)
    assert manifest == {
        "schema_version": "run-record-manifest/v1", "run_id": record.run_id,
        "record_sha256": hashlib.sha256(raw).hexdigest(), "record_bytes": len(raw),
    }
    assert receipt == store.RunRecordWriteReceipt(
        record.run_id, hashlib.sha256(raw).hexdigest(), hashlib.sha256(manifest_raw).hexdigest(),
    )
    assert set(vars_as_mapping(receipt)) == {"run_id", "record_sha256", "manifest_sha256"}
    with pytest.raises(store.RunRecordStoreError):
        store.write_run_record(root, record)
    assert record_path(root, record).read_bytes() == raw
    assert manifest_path(root, record).read_bytes() == manifest_raw


def vars_as_mapping(receipt):
    return {name: getattr(receipt, name) for name in receipt.__dataclass_fields__}


@pytest.mark.parametrize("kind", ["string", "relative", "missing", "outside", "parent", "case"])
def test_root_is_explicit_existing_absolute_and_under_exact_runtime(tmp_path, record, kind):
    actual = tmp_path / ".runtime" / "records"
    actual.mkdir(parents=True)
    roots = {
        "string": str(actual), "relative": Path(".runtime") / "records",
        "missing": actual / "missing", "outside": Path(tmp_path.anchor) / "synthetic-no-runtime",
        "parent": actual / ".." / "records", "case": Path(tmp_path.anchor) / ".Runtime",
    }
    with pytest.raises(store.RunRecordStoreError):
        store.write_run_record(roots[kind], record)
    assert not (actual / record.run_id).exists()


@pytest.mark.parametrize("component", [
    ".. ", "records.", "records ", "records\t", "records\n", "records\x7f", "records\x85",
    'a:b', 'a<b', 'a>b', 'a"b', 'a|b', 'a?b', 'a*b',
    "CON", "con.txt", "PRN", "AUX.json", "NUL", "COM1", "com9.log", "LPT1", "lpt9.json",
])
def test_nonportable_root_components_are_rejected_before_lookup(root, record, component, monkeypatch):
    # Never create or look up device names / aliases on Windows.
    def forbidden_lookup(_path, *args, **kwargs):
        pytest.fail("nonportable path reached filesystem lookup")

    with monkeypatch.context() as context:
        context.setattr(Path, "lstat", forbidden_lookup)
        with pytest.raises(store.RunRecordStoreError):
            store.write_run_record(root / component, record)
    assert list(root.iterdir()) == []


def test_resolved_root_must_still_have_exact_runtime_and_identity(root, record, tmp_path, monkeypatch):
    original = Path.resolve

    def outside(path, *args, **kwargs):
        return tmp_path if path == root else original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", outside)
    with pytest.raises(store.RunRecordStoreError):
        store.write_run_record(root, record)
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("run_id", [None, True, 1, "", "a" * 31, "A" * 32, "a" * 33,
                                     "../" + "a" * 32, "/" + "a" * 32, "a" * 31 + "\\"])
def test_reader_rejects_untrusted_identity_without_filesystem_writes(root, run_id):
    with pytest.raises(store.RunRecordStoreError):
        store.read_run_record(root, run_id)
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("value", [None, {}, "raw-secret-placeholder", 1, object()])
def test_writer_requires_exact_record_type_and_never_echoes_input(root, value):
    with pytest.raises(store.RunRecordStoreError) as caught:
        store.write_run_record(root, value)
    assert str(caught.value) == "invalid local RunRecord store operation"
    assert "raw-secret-placeholder" not in repr(caught.value)
    assert list(root.iterdir()) == []


def test_existing_incomplete_directory_is_preserved_not_reused(root, record):
    directory = root / record.run_id
    directory.mkdir()
    sentinel = directory / "interrupted"
    sentinel.write_bytes(b"synthetic diagnostic")
    with pytest.raises(store.RunRecordStoreError):
        store.write_run_record(root, record)
    with pytest.raises(store.RunRecordStoreError):
        store.read_run_record(root, record.run_id)
    assert sentinel.read_bytes() == b"synthetic diagnostic"


@pytest.mark.parametrize("name", ["extra.json", "subdirectory"])
def test_reader_refuses_any_extra_entry(root, record, name):
    store.write_run_record(root, record)
    extra = root / record.run_id / name
    extra.mkdir() if name == "subdirectory" else extra.write_bytes(b"synthetic")
    with pytest.raises(store.RunRecordStoreError):
        store.read_run_record(root, record.run_id)


@pytest.mark.parametrize("name", [store.RECORD_NAME, store.MANIFEST_NAME])
def test_reader_refuses_missing_or_empty_file(root, record, name):
    store.write_run_record(root, record)
    path = root / record.run_id / name
    path.write_bytes(b"")
    with pytest.raises(store.RunRecordStoreError):
        store.read_run_record(root, record.run_id)
    path.unlink()
    with pytest.raises(store.RunRecordStoreError):
        store.read_run_record(root, record.run_id)


def test_reader_rejects_record_corruption_without_echo(root, record):
    store.write_run_record(root, record)
    record_path(root, record).write_bytes(b"synthetic-secret-placeholder")
    with pytest.raises(store.RunRecordStoreError) as caught:
        store.read_run_record(root, record.run_id)
    assert "placeholder" not in repr(caught.value)
    assert str(root) not in str(caught.value)


@pytest.mark.parametrize("field,value", [
    ("schema_version", "other/v1"), ("run_id", "f" * 32),
    ("record_bytes", True), ("record_bytes", 0), ("record_bytes", -1),
    ("record_bytes", 1.0), ("record_bytes", store.MAX_RECORD_BYTES + 1),
    ("record_sha256", "A" * 64), ("record_sha256", "0" * 64),
    ("record_sha256", None), ("extra", "synthetic"),
])
def test_manifest_is_closed_typed_and_bound(root, record, field, value):
    store.write_run_record(root, record)
    rewrite_manifest(root, record, lambda manifest: manifest.update({field: value}))
    with pytest.raises(store.RunRecordStoreError):
        store.read_run_record(root, record.run_id)


@pytest.mark.parametrize("transform", [
    lambda raw: raw + b"\n",
    lambda raw: raw.replace(b'{', b'{"run_id":"duplicate",', 1),
    lambda raw: b'{"record_bytes":NaN}',
    lambda raw: b"\xff",
    lambda raw: b"[]",
    lambda raw: b"{}" * 2049,
])
def test_manifest_rejects_noncanonical_duplicate_nonfinite_or_oversized_json(root, record, transform):
    store.write_run_record(root, record)
    path = manifest_path(root, record)
    path.write_bytes(transform(path.read_bytes()))
    with pytest.raises(store.RunRecordStoreError):
        store.read_run_record(root, record.run_id)


@pytest.mark.parametrize("transform", [
    lambda raw: raw + b"\n", lambda raw: b"[]", lambda raw: b"{\"x\":NaN}",
    lambda raw: b'{"identity":{},"identity":{}}', lambda raw: b"\xff",
])
def test_record_json_revalidated_even_when_manifest_hash_is_recomputed(root, record, transform):
    store.write_run_record(root, record)
    rewrite_record(root, record, transform(record_path(root, record).read_bytes()))
    with pytest.raises(store.RunRecordStoreError):
        store.read_run_record(root, record.run_id)


def test_recomputed_hash_does_not_bypass_record_schema_or_run_identity(root, record):
    store.write_run_record(root, record)
    value = record.to_mapping()
    value["identity"]["run_id"] = "e" * 32
    rewrite_record(root, record, canonical_json_bytes(value))
    with pytest.raises(store.RunRecordStoreError):
        store.read_run_record(root, record.run_id)


def test_record_size_limit_is_checked_before_directory_creation(root, record, monkeypatch):
    monkeypatch.setattr(store, "MAX_RECORD_BYTES", 1)
    with pytest.raises(store.RunRecordStoreError):
        store.write_run_record(root, record)
    assert list(root.iterdir()) == []


def test_interrupted_manifest_write_preserves_record_and_blocks_reuse(root, record, monkeypatch):
    original = store._write_exclusive

    def interrupted(path, raw):
        if path.name == store.MANIFEST_NAME:
            raise OSError("synthetic-secret-placeholder")
        original(path, raw)

    with monkeypatch.context() as context:
        context.setattr(store, "_write_exclusive", interrupted)
        with pytest.raises(store.RunRecordStoreError):
            store.write_run_record(root, record)
    assert record_path(root, record).read_bytes() == canonical_json_bytes(record.to_mapping())
    assert not manifest_path(root, record).exists()
    with pytest.raises(store.RunRecordStoreError):
        store.read_run_record(root, record.run_id)
    with pytest.raises(store.RunRecordStoreError):
        store.write_run_record(root, record)


def test_record_fsync_failure_never_creates_manifest(root, record, monkeypatch):
    def interrupted(_descriptor):
        raise OSError("synthetic-secret-placeholder")

    monkeypatch.setattr(store.os, "fsync", interrupted)
    with pytest.raises(store.RunRecordStoreError):
        store.write_run_record(root, record)
    assert record_path(root, record).exists()
    assert not manifest_path(root, record).exists()


def test_record_is_fsynced_before_final_manifest_creation(root, record, monkeypatch):
    events = []
    original_write = store._write_exclusive
    original_fsync = store.os.fsync

    def write(path, raw):
        events.append(("open", path.name))
        original_write(path, raw)

    def sync(descriptor):
        events.append(("fsync", None))
        original_fsync(descriptor)

    monkeypatch.setattr(store, "_write_exclusive", write)
    monkeypatch.setattr(store.os, "fsync", sync)
    store.write_run_record(root, record)
    assert events == [("open", store.RECORD_NAME), ("fsync", None),
                      ("open", store.MANIFEST_NAME), ("fsync", None)]


def test_reparse_attribute_on_ancestor_is_rejected_before_writes(root, record, monkeypatch):
    original = Path.lstat

    def lstat(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == root.parent:
            return SimpleNamespace(st_mode=info.st_mode, st_dev=info.st_dev, st_ino=info.st_ino,
                                   st_file_attributes=store._REPARSE_ATTRIBUTE)
        return info

    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(store.RunRecordStoreError):
        store.write_run_record(root, record)
    assert list(root.iterdir()) == []


def symlink_or_skip(link, target, *, directory=False):
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError:
        pytest.skip("host does not permit symlink fixture creation")


def test_symlink_in_root_chain_is_rejected(tmp_path, record):
    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / ".runtime"
    symlink_or_skip(link, actual, directory=True)
    with pytest.raises(store.RunRecordStoreError):
        store.write_run_record(link, record)
    assert list(actual.iterdir()) == []


def test_symlink_run_directory_is_not_followed(root, record, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    symlink_or_skip(root / record.run_id, outside, directory=True)
    with pytest.raises(store.RunRecordStoreError):
        store.write_run_record(root, record)
    with pytest.raises(store.RunRecordStoreError):
        store.read_run_record(root, record.run_id)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("name", [store.RECORD_NAME, store.MANIFEST_NAME])
def test_symlink_record_file_is_not_followed(root, record, tmp_path, name):
    store.write_run_record(root, record)
    original = root / record.run_id / name
    outside = tmp_path / name
    outside.write_bytes(original.read_bytes())
    original.unlink()
    symlink_or_skip(original, outside)
    with pytest.raises(store.RunRecordStoreError):
        store.read_run_record(root, record.run_id)


@pytest.mark.parametrize("name", [store.RECORD_NAME, store.MANIFEST_NAME])
def test_hardlinked_record_file_is_not_accepted(root, record, tmp_path, name):
    store.write_run_record(root, record)
    original = root / record.run_id / name
    outside = tmp_path / name
    try:
        os.link(original, outside)
    except OSError:
        pytest.skip("host filesystem does not permit hardlink fixtures")
    with pytest.raises(store.RunRecordStoreError):
        store.read_run_record(root, record.run_id)


def test_nonregular_file_is_rejected_without_opening():
    with pytest.raises(store.RunRecordStoreError):
        store._regular_file(SimpleNamespace(st_mode=stat.S_IFIFO, st_nlink=1))
