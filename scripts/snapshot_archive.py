"""DEC-055 bounded, local snapshot integrity and filestore restoration.

This helper never connects to PostgreSQL, removes files, or inspects credentials.
The caller supplies a quiescent, disposable filestore and a custom-format dump.
Hashes identify local artifacts, not an authenticated or scientific snapshot.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tarfile


class SnapshotArchiveError(ValueError):
    """Finite, payload-free failure; never embed a path or underlying message."""


@dataclass(frozen=True)
class Limits:
    max_entries: int = 10_000
    max_file_bytes: int = 67_108_864
    max_total_file_bytes: int = 268_435_456
    max_archive_bytes: int = 285_212_672
    max_dump_bytes: int = 1_073_741_824
    max_manifest_bytes: int = 4_194_304
    max_path_chars: int = 512
    max_path_depth: int = 16

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in vars(self).values()):
            raise SnapshotArchiveError("INVALID_LIMITS")


DEFAULT_LIMITS = Limits()
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CHUNK = 1_048_576


def _require(value, code):
    if not value:
        raise SnapshotArchiveError(code)


def _canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _absolute(path):
    return Path(os.path.abspath(os.fspath(path)))


def _no_link_ancestors(path, *, allow_missing_leaf=False):
    """Never resolve a symlink into a seemingly acceptable target."""
    path = _absolute(path)
    chain = list(reversed(path.parents)) + [path]
    for index, item in enumerate(chain):
        try:
            info = item.lstat()
        except FileNotFoundError:
            _require(allow_missing_leaf and index == len(chain) - 1, "MISSING_PATH")
            continue
        reparse = bool(getattr(info, "st_file_attributes", 0) &
                       getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
        _require(not stat.S_ISLNK(info.st_mode) and not reparse, "LINK_REJECTED")
        if index < len(chain) - 1:
            _require(stat.S_ISDIR(info.st_mode), "INVALID_PARENT")
    return path


def _regular_file(path, maximum):
    path = _no_link_ancestors(path)
    info = path.lstat()
    _require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= maximum,
             "INVALID_ARTIFACT_FILE")
    return path, info


def _open_readonly(path, info):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    current = os.fstat(descriptor)
    if (not stat.S_ISREG(current.st_mode) or current.st_dev != info.st_dev or
            current.st_ino != info.st_ino or current.st_size != info.st_size):
        os.close(descriptor)
        raise SnapshotArchiveError("ARTIFACT_CHANGED")
    return os.fdopen(descriptor, "rb")


def _hash_file(path, maximum, *, magic=None):
    path, info = _regular_file(path, maximum)
    digest = hashlib.sha256()
    with _open_readonly(path, info) as stream:
        if magic is not None:
            prefix = stream.read(len(magic))
            _require(prefix == magic, "INVALID_DUMP_MAGIC")
            digest.update(prefix)
        size = len(magic) if magic is not None else 0
        for chunk in iter(lambda: stream.read(_CHUNK), b""):
            size += len(chunk)
            _require(size <= maximum, "ARTIFACT_SIZE_LIMIT")
            digest.update(chunk)
        _require(size == info.st_size, "ARTIFACT_CHANGED")
    return {"sha256": digest.hexdigest(), "size_bytes": size}


def _member_name(name, limits):
    _require(type(name) is str and 0 < len(name) <= limits.max_path_chars,
             "INVALID_ARCHIVE_PATH")
    _require("\\" not in name and ":" not in name and "\x00" not in name and
             all(ord(character) >= 32 and ord(character) != 127 for character in name),
             "INVALID_ARCHIVE_PATH")
    parts = name.split("/")
    _require(len(parts) <= limits.max_path_depth and
             all(part not in {"", ".", ".."} for part in parts) and
             not PurePosixPath(name).is_absolute(), "INVALID_ARCHIVE_PATH")
    return name


def _descriptor(archive_hash, rows):
    return {"schema_version": "filestore-archive/v1", **archive_hash,
            "entry_count": len(rows), "file_count": sum(row["kind"] == "file" for row in rows),
            "total_file_bytes": sum(row["size_bytes"] for row in rows),
            "inventory_sha256": hashlib.sha256(_canonical(rows)).hexdigest(), "inventory": rows}


def verify_archive(archive, *, expected_sha256=None, limits=DEFAULT_LIMITS):
    """Fully preflight an uncompressed archive, without extracting any member."""
    if expected_sha256 is not None:
        _require(type(expected_sha256) is str and _SHA256.fullmatch(expected_sha256),
                 "INVALID_EXPECTED_HASH")
    archive_hash = _hash_file(archive, limits.max_archive_bytes)
    _require(expected_sha256 is None or archive_hash["sha256"] == expected_sha256,
             "ARCHIVE_HASH_MISMATCH")
    rows, seen, folded, total = [], {}, set(), 0
    try:
        with tarfile.open(archive, mode="r:") as source:
            for member in source:
                _require(len(rows) < limits.max_entries, "ARCHIVE_ENTRY_LIMIT")
                _require(not member.pax_headers and member.type in {tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE}
                         and not member.sparse, "UNSAFE_ARCHIVE_MEMBER")
                name = _member_name(member.name, limits)
                _require(name not in seen and name.casefold() not in folded, "DUPLICATE_ARCHIVE_PATH")
                kind = "directory" if member.isdir() else "file"
                _require(type(member.size) is int and 0 <= member.size <= limits.max_file_bytes,
                         "ARCHIVE_FILE_LIMIT")
                _require(kind == "file" or member.size == 0, "INVALID_DIRECTORY_SIZE")
                total += member.size
                _require(total <= limits.max_total_file_bytes, "ARCHIVE_TOTAL_LIMIT")
                seen[name] = kind
                folded.add(name.casefold())
                file_hash = None
                if kind == "file":
                    stream = source.extractfile(member)
                    _require(stream is not None, "ARCHIVE_FILE_UNREADABLE")
                    digest, copied = hashlib.sha256(), 0
                    with stream:
                        for chunk in iter(lambda: stream.read(_CHUNK), b""):
                            copied += len(chunk)
                            _require(copied <= member.size, "ARCHIVE_FILE_LIMIT")
                            digest.update(chunk)
                    _require(copied == member.size, "ARCHIVE_FILE_TRUNCATED")
                    file_hash = digest.hexdigest()
                rows.append({"path": name, "kind": kind, "size_bytes": member.size, "sha256": file_hash})
        for name in seen:
            parents = PurePosixPath(name).parents
            _require(all(str(parent) == "." or seen.get(str(parent), "directory") == "directory"
                         for parent in parents), "ARCHIVE_PARENT_IS_FILE")
    except (tarfile.TarError, UnicodeError, EOFError) as error:
        raise SnapshotArchiveError("INVALID_ARCHIVE") from None
    # Recheck bytes after parsing; no writer is permitted in the caller's snapshot.
    _require(_hash_file(archive, limits.max_archive_bytes) == archive_hash, "ARTIFACT_CHANGED")
    return _descriptor(archive_hash, sorted(rows, key=lambda row: row["path"]))


def capture_filestore(root, archive, *, limits=DEFAULT_LIMITS):
    """Create a deterministic plain tar, exclusively; absent roots mean empty store."""
    root = _no_link_ancestors(root, allow_missing_leaf=True)
    archive = _no_link_ancestors(archive, allow_missing_leaf=True)
    _require(not archive.exists(), "OUTPUT_ALREADY_EXISTS")
    _require(root != archive and root not in archive.parents, "OUTPUT_INSIDE_FILESTORE")
    paths = []
    if root.exists():
        _require(root.is_dir(), "INVALID_FILESTORE_ROOT")
        pending = [root]
        while pending:
            directory = pending.pop()
            with os.scandir(directory) as entries:
                children = sorted(entries, key=lambda entry: entry.name)
            for entry in children:
                _require(len(paths) < limits.max_entries, "ARCHIVE_ENTRY_LIMIT")
                path = Path(entry.path)
                # Windows DirEntry.stat may report zero inode/device identifiers;
                # a real lstat is required for the later open/fstat identity gate.
                info = path.lstat()
                _require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), "UNSAFE_FILESTORE_MEMBER")
                _require(not stat.S_ISREG(info.st_mode) or info.st_nlink == 1, "HARDLINK_REJECTED")
                name = _member_name(path.relative_to(root).as_posix(), limits)
                paths.append((name, path, info))
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
    total = sum(info.st_size for _, _, info in paths if stat.S_ISREG(info.st_mode))
    _require(total <= limits.max_total_file_bytes, "ARCHIVE_TOTAL_LIMIT")
    _require(all(not stat.S_ISREG(info.st_mode) or info.st_size <= limits.max_file_bytes
                 for _, _, info in paths), "ARCHIVE_FILE_LIMIT")
    try:
        with archive.open("xb") as raw:
            with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as output:
                for name, path, info in sorted(paths):
                    member = tarfile.TarInfo(name)
                    member.uid = member.gid = member.mtime = 0
                    member.uname = member.gname = ""
                    member.mode = 0o750 if stat.S_ISDIR(info.st_mode) else 0o640
                    member.type = tarfile.DIRTYPE if stat.S_ISDIR(info.st_mode) else tarfile.REGTYPE
                    member.size = 0 if member.isdir() else info.st_size
                    _no_link_ancestors(path)
                    if member.isdir():
                        output.addfile(member)
                    else:
                        with _open_readonly(path, info) as stream:
                            output.addfile(member, stream)
                            current = os.fstat(stream.fileno())
                            _require(current.st_size == info.st_size and current.st_mtime_ns == info.st_mtime_ns,
                                     "FILESTORE_CHANGED")
    except (tarfile.TarError, UnicodeError) as error:
        raise SnapshotArchiveError("INVALID_FILESTORE") from None
    return verify_archive(archive, limits=limits)


def _validate_manifest(value):
    _require(type(value) is dict and set(value) == {"schema_version", "dump", "filestore"} and
             value["schema_version"] == "local-state-snapshot/v1", "INVALID_MANIFEST")
    dump = value["dump"]
    _require(type(dump) is dict and set(dump) == {"format", "sha256", "size_bytes"} and
             dump["format"] == "postgres-custom" and type(dump["sha256"]) is str and
             _SHA256.fullmatch(dump["sha256"]) and type(dump["size_bytes"]) is int and
             dump["size_bytes"] >= 5, "INVALID_MANIFEST")
    # The archive descriptor is validated by exact equality with reconstructed facts.
    _require(type(value["filestore"]) is dict, "INVALID_MANIFEST")
    return value


def create_manifest(dump, archive, manifest, *, limits=DEFAULT_LIMITS):
    dump_info = _hash_file(dump, limits.max_dump_bytes, magic=b"PGDMP")
    archive_info = verify_archive(archive, limits=limits)
    value = {"schema_version": "local-state-snapshot/v1",
             "dump": {"format": "postgres-custom", **dump_info}, "filestore": archive_info}
    encoded = _canonical(value) + b"\n"
    _require(len(encoded) <= limits.max_manifest_bytes, "MANIFEST_SIZE_LIMIT")
    path = _no_link_ancestors(manifest, allow_missing_leaf=True)
    with path.open("xb") as output:
        output.write(encoded)
    return value


def verify_manifest(dump, archive, manifest, *, limits=DEFAULT_LIMITS):
    path, info = _regular_file(manifest, limits.max_manifest_bytes)

    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "INVALID_MANIFEST")
            result[key] = value
        return result

    def constant(_value):
        raise SnapshotArchiveError("INVALID_MANIFEST")

    try:
        with _open_readonly(path, info) as stream:
            data = stream.read(limits.max_manifest_bytes + 1)
        _require(len(data) == info.st_size, "ARTIFACT_CHANGED")
        value = _validate_manifest(json.loads(data, object_pairs_hook=pairs, parse_constant=constant))
    except (json.JSONDecodeError, UnicodeError, RecursionError):
        raise SnapshotArchiveError("INVALID_MANIFEST") from None
    dump_info = _hash_file(dump, limits.max_dump_bytes, magic=b"PGDMP")
    archive_info = verify_archive(archive, limits=limits)
    expected = {"schema_version": "local-state-snapshot/v1",
                "dump": {"format": "postgres-custom", **dump_info}, "filestore": archive_info}
    # Canonical bytes, rather than Python equality, distinguish bool from int.
    _require(_canonical(value) == _canonical(expected), "SNAPSHOT_INTEGRITY_MISMATCH")
    return expected


def restore_filestore(archive, target, *, expected_sha256, limits=DEFAULT_LIMITS):
    """Verify all members before creating a fresh target; no deletion or extractall."""
    descriptor = verify_archive(archive, expected_sha256=expected_sha256, limits=limits)
    target = _no_link_ancestors(target, allow_missing_leaf=True)
    archive = _absolute(archive)
    _require(target != archive and target not in archive.parents, "OUTPUT_INSIDE_FILESTORE")
    if target.exists():
        _require(target.is_dir() and not any(target.iterdir()), "TARGET_NOT_EMPTY")
    else:
        target.mkdir(mode=0o750)
    inventory = {row["path"]: row for row in descriptor["inventory"]}
    restored = set()
    with tarfile.open(archive, mode="r:") as source:
        for member in source:
            name = _member_name(member.name, limits)
            _require(name in inventory and name not in restored and not member.pax_headers and
                     member.type in {tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE} and
                     not member.sparse, "ARTIFACT_CHANGED")
            expected = inventory[name]
            kind = "directory" if member.isdir() else "file"
            _require(kind == expected["kind"] and member.size == expected["size_bytes"],
                     "ARTIFACT_CHANGED")
            restored.add(name)
            destination = target.joinpath(*PurePosixPath(name).parts)
            destination.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
            _no_link_ancestors(destination, allow_missing_leaf=True)
            if member.isdir():
                destination.mkdir(mode=0o750, exist_ok=True)
            else:
                stream = source.extractfile(member)
                _require(stream is not None, "ARCHIVE_FILE_UNREADABLE")
                digest, copied = hashlib.sha256(), 0
                with stream, destination.open("xb") as output:
                    for chunk in iter(lambda: stream.read(_CHUNK), b""):
                        copied += len(chunk)
                        _require(copied <= member.size, "ARCHIVE_FILE_LIMIT")
                        output.write(chunk)
                        digest.update(chunk)
                destination.chmod(0o640)
                _require(copied == member.size and digest.hexdigest() == expected["sha256"],
                         "ARTIFACT_CHANGED")
    _require(restored == set(inventory), "ARTIFACT_CHANGED")
    _require(_hash_file(archive, limits.max_archive_bytes)["sha256"] == descriptor["sha256"],
             "ARTIFACT_CHANGED")
    return descriptor


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local disposable snapshot integrity helper")
    parser.add_argument("mode", choices=("capture", "verify", "restore"))
    parser.add_argument("--filestore")
    parser.add_argument("--target")
    parser.add_argument("--archive", required=True)
    parser.add_argument("--dump", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == "capture":
            _require(args.filestore is not None and args.target is None, "INVALID_ARGUMENTS")
            capture_filestore(args.filestore, args.archive)
            create_manifest(args.dump, args.archive, args.manifest)
        else:
            _require(args.filestore is None and (args.target is not None) == (args.mode == "restore"),
                     "INVALID_ARGUMENTS")
            verified = verify_manifest(args.dump, args.archive, args.manifest)
            if args.mode == "restore":
                restore_filestore(args.archive, args.target,
                                  expected_sha256=verified["filestore"]["sha256"])
    except (SnapshotArchiveError, OSError, ValueError, TypeError, tarfile.TarError):
        print("SNAPSHOT_ARCHIVE_FAILED_" + args.mode.upper())
        return 1
    print("SNAPSHOT_ARCHIVE_PASS_" + args.mode.upper())
    return 0


if __name__ == "__main__":
    sys.exit(main())
