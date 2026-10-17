"""DEC-059: private, exclusive reset history beside the immutable run store.

The caller provisions distinct sibling roots beneath ``.runtime``. Each slot is
created once, then its checkpoint is flushed/fsynced before its final manifest.
Interrupted directories remain evidence and block reads and further appends;
there is no repair, deletion, rewrite, scheduling, observation or ERP mutation.
Local hash linkage neither authenticates the producer nor establishes external
immutable backup or protection from a hostile filesystem administrator.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

from . import run_record_store as _fs
from .run_record import RunRecord
from .run_reset_checkpoint import (
    MAX_CHECKPOINT_BYTES as _CONTRACT_MAX_BYTES,
    RunResetCheckpoint,
    derive_next_slot_gate,
    parse_run_reset_checkpoint,
)
from .state import canonical_json_bytes


MAX_CHECKPOINTS = 32
MAX_CHECKPOINT_BYTES = min(128 * 1024 * 1024, _CONTRACT_MAX_BYTES)
MAX_MANIFEST_BYTES = 2048
MANIFEST_VERSION = "run-reset-checkpoint-manifest/v1"
CHECKPOINT_NAME = "checkpoint.json"
MANIFEST_NAME = "manifest.json"
_MANIFEST_FIELDS = {
    "schema_version", "run_id", "sequence", "record_sha256",
    "previous_checkpoint_sha256", "checkpoint_sha256", "checkpoint_bytes",
}
_ERROR = "invalid local reset journal operation"
_FAILURES = (OSError, ValueError, TypeError, AttributeError, KeyError,
             OverflowError, RecursionError)


class RunResetJournalError(ValueError):
    """Finite failure without received paths, raw evidence or OS diagnostics."""


@dataclass(frozen=True, slots=True)
class RunResetCheckpointWriteReceipt:
    run_id: str
    sequence: int
    checkpoint_sha256: str
    manifest_sha256: str


@dataclass(frozen=True, slots=True, repr=False)
class _ReadState:
    record_root: Path
    journal_root: Path
    record_root_identity: tuple[int, int]
    journal_root_identity: tuple[int, int]
    record: RunRecord
    record_sha256: str
    checkpoints: tuple[RunResetCheckpoint, ...]
    directory_identity: tuple[int, int] | None


def _fail() -> None:
    raise RunResetJournalError(_ERROR)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _checkpoint_sha256(checkpoint: RunResetCheckpoint) -> str:
    return _sha256(canonical_json_bytes(checkpoint.to_mapping()))


def _digest(value: Any, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) is not str or _fs._SHA256.fullmatch(value) is None:
        _fail()


def _roots(record_root: Path, journal_root: Path):
    record_root, record_identity = _fs._root(record_root)
    journal_root, journal_identity = _fs._root(journal_root)
    # A shared, already-validated parent under .runtime excludes the .runtime
    # directory itself and prevents either store being nested inside the other.
    if (record_root == journal_root or record_root.parent != journal_root.parent
            or ".runtime" not in record_root.parent.parts
            or record_identity == journal_identity):
        _fail()
    return record_root, journal_root, record_identity, journal_identity


def _base(record_root: Path, run_id: str) -> tuple[RunRecord, str]:
    record = _fs.read_run_record(record_root, run_id)
    value = record.to_mapping()
    if value["schema_version"] != "run-record/v2":
        _fail()
    return record, _sha256(canonical_json_bytes(value))


def _files(directory: Path) -> None:
    if _entry_names(directory, 2) != {CHECKPOINT_NAME, MANIFEST_NAME}:
        _fail()
    for name in (CHECKPOINT_NAME, MANIFEST_NAME):
        _fs._regular_file((directory / name).lstat())


def _entries(directory: Path, count: int) -> None:
    if _entry_names(directory, MAX_CHECKPOINTS) != {
            f"{sequence:08d}" for sequence in range(1, count + 1)}:
        _fail()


def _entry_names(directory: Path, limit: int) -> set[str]:
    names: set[str] = set()
    for entry in directory.iterdir():
        names.add(entry.name)
        if len(names) > limit:
            _fail()
    return names


def _verify_roots(state: _ReadState) -> None:
    _fs._verify_directory(state.record_root, state.record_root_identity)
    _fs._verify_directory(state.journal_root, state.journal_root_identity)


def _read_state(*, record_root: Path, journal_root: Path, run_id: str) -> _ReadState:
    record_root, journal_root, record_identity, journal_identity = _roots(record_root, journal_root)
    run_id = _fs._run_id(run_id)
    record, record_sha256 = _base(record_root, run_id)
    directory = _fs._run_directory(journal_root, run_id)
    try:
        directory.lstat()
    except FileNotFoundError:
        _fs._verify_directory(record_root, record_identity)
        _fs._verify_directory(journal_root, journal_identity)
        # The original must still be complete and unchanged, even for an empty
        # history. Absence of a journal never bypasses the base-store contract.
        if _base(record_root, run_id)[1] != record_sha256:
            _fail()
        try:
            directory.lstat()
        except FileNotFoundError:
            return _ReadState(record_root, journal_root, record_identity,
                              journal_identity, record, record_sha256, (), None)
        _fail()
    directory_identity = _fs._identity(_fs._directory_chain(directory))
    count = len(_entry_names(directory, MAX_CHECKPOINTS))
    if not 1 <= count <= MAX_CHECKPOINTS:
        _fail()
    _entries(directory, count)
    history: list[RunResetCheckpoint] = []
    previous_sha256 = None
    for sequence in range(1, count + 1):
        slot = directory / f"{sequence:08d}"
        slot_identity = _fs._identity(_fs._directory_chain(slot))
        _files(slot)
        manifest = _fs._json(_fs._read_bounded(slot / MANIFEST_NAME, MAX_MANIFEST_BYTES))
        if (set(manifest) != _MANIFEST_FIELDS
                or manifest["schema_version"] != MANIFEST_VERSION
                or manifest["run_id"] != run_id
                or type(manifest["sequence"]) is not int
                or manifest["sequence"] != sequence
                or manifest["record_sha256"] != record_sha256
                or manifest["previous_checkpoint_sha256"] != previous_sha256
                or type(manifest["checkpoint_bytes"]) is not int
                or not 0 < manifest["checkpoint_bytes"] <= MAX_CHECKPOINT_BYTES):
            _fail()
        _digest(manifest["record_sha256"])
        _digest(manifest["previous_checkpoint_sha256"], nullable=True)
        _digest(manifest["checkpoint_sha256"])
        raw = _fs._read_bounded(slot / CHECKPOINT_NAME, MAX_CHECKPOINT_BYTES)
        if (len(raw) != manifest["checkpoint_bytes"]
                or _sha256(raw) != manifest["checkpoint_sha256"]):
            _fail()
        checkpoint = parse_run_reset_checkpoint(_fs._json(raw), record=record,
            previous=history[-1] if history else None)
        if (type(checkpoint) is not RunResetCheckpoint
                or checkpoint.run_id != run_id or checkpoint.sequence != sequence):
            _fail()
        history.append(checkpoint)
        previous_sha256 = manifest["checkpoint_sha256"]
        _files(slot)
        _fs._verify_directory(slot, slot_identity)
        _fs._verify_directory(directory, directory_identity)
    checkpoints = tuple(history)
    # Revalidates the complete ordered chain, not just its final element.
    derive_next_slot_gate(record, checkpoints)
    _entries(directory, count)
    _fs._verify_directory(directory, directory_identity)
    _fs._verify_directory(record_root, record_identity)
    _fs._verify_directory(journal_root, journal_identity)
    if _base(record_root, run_id)[1] != record_sha256:
        _fail()
    return _ReadState(record_root, journal_root, record_identity, journal_identity,
                      record, record_sha256, checkpoints, directory_identity)


def read_reset_journal(*, record_root: Path, journal_root: Path,
                       run_id: str) -> tuple[RunResetCheckpoint, ...]:
    """Read a complete bounded chain; reject and retain any partial directory."""

    try:
        return _read_state(record_root=record_root, journal_root=journal_root,
                           run_id=run_id).checkpoints
    except _FAILURES:
        raise RunResetJournalError(_ERROR) from None


def read_stored_next_slot_gate(*, record_root: Path, journal_root: Path,
                               run_id: str) -> str:
    """Derive only local technical continuation; never schedule or authorise."""

    try:
        state = _read_state(record_root=record_root, journal_root=journal_root,
                            run_id=run_id)
        return derive_next_slot_gate(state.record, state.checkpoints)
    except _FAILURES:
        raise RunResetJournalError(_ERROR) from None


def append_reset_checkpoint(*, record_root: Path, journal_root: Path, run_id: str,
                            checkpoint: RunResetCheckpoint,
                            expected_head_sha256: str | None
                            ) -> RunResetCheckpointWriteReceipt:
    """Compare the expected head and exclusively append one complete checkpoint.

    A stale writer, racing mkdir or interrupted fsync fails without cleanup or
    retry. A failure may leave its exclusive slot, which must be preserved.
    Existing source records and completed checkpoints are never overwritten.
    """

    try:
        _digest(expected_head_sha256, nullable=True)
        state = _read_state(record_root=record_root, journal_root=journal_root,
                            run_id=run_id)
        if type(checkpoint) is not RunResetCheckpoint:
            _fail()
        previous = state.checkpoints[-1] if state.checkpoints else None
        head_sha256 = _checkpoint_sha256(previous) if previous is not None else None
        if expected_head_sha256 != head_sha256 or len(state.checkpoints) >= MAX_CHECKPOINTS:
            _fail()
        checkpoint = parse_run_reset_checkpoint(checkpoint.to_mapping(),
            record=state.record, previous=previous)
        sequence = len(state.checkpoints) + 1
        if checkpoint.run_id != run_id or checkpoint.sequence != sequence:
            _fail()
        derive_next_slot_gate(state.record, (*state.checkpoints, checkpoint))
        raw = canonical_json_bytes(checkpoint.to_mapping())
        if not 0 < len(raw) <= MAX_CHECKPOINT_BYTES:
            _fail()
        checkpoint_sha256 = _sha256(raw)
        manifest_raw = canonical_json_bytes({
            "schema_version": MANIFEST_VERSION,
            "run_id": run_id,
            "sequence": sequence,
            "record_sha256": state.record_sha256,
            "previous_checkpoint_sha256": head_sha256,
            "checkpoint_sha256": checkpoint_sha256,
            "checkpoint_bytes": len(raw),
        })
        if not 0 < len(manifest_raw) <= MAX_MANIFEST_BYTES:
            _fail()
        _verify_roots(state)
        directory = _fs._run_directory(state.journal_root, run_id)
        directory_identity = state.directory_identity
        if directory_identity is None:
            directory.mkdir(mode=0o700, exist_ok=False)
            directory_identity = _fs._identity(_fs._directory_chain(directory))
        _fs._verify_directory(directory, directory_identity)
        _entries(directory, sequence - 1)
        slot = directory / f"{sequence:08d}"
        slot.mkdir(mode=0o700, exist_ok=False)
        slot_identity = _fs._identity(_fs._directory_chain(slot))
        _verify_roots(state)
        _fs._verify_directory(directory, directory_identity)
        _entries(directory, sequence)
        if _base(state.record_root, run_id)[1] != state.record_sha256:
            _fail()
        _fs._write_exclusive(slot / CHECKPOINT_NAME, raw)
        _fs._verify_directory(slot, slot_identity)
        _fs._verify_directory(directory, directory_identity)
        _verify_roots(state)
        _fs._write_exclusive(slot / MANIFEST_NAME, manifest_raw)
        _fs._verify_directory(slot, slot_identity)
        _fs._verify_directory(directory, directory_identity)
        _verify_roots(state)
        verified = _read_state(record_root=state.record_root,
            journal_root=state.journal_root, run_id=run_id)
        if (verified.record_sha256 != state.record_sha256
                or len(verified.checkpoints) != sequence
                or _checkpoint_sha256(verified.checkpoints[-1]) != checkpoint_sha256):
            _fail()
        return RunResetCheckpointWriteReceipt(run_id, sequence, checkpoint_sha256,
                                               _sha256(manifest_raw))
    except _FAILURES:
        raise RunResetJournalError(_ERROR) from None
