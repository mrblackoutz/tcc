"""DEC-056: exclusive local persistence, not an external immutable backup.

The caller explicitly creates an absolute store root beneath ``.runtime``.
Raw records never have a public export path here. Link/reparse checks protect
the local operation, not against an administrator concurrently replacing the
filesystem or changing records and all of their integrity hashes together.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from .run_record import RunRecord, parse_run_record
from .state import canonical_json_bytes


MAX_RECORD_BYTES = 128 * 1024 * 1024
MAX_MANIFEST_BYTES = 2048
MANIFEST_VERSION = "run-record-manifest/v1"
RECORD_NAME = "record.json"
MANIFEST_NAME = "manifest.json"
_RUN_ID = re.compile(r"[0-9a-f]{32}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MANIFEST_FIELDS = {"schema_version", "run_id", "record_sha256", "record_bytes"}
_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_RESERVED_CHARACTERS = frozenset(':<>"|?*\\/')
_DEVICE_NAMES = frozenset({"CON", "PRN", "AUX", "NUL", *(
    prefix + str(number) for prefix in ("COM", "LPT") for number in range(1, 10)
)})


class RunRecordStoreError(ValueError):
    """Finite local-store failure, with no path, raw payload or OS error."""


@dataclass(frozen=True, slots=True)
class RunRecordWriteReceipt:
    run_id: str
    record_sha256: str
    manifest_sha256: str


def _fail() -> None:
    raise RunRecordStoreError("invalid local RunRecord store operation")


def _linked(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
    )


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _portable_component(component: str) -> None:
    """Reject ambiguous Win32 spellings on every host before filesystem I/O."""

    if (not component or component.endswith((".", " "))
            or any(character in _RESERVED_CHARACTERS or ord(character) < 32
                   or 0x7f <= ord(character) <= 0x9f for character in component)
            or component.split(".", 1)[0].rstrip(" ").upper() in _DEVICE_NAMES):
        _fail()


def _directory_chain(path: Path) -> os.stat_result:
    """Inspect lexical components before opening or creating any raw file."""

    if not path.is_absolute() or ".." in path.parts:
        _fail()
    # UNC/network shares are not an approved local raw store.
    if path.drive.startswith("\\\\"):
        _fail()
    for component in path.parts[1:]:
        _portable_component(component)
    current = Path(path.anchor)
    info = current.lstat()
    if _linked(info) or not stat.S_ISDIR(info.st_mode):
        _fail()
    for component in path.parts[1:]:
        current = current / component
        info = current.lstat()
        if _linked(info) or not stat.S_ISDIR(info.st_mode):
            _fail()
    return info


def _root(root: Path) -> tuple[Path, tuple[int, int]]:
    if type(root) not in {Path, type(Path())}:
        _fail()
    if ".runtime" not in root.parts:
        _fail()
    identity = _identity(_directory_chain(root))
    canonical = root.resolve(strict=True)
    if (canonical != root or ".runtime" not in canonical.parts
            or _identity(_directory_chain(canonical)) != identity):
        _fail()
    return canonical, identity


def _run_id(value: Any) -> str:
    if type(value) is not str or _RUN_ID.fullmatch(value) is None:
        _fail()
    return value


def _run_directory(root: Path, run_id: str) -> Path:
    result = root / _run_id(run_id)
    if result.parent != root:
        _fail()
    return result


def _verify_directory(path: Path, identity: tuple[int, int]) -> None:
    if _identity(_directory_chain(path)) != identity:
        _fail()


def _regular_file(info: os.stat_result) -> None:
    if _linked(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        _fail()


def _open_flags(*, writing: bool) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL if writing else os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    return flags


def _write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, _open_flags(writing=True), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        _regular_file(os.fstat(stream.fileno()))
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _regular_file(path.lstat())


def _read_bounded(path: Path, limit: int) -> bytes:
    before = path.lstat()
    _regular_file(before)
    if not 0 < before.st_size <= limit:
        _fail()
    descriptor = os.open(path, _open_flags(writing=False))
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        _regular_file(opened)
        if _identity(before) != _identity(opened) or not 0 < opened.st_size <= limit:
            _fail()
        raw = stream.read(limit + 1)
        if len(raw) != opened.st_size or len(raw) > limit:
            _fail()
        after = os.fstat(stream.fileno())
        if _identity(after) != _identity(opened) or after.st_size != opened.st_size:
            _fail()
    if _identity(path.lstat()) != _identity(opened):
        _fail()
    _regular_file(path.lstat())
    return raw


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def _json(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                       parse_constant=lambda _: _fail())
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        _fail()
    return value


def _files(directory: Path) -> None:
    if {path.name for path in directory.iterdir()} != {RECORD_NAME, MANIFEST_NAME}:
        _fail()
    for name in (RECORD_NAME, MANIFEST_NAME):
        _regular_file((directory / name).lstat())


def write_run_record(root: Path, record: RunRecord) -> RunRecordWriteReceipt:
    """Persist once; any partial directory is retained and cannot be reused.

    The record file is flushed and fsynced before the final exclusive manifest
    is created and fsynced. This is local completion evidence, not a claim of
    power-loss safety, external retention, encryption or scientific acceptance.
    """

    try:
        root, root_identity = _root(root)
        if type(record) is not RunRecord:
            _fail()
        checked = parse_run_record(record.to_mapping())
        if checked.run_id != record.run_id:
            _fail()
        raw = canonical_json_bytes(checked.to_mapping())
        if not 0 < len(raw) <= MAX_RECORD_BYTES:
            _fail()
        run_id = _run_id(checked.run_id)
        directory = _run_directory(root, run_id)
        _verify_directory(root, root_identity)
        directory.mkdir(mode=0o700, exist_ok=False)
        directory_identity = _identity(_directory_chain(directory))
        _verify_directory(root, root_identity)
        record_sha256 = hashlib.sha256(raw).hexdigest()
        manifest = canonical_json_bytes({
            "schema_version": MANIFEST_VERSION,
            "run_id": run_id,
            "record_sha256": record_sha256,
            "record_bytes": len(raw),
        })
        _write_exclusive(directory / RECORD_NAME, raw)
        _verify_directory(directory, directory_identity)
        _verify_directory(root, root_identity)
        _write_exclusive(directory / MANIFEST_NAME, manifest)
        _verify_directory(directory, directory_identity)
        _verify_directory(root, root_identity)
        _files(directory)
        return RunRecordWriteReceipt(run_id, record_sha256, hashlib.sha256(manifest).hexdigest())
    except (OSError, ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError):
        raise RunRecordStoreError("invalid local RunRecord store operation") from None


def read_run_record(root: Path, run_id: str) -> RunRecord:
    """Read only a complete, exact two-file record and revalidate its contract."""

    try:
        root, root_identity = _root(root)
        run_id = _run_id(run_id)
        directory = _run_directory(root, run_id)
        directory_identity = _identity(_directory_chain(directory))
        _files(directory)
        manifest = _json(_read_bounded(directory / MANIFEST_NAME, MAX_MANIFEST_BYTES))
        if (set(manifest) != _MANIFEST_FIELDS
                or manifest["schema_version"] != MANIFEST_VERSION
                or manifest["run_id"] != run_id
                or type(manifest["record_bytes"]) is not int
                or not 0 < manifest["record_bytes"] <= MAX_RECORD_BYTES
                or type(manifest["record_sha256"]) is not str
                or _SHA256.fullmatch(manifest["record_sha256"]) is None):
            _fail()
        raw = _read_bounded(directory / RECORD_NAME, MAX_RECORD_BYTES)
        if (len(raw) != manifest["record_bytes"]
                or hashlib.sha256(raw).hexdigest() != manifest["record_sha256"]):
            _fail()
        record = parse_run_record(_json(raw))
        if type(record) is not RunRecord or record.run_id != run_id:
            _fail()
        _verify_directory(directory, directory_identity)
        _verify_directory(root, root_identity)
        _files(directory)
        return record
    except (OSError, ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError):
        raise RunRecordStoreError("invalid local RunRecord store operation") from None
