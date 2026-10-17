"""DEC-059 local synthetic filesystem tests, without API or ERP effects."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from types import SimpleNamespace

import pytest

from tcc_gateway import run_record_store as records
from tcc_gateway import run_reset_journal as store
from tcc_gateway.company_capture import parse_company_capture
from tcc_gateway.run_record import build_run_record
from tcc_gateway.run_record_v2 import build_run_record_v2
from tcc_gateway.run_reset_checkpoint import RunResetCheckpoint, build_run_reset_checkpoint
from tcc_gateway.run_supervision import StageInterval
from tcc_gateway.state import canonical_json_bytes, canonical_json_sha256
from test_company_capture import BINDING, sign
from test_run_record import valid_inputs


@pytest.fixture
def roots(tmp_path):
    record_root = tmp_path / ".runtime" / "records"
    journal_root = record_root.with_name("reset-journal")
    record_root.mkdir(parents=True)
    journal_root.mkdir()
    return record_root, journal_root


@pytest.fixture
def sample(roots):
    inputs = valid_inputs()
    inputs["restored"] = None
    record = build_run_record_v2(**inputs)
    records.write_run_record(roots[0], record)
    return record, inputs


def checkpoint(sample, previous=None, restored="baseline"):
    record, inputs = sample
    if restored == "baseline":
        capture = inputs["baseline"]
    elif restored == "divergent":
        value = inputs["baseline"].to_mapping()
        value["records"]["postgres.sequence"][0]["last_value"] += 1
        capture = parse_company_capture(sign(value), BINDING)
    else:
        assert restored is None
        capture = None
    start = (previous.to_mapping()["supervision"]["intervals"][-1]["ended_ns"]
             if previous is not None else inputs["supervision"].intervals[-1].ended_ns)
    supervision = replace(inputs["supervision"],
        intervals=(StageInterval("capture", start + 1, start + 2),))
    return build_run_reset_checkpoint(record=record, previous=previous,
                                      restored=capture, supervision=supervision)


def read(roots, sample):
    return store.read_reset_journal(record_root=roots[0], journal_root=roots[1],
                                    run_id=sample[0].run_id)


def gate(roots, sample):
    return store.read_stored_next_slot_gate(record_root=roots[0], journal_root=roots[1],
                                           run_id=sample[0].run_id)


def append(roots, sample, value, head=None):
    return store.append_reset_checkpoint(record_root=roots[0], journal_root=roots[1],
        run_id=sample[0].run_id, checkpoint=value, expected_head_sha256=head)


def slot(roots, sample, sequence=1):
    return roots[1] / sample[0].run_id / f"{sequence:08d}"


def rewrite_manifest(roots, sample, transform, sequence=1):
    path = slot(roots, sample, sequence) / store.MANIFEST_NAME
    value = json.loads(path.read_bytes())
    transform(value)
    path.write_bytes(canonical_json_bytes(value))


def rewrite_checkpoint(roots, sample, raw, sequence=1):
    (slot(roots, sample, sequence) / store.CHECKPOINT_NAME).write_bytes(raw)
    rewrite_manifest(roots, sample, lambda value: value.update({
        "checkpoint_bytes": len(raw), "checkpoint_sha256": hashlib.sha256(raw).hexdigest(),
    }), sequence)


def assert_blocked(roots, sample, value):
    for action in (lambda: read(roots, sample), lambda: gate(roots, sample),
                   lambda: append(roots, sample, value)):
        with pytest.raises(store.RunResetJournalError) as caught:
            action()
        assert str(caught.value) == "invalid local reset journal operation"
        assert str(roots[0]) not in repr(caught.value)
        assert "synthetic-secret-placeholder" not in repr(caught.value)


def test_no_journal_requires_valid_base_and_does_not_create_anything(roots, sample):
    assert read(roots, sample) == ()
    assert gate(roots, sample) == "HALT_RESET"
    assert list(roots[1].iterdir()) == []
    assert store.MAX_CHECKPOINTS == 32
    assert store.MAX_CHECKPOINT_BYTES <= 128 * 1024 * 1024


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_round_trip_links_manifest_and_preserves_original_two_files(roots, condition):
    inputs = valid_inputs(condition, attack=True)
    inputs["restored"] = None
    record = build_run_record_v2(**inputs)
    sample = record, inputs
    records.write_run_record(roots[0], record)
    original = {path.name: path.read_bytes() for path in (roots[0] / record.run_id).iterdir()}
    first = checkpoint(sample)
    receipt = append(roots, sample, first)
    checkpoint_raw = (slot(roots, sample) / store.CHECKPOINT_NAME).read_bytes()
    manifest_raw = (slot(roots, sample) / store.MANIFEST_NAME).read_bytes()
    assert checkpoint_raw == canonical_json_bytes(first.to_mapping())
    assert json.loads(manifest_raw) == {
        "schema_version": "run-reset-checkpoint-manifest/v1", "run_id": record.run_id,
        "sequence": 1, "record_sha256": canonical_json_sha256(record.to_mapping()),
        "previous_checkpoint_sha256": None,
        "checkpoint_sha256": hashlib.sha256(checkpoint_raw).hexdigest(),
        "checkpoint_bytes": len(checkpoint_raw),
    }
    assert receipt == store.RunResetCheckpointWriteReceipt(record.run_id, 1,
        hashlib.sha256(checkpoint_raw).hexdigest(), hashlib.sha256(manifest_raw).hexdigest())
    assert tuple(value.to_mapping() for value in read(roots, sample)) == (first.to_mapping(),)
    assert gate(roots, sample) == "CONTINUE"
    assert {path.name: path.read_bytes() for path in (roots[0] / record.run_id).iterdir()} == original
    assert original.keys() == {"record.json", "manifest.json"}
    assert records.read_run_record(roots[0], record.run_id).to_mapping() == record.to_mapping()


def test_absent_and_divergent_observations_are_kept_before_recovery(roots, sample):
    history = []
    head = None
    for kind, expected in ((None, "HALT_RESET"), ("divergent", "HALT_RESET"),
                           ("baseline", "CONTINUE")):
        value = checkpoint(sample, history[-1] if history else None, kind)
        receipt = append(roots, sample, value, head)
        history.append(value)
        head = receipt.checkpoint_sha256
        assert receipt.sequence == len(history)
        assert gate(roots, sample) == expected
    actual = read(roots, sample)
    assert [value.to_mapping()["derived"]["reset_status"] for value in actual] == [
        "UNOBSERVED", "DIVERGED", "VERIFIED"]
    assert [value.sequence for value in actual] == [1, 2, 3]
    assert sample[0].to_mapping()["derived"]["reset_status"] == "UNOBSERVED"


@pytest.mark.parametrize("head", [None, "0" * 64, "A" * 64, True, 1, "", "../outside"])
def test_expected_head_rejects_stale_or_invalid_writer_without_new_slot(roots, sample, head):
    first = checkpoint(sample)
    append(roots, sample, first)
    second = checkpoint(sample, first)
    original = {p.name: p.read_bytes() for p in slot(roots, sample).iterdir()}
    with pytest.raises(store.RunResetJournalError):
        append(roots, sample, second, head)
    assert [p.name for p in slot(roots, sample).parent.iterdir()] == ["00000001"]
    assert {p.name: p.read_bytes() for p in slot(roots, sample).iterdir()} == original


def test_nonempty_head_cannot_create_first_slot(roots, sample):
    with pytest.raises(store.RunResetJournalError):
        append(roots, sample, checkpoint(sample), "0" * 64)
    assert list(roots[1].iterdir()) == []


def test_existing_complete_slot_is_never_overwritten(roots, sample):
    value = checkpoint(sample)
    receipt = append(roots, sample, value)
    original = {p.name: p.read_bytes() for p in slot(roots, sample).iterdir()}
    for head in (None, receipt.checkpoint_sha256):
        with pytest.raises(store.RunResetJournalError):
            append(roots, sample, value, head)
    assert {p.name: p.read_bytes() for p in slot(roots, sample).iterdir()} == original


def test_checkpoint_limit_blocks_before_directory_creation(roots, sample, monkeypatch):
    monkeypatch.setattr(store, "MAX_CHECKPOINTS", 2)
    first = checkpoint(sample)
    one = append(roots, sample, first)
    second = checkpoint(sample, first)
    two = append(roots, sample, second, one.checkpoint_sha256)
    with pytest.raises(store.RunResetJournalError):
        append(roots, sample, checkpoint(sample, second), two.checkpoint_sha256)
    assert len(read(roots, sample)) == 2
    assert not slot(roots, sample, 3).exists()


@pytest.mark.parametrize("limit_name", ["MAX_CHECKPOINT_BYTES", "MAX_MANIFEST_BYTES"])
def test_write_size_limits_apply_before_any_directory(roots, sample, monkeypatch, limit_name):
    value = checkpoint(sample)
    monkeypatch.setattr(store, limit_name, 1)
    with pytest.raises(store.RunResetJournalError):
        append(roots, sample, value)
    assert list(roots[1].iterdir()) == []


@pytest.mark.parametrize("root_name", ["record", "journal"])
@pytest.mark.parametrize("kind", ["string", "relative", "missing", "not_sibling", "parent"])
def test_roots_require_explicit_existing_local_paths(roots, sample, tmp_path, root_name, kind):
    actual = roots[0 if root_name == "record" else 1]
    values = {
        "string": str(actual), "relative": Path(".runtime") / actual.name,
        "missing": actual / "missing", "not_sibling": tmp_path,
        "parent": actual / ".." / actual.name,
    }
    args = {"record_root": roots[0], "journal_root": roots[1], "run_id": sample[0].run_id}
    args[f"{root_name}_root"] = values[kind]
    with pytest.raises(store.RunResetJournalError):
        store.read_reset_journal(**args)
    with pytest.raises(store.RunResetJournalError):
        store.append_reset_checkpoint(**args, checkpoint=checkpoint(sample), expected_head_sha256=None)
    assert list(roots[1].iterdir()) == []


@pytest.mark.parametrize("root_name", ["record", "journal"])
def test_existing_root_genuinely_outside_runtime_is_rejected(roots, sample, root_name):
    # Do not mistake tmp_path for an outside location: the suite may deliberately
    # use a basetemp beneath the project's .runtime. This separate OS temporary
    # directory contains only this synthetic, empty path fixture.
    with TemporaryDirectory(prefix="tcc-reset-outside-runtime-") as scratch:
        outside = Path(scratch).resolve()
        if ".runtime" in outside.parts:
            pytest.skip("OS temporary directory is itself beneath .runtime")
        args = {"record_root": roots[0], "journal_root": roots[1], "run_id": sample[0].run_id}
        args[f"{root_name}_root"] = outside
        with pytest.raises(store.RunResetJournalError):
            store.read_reset_journal(**args)
        with pytest.raises(store.RunResetJournalError):
            store.append_reset_checkpoint(**args, checkpoint=checkpoint(sample), expected_head_sha256=None)
        assert list(outside.iterdir()) == []
    assert list(roots[1].iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Win32 case-alias semantics")
@pytest.mark.parametrize("root_name", ["record", "journal"])
def test_windows_case_alias_under_valid_runtime_ancestor_stays_local(tmp_path, sample, root_name):
    # A different spelling of an inner component is not an escape on Windows
    # when an existing exact .runtime ancestor still authorises the real path.
    # The case alias must name the same directory; no production barrier changes.
    outer = tmp_path / ".runtime" / "case-alias-fixture"
    record_root = outer / ".runtime" / "records"
    journal_root = record_root.with_name("reset-journal")
    record_root.mkdir(parents=True)
    journal_root.mkdir()
    records.write_run_record(record_root, sample[0])
    canonical_roots = record_root, journal_root
    args = {"record_root": record_root, "journal_root": journal_root, "run_id": sample[0].run_id}
    args[f"{root_name}_root"] = outer / ".Runtime" / args[f"{root_name}_root"].name
    assert args[f"{root_name}_root"].samefile(record_root if root_name == "record" else journal_root)
    assert store.read_reset_journal(**args) == ()
    store.append_reset_checkpoint(**args, checkpoint=checkpoint(sample), expected_head_sha256=None)
    assert len(read(canonical_roots, sample)) == 1
    assert gate(canonical_roots, sample) == "CONTINUE"


@pytest.mark.parametrize("kind", ["same", "nested", "reverse_nested", "different_parent", "runtime_root"])
def test_roots_must_be_distinct_dedicated_siblings(roots, sample, kind):
    record_root, journal_root = roots
    if kind == "same":
        journal_root = record_root
    elif kind == "nested":
        journal_root = record_root / "journal"
        journal_root.mkdir()
    elif kind == "reverse_nested":
        record_root = journal_root / "records"
        record_root.mkdir()
    elif kind == "runtime_root":
        journal_root = record_root.parent
    else:
        journal_root = journal_root / "other" / "journal"
        journal_root.mkdir(parents=True)
    with pytest.raises(store.RunResetJournalError):
        store.read_reset_journal(record_root=record_root, journal_root=journal_root,
                                 run_id=sample[0].run_id)


@pytest.mark.parametrize("component", [".. ", "journal.", "journal ", "journal\t", "journal\x85",
                                        "a:b", "a<b", "a?b", "CON", "nul.txt", "COM1", "lpt9.log"])
def test_nonportable_journal_path_is_rejected_without_looking_up_it(roots, sample, component, monkeypatch):
    forbidden = roots[1] / component
    original = Path.lstat

    def lstat(path, *args, **kwargs):
        if path == forbidden:
            pytest.fail("untrusted Win32 spelling reached filesystem lookup")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(store.RunResetJournalError):
        store.read_reset_journal(record_root=roots[0], journal_root=forbidden, run_id=sample[0].run_id)
    assert list(roots[1].iterdir()) == []


@pytest.mark.parametrize("run_id", [None, True, 1, "", "A" * 32, "a" * 31, "a" * 33,
                                     "../" + "a" * 32, "/" + "a" * 32])
def test_run_identity_is_closed_before_any_write(roots, sample, run_id):
    with pytest.raises(store.RunResetJournalError):
        store.append_reset_checkpoint(record_root=roots[0], journal_root=roots[1], run_id=run_id,
                                       checkpoint=checkpoint(sample), expected_head_sha256=None)
    assert list(roots[1].iterdir()) == []


@pytest.mark.parametrize("value", [None, {}, 1, "synthetic-secret-placeholder", object()])
def test_checkpoint_type_is_exact_and_error_never_echoes_payload(roots, sample, value):
    with pytest.raises(store.RunResetJournalError) as caught:
        append(roots, sample, value)
    assert str(caught.value) == "invalid local reset journal operation"
    assert "placeholder" not in repr(caught.value)
    assert list(roots[1].iterdir()) == []


def test_forged_typed_checkpoint_is_revalidated_before_write(roots, sample):
    value = checkpoint(sample).to_mapping()
    value["derived"]["batch_gate"] = "HALT_RESET"
    forged = RunResetCheckpoint(canonical_json_bytes(value))
    with pytest.raises(store.RunResetJournalError):
        append(roots, sample, forged)
    assert list(roots[1].iterdir()) == []


def test_checkpoint_from_another_condition_cannot_be_appended(roots, sample):
    inputs = valid_inputs("C0")
    record = build_run_record_v2(**inputs)
    other = checkpoint((record, inputs))
    with pytest.raises(store.RunResetJournalError):
        append(roots, sample, other)
    assert list(roots[1].iterdir()) == []


def test_virtual_predecessor_does_not_establish_a_chain(roots, sample):
    first = checkpoint(sample)
    with pytest.raises(store.RunResetJournalError):
        append(roots, sample, checkpoint(sample, first))
    assert list(roots[1].iterdir()) == []


def test_v1_base_is_not_silently_promoted_to_reset_recovery(roots):
    inputs = valid_inputs()
    record = build_run_record(**inputs)
    records.write_run_record(roots[0], record)
    with pytest.raises(store.RunResetJournalError):
        store.read_reset_journal(record_root=roots[0], journal_root=roots[1], run_id=record.run_id)
    assert list(roots[1].iterdir()) == []


@pytest.mark.parametrize("kind", ["missing_record", "partial_record", "corrupt_record", "record_extra"])
def test_empty_history_never_masks_invalid_or_incomplete_original(roots, sample, kind):
    directory = roots[0] / sample[0].run_id
    if kind == "missing_record":
        (directory / records.RECORD_NAME).unlink()
        (directory / records.MANIFEST_NAME).unlink()
        directory.rmdir()
    elif kind == "partial_record":
        (directory / records.MANIFEST_NAME).unlink()
    elif kind == "corrupt_record":
        (directory / records.RECORD_NAME).write_bytes(b"synthetic-secret-placeholder")
    else:
        (directory / "extra.json").write_bytes(b"synthetic")
    assert_blocked(roots, sample, checkpoint(sample))
    assert list(roots[1].iterdir()) == []


def change_base(roots, sample):
    value = sample[0].to_mapping()
    value["policy_sha256"] = "a" * 64
    raw = canonical_json_bytes(value)
    directory = roots[0] / sample[0].run_id
    (directory / records.RECORD_NAME).write_bytes(raw)
    manifest = json.loads((directory / records.MANIFEST_NAME).read_bytes())
    manifest.update(record_sha256=hashlib.sha256(raw).hexdigest(), record_bytes=len(raw))
    (directory / records.MANIFEST_NAME).write_bytes(canonical_json_bytes(manifest))


def test_changed_valid_base_and_recomputed_record_manifest_break_the_journal_binding(roots, sample):
    first = checkpoint(sample)
    append(roots, sample, first)
    original_checkpoint = (slot(roots, sample) / store.CHECKPOINT_NAME).read_bytes()
    change_base(roots, sample)
    assert records.read_run_record(roots[0], sample[0].run_id).to_mapping()["policy_sha256"] == "a" * 64
    assert_blocked(roots, sample, first)
    assert (slot(roots, sample) / store.CHECKPOINT_NAME).read_bytes() == original_checkpoint


@pytest.mark.parametrize("field,value", [
    ("schema_version", "other/v1"), ("run_id", "f" * 32),
    ("sequence", True), ("sequence", 0), ("sequence", 2), ("sequence", 1.0),
    ("record_sha256", "0" * 64), ("record_sha256", None),
    ("previous_checkpoint_sha256", "0" * 64), ("previous_checkpoint_sha256", True),
    ("checkpoint_sha256", "A" * 64), ("checkpoint_sha256", "0" * 64),
    ("checkpoint_bytes", True), ("checkpoint_bytes", 0), ("checkpoint_bytes", -1),
    ("checkpoint_bytes", 1.0), ("checkpoint_bytes", store.MAX_CHECKPOINT_BYTES + 1),
    ("extra", "synthetic"),
])
def test_manifest_is_closed_typed_and_bound(roots, sample, field, value):
    first = checkpoint(sample)
    append(roots, sample, first)
    rewrite_manifest(roots, sample, lambda manifest: manifest.update({field: value}))
    assert_blocked(roots, sample, first)


@pytest.mark.parametrize("target", [store.CHECKPOINT_NAME, store.MANIFEST_NAME])
@pytest.mark.parametrize("transform", [
    lambda raw: raw + b"\n", lambda raw: b"[]", lambda raw: b"\xff",
    lambda raw: b'{"sequence":NaN}', lambda raw: b'{"sequence":Infinity}',
    lambda raw: b'{"identity":{},"identity":{}}',
])
def test_json_is_canonical_duplicate_free_and_finite_even_after_rehash(roots, sample, target, transform):
    first = checkpoint(sample)
    append(roots, sample, first)
    path = slot(roots, sample) / target
    raw = transform(path.read_bytes())
    if target == store.CHECKPOINT_NAME:
        rewrite_checkpoint(roots, sample, raw)
    else:
        path.write_bytes(raw)
    assert_blocked(roots, sample, first)


@pytest.mark.parametrize("name", [store.CHECKPOINT_NAME, store.MANIFEST_NAME])
@pytest.mark.parametrize("kind", ["absent", "empty", "directory", "oversized"])
def test_noncomplete_or_unbounded_slot_files_block_reads_and_appends(roots, sample, name, kind, monkeypatch):
    first = checkpoint(sample)
    append(roots, sample, first)
    path = slot(roots, sample) / name
    if kind == "empty":
        path.write_bytes(b"")
    elif kind == "oversized":
        monkeypatch.setattr(store, "MAX_CHECKPOINT_BYTES" if name == store.CHECKPOINT_NAME
                            else "MAX_MANIFEST_BYTES", 1)
    else:
        path.unlink()
        if kind == "directory":
            path.mkdir()
    assert_blocked(roots, sample, first)


@pytest.mark.parametrize("kind", ["empty_run", "empty_slot", "run_extra", "slot_extra", "gap",
                                   "zero", "noncanonical", "slot_file", "too_many"])
def test_partial_or_noncontiguous_directory_layout_is_never_repaired(roots, sample, kind):
    first = checkpoint(sample)
    if kind == "empty_run":
        slot(roots, sample).parent.mkdir()
    elif kind == "empty_slot":
        slot(roots, sample).mkdir(parents=True)
    else:
        append(roots, sample, first)
        if kind in {"run_extra", "slot_extra"}:
            parent = slot(roots, sample).parent if kind == "run_extra" else slot(roots, sample)
            (parent / "extra.json").write_bytes(b"synthetic-secret-placeholder")
        elif kind in {"gap", "zero", "noncanonical"}:
            slot(roots, sample).rename(slot(roots, sample).with_name({
                "gap": "00000002", "zero": "00000000", "noncanonical": "1"}[kind]))
        elif kind == "slot_file":
            (slot(roots, sample, 2)).write_bytes(b"synthetic")
        else:
            for sequence in range(2, store.MAX_CHECKPOINTS + 2):
                slot(roots, sample, sequence).mkdir()
    before = sorted(str(p.relative_to(roots[1])) for p in roots[1].rglob("*"))
    assert_blocked(roots, sample, first)
    assert sorted(str(p.relative_to(roots[1])) for p in roots[1].rglob("*")) == before


@pytest.mark.parametrize("phase", ["checkpoint", "manifest", "fsync_checkpoint", "fsync_manifest"])
def test_interrupted_write_is_preserved_and_permanently_blocks_reuse(roots, sample, monkeypatch, phase):
    value = checkpoint(sample)
    original_write = store._fs._write_exclusive
    original_sync = store._fs.os.fsync
    synced = 0

    def write(path, raw):
        if phase == "checkpoint" and path.name == store.CHECKPOINT_NAME:
            raise OSError("synthetic-secret-placeholder")
        if phase == "manifest" and path.name == store.MANIFEST_NAME:
            raise OSError("synthetic-secret-placeholder")
        original_write(path, raw)

    def sync(descriptor):
        nonlocal synced
        synced += 1
        if (phase == "fsync_checkpoint" and synced == 1
                or phase == "fsync_manifest" and synced == 2):
            raise OSError("synthetic-secret-placeholder")
        original_sync(descriptor)

    with monkeypatch.context() as context:
        context.setattr(store._fs, "_write_exclusive", write)
        context.setattr(store._fs.os, "fsync", sync)
        with pytest.raises(store.RunResetJournalError):
            append(roots, sample, value)
    assert slot(roots, sample).is_dir()
    if phase in {"manifest", "fsync_checkpoint", "fsync_manifest"}:
        assert (slot(roots, sample) / store.CHECKPOINT_NAME).read_bytes() == canonical_json_bytes(value.to_mapping())
    if phase != "fsync_manifest":
        assert not (slot(roots, sample) / store.MANIFEST_NAME).exists()
        assert_blocked(roots, sample, value)
    else:
        # A final fsync failure may leave both complete bytes: it never permits
        # rewriting them, and recovery cannot infer a durability guarantee.
        original = {p.name: p.read_bytes() for p in slot(roots, sample).iterdir()}
        with pytest.raises(store.RunResetJournalError):
            append(roots, sample, value)
        assert {p.name: p.read_bytes() for p in slot(roots, sample).iterdir()} == original


def test_checkpoint_fsync_precedes_final_manifest_creation(roots, sample, monkeypatch):
    events = []
    original_write = store._fs._write_exclusive
    original_sync = store._fs.os.fsync

    def write(path, raw):
        events.append(("open", path.name))
        original_write(path, raw)

    def sync(descriptor):
        events.append(("fsync", None))
        original_sync(descriptor)

    monkeypatch.setattr(store._fs, "_write_exclusive", write)
    monkeypatch.setattr(store._fs.os, "fsync", sync)
    append(roots, sample, checkpoint(sample))
    assert events == [("open", store.CHECKPOINT_NAME), ("fsync", None),
                      ("open", store.MANIFEST_NAME), ("fsync", None)]


def test_concurrent_compare_and_append_allows_exactly_one_writer(roots, sample, monkeypatch):
    first = checkpoint(sample)
    head = append(roots, sample, first).checkpoint_sha256
    second = checkpoint(sample, first)
    rendezvous = Barrier(2, timeout=20)
    original = Path.mkdir

    def mkdir(path, *args, **kwargs):
        if path == slot(roots, sample, 2):
            rendezvous.wait()
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)

    def writer():
        try:
            return append(roots, sample, second, head)
        except store.RunResetJournalError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: writer(), range(2)))
    assert sum(result is not None for result in results) == 1
    assert len(read(roots, sample)) == 2
    assert [p.name for p in slot(roots, sample).parent.iterdir()] == ["00000001", "00000002"]


@pytest.mark.parametrize("location", ["ancestor", "run", "slot", "checkpoint", "manifest"])
def test_reparse_attributes_are_rejected_without_following(roots, sample, monkeypatch, location):
    first = checkpoint(sample)
    append(roots, sample, first)
    paths = {"ancestor": roots[1], "run": slot(roots, sample).parent,
             "slot": slot(roots, sample), "checkpoint": slot(roots, sample) / store.CHECKPOINT_NAME,
             "manifest": slot(roots, sample) / store.MANIFEST_NAME}
    original = Path.lstat

    def lstat(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == paths[location]:
            return SimpleNamespace(st_mode=info.st_mode, st_dev=info.st_dev, st_ino=info.st_ino,
                                   st_file_attributes=records._REPARSE_ATTRIBUTE)
        return info

    monkeypatch.setattr(Path, "lstat", lstat)
    assert_blocked(roots, sample, first)


@pytest.mark.parametrize("name", [store.CHECKPOINT_NAME, store.MANIFEST_NAME])
def test_hardlinked_files_are_rejected(roots, sample, tmp_path, name):
    first = checkpoint(sample)
    append(roots, sample, first)
    try:
        os.link(slot(roots, sample) / name, tmp_path / name)
    except OSError:
        pytest.skip("host does not permit hardlink fixtures")
    assert_blocked(roots, sample, first)


@pytest.mark.parametrize("location", ["run", "slot", "checkpoint", "manifest"])
def test_symbolic_links_are_not_followed(roots, sample, tmp_path, location):
    first = checkpoint(sample)
    append(roots, sample, first)
    if location in {"run", "slot"}:
        original = slot(roots, sample).parent if location == "run" else slot(roots, sample)
    else:
        original = slot(roots, sample) / (store.CHECKPOINT_NAME if location == "checkpoint" else store.MANIFEST_NAME)
    outside = tmp_path / "outside"
    is_directory = original.is_dir()
    original.rename(outside)
    try:
        original.symlink_to(outside, target_is_directory=is_directory)
    except OSError:
        pytest.skip("host does not permit symlink fixture creation")
    assert_blocked(roots, sample, first)


def test_original_changed_during_append_cannot_return_completion_receipt(roots, sample, monkeypatch):
    first = checkpoint(sample)
    original = store._fs._write_exclusive

    def write(path, raw):
        original(path, raw)
        if path.name == store.CHECKPOINT_NAME:
            change_base(roots, sample)

    with monkeypatch.context() as context:
        context.setattr(store._fs, "_write_exclusive", write)
        with pytest.raises(store.RunResetJournalError):
            append(roots, sample, first)
    assert (slot(roots, sample) / store.CHECKPOINT_NAME).is_file()
    assert_blocked(roots, sample, first)
