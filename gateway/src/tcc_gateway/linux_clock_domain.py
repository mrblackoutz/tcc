"""DEC-079 Linux-only clock evidence; no conversion or cross-host assumption.

Measurements are trusted administrative observations, not authentication of
their producer. Equal hashes are useful only after each participating process
independently measures its own kernel/current time namespace. No timestamp is
translated, no clock is set, and no Windows/estimated-offset fallback exists.

The deliberately narrow profile accepts only the current initial namespace:
own current, PID 1 current and own for-children namespace must agree, and both
exposed offsets must be zero. The for-children link is a rejection guard, never
the identity substituted for the current namespace.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time


DOMAIN_VERSION = "linux-clock-domain/v1"
SAMPLE_VERSION = "linux-clock-sample/v1"
IMPLEMENTATION = "clock_gettime(CLOCK_MONOTONIC)"
_DOMAIN_FIELDS = frozenset({"schema_version", "boot_sha256", "time_namespace_sha256", "offsets_sha256",
    "implementation", "host_id", "clock_id", "domain_sha256"})
_SAMPLE_FIELDS = frozenset({"schema_version", "domain", "monotonic_ns", "utc"})
_DIGEST = re.compile(r"[0-9a-f]{64}", re.ASCII)
_BOOT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.ASCII)
_NAMESPACE = re.compile(r"time:\[([1-9][0-9]{0,19})\]", re.ASCII)
_UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z", re.ASCII)
_CURRENT = "/proc/self/ns/time"
_INIT_CURRENT = "/proc/1/ns/time"
_CHILDREN = "/proc/self/ns/time_for_children"


class LinuxClockDomainError(ValueError):
    """Finite error; never include a path, kernel identity or received value."""


def _fail():
    raise LinuxClockDomainError("invalid Linux monotonic clock evidence")


def _require(value):
    if not value:
        _fail()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


_ZERO_OFFSETS = {"monotonic": {"seconds": 0, "nanoseconds": 0}, "boottime": {"seconds": 0, "nanoseconds": 0}}
_ZERO_OFFSETS_SHA256 = _sha(_ZERO_OFFSETS)


def _from_fingerprints(boot_sha256, time_namespace_sha256, offsets_sha256):
    preimage = {"schema_version": DOMAIN_VERSION, "boot_sha256": boot_sha256,
        "time_namespace_sha256": time_namespace_sha256, "offsets_sha256": offsets_sha256,
        "implementation": IMPLEMENTATION}
    digest = _sha(preimage)
    return {**preimage, "host_id": "kernel-" + boot_sha256[:24],
        "clock_id": "monotonic-" + digest[:40], "domain_sha256": digest}


def parse_clock_domain(value):
    """Check a closed fingerprint envelope without filesystem/clock access."""
    try:
        _require(type(value) is dict and set(value) == _DOMAIN_FIELDS
            and all(type(item) is str for item in value.values())
            and value["schema_version"] == DOMAIN_VERSION and value["implementation"] == IMPLEMENTATION)
        for name in ("boot_sha256", "time_namespace_sha256", "offsets_sha256", "domain_sha256"):
            _require(type(value[name]) is str and _DIGEST.fullmatch(value[name]) is not None)
        _require(value["offsets_sha256"] == _ZERO_OFFSETS_SHA256)
        expected = _from_fingerprints(value["boot_sha256"], value["time_namespace_sha256"], value["offsets_sha256"])
        _require(value == expected)
        return expected
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError):
        raise LinuxClockDomainError("invalid Linux monotonic clock evidence") from None


def require_same_domain(*domains):
    """Revalidate every nonempty argument and require exact domain equality."""
    try:
        _require(bool(domains))
        first = parse_clock_domain(domains[0])
        for value in domains[1:]:
            _require(parse_clock_domain(value) == first)
        return dict(first)
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError):
        raise LinuxClockDomainError("invalid Linux monotonic clock evidence") from None


def _read_ascii(path, limit):
    # Only the fixed kernel paths below call this helper; it is not an arbitrary
    # user-supplied path reader. Bounded allocation also covers procfs stat=0.
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    _require(0 < len(raw) <= limit)
    return raw.decode("ascii", errors="strict")


def _namespace(path):
    link = os.readlink(path)
    match = _NAMESPACE.fullmatch(link) if type(link) is str else None
    _require(match is not None)
    info = os.stat(path)
    _require(type(info.st_dev) is int and info.st_dev >= 0
        and type(info.st_ino) is int and info.st_ino == int(match.group(1))
        and stat.S_ISREG(info.st_mode) and os.readlink(path) == link)
    return {"link": link, "device": info.st_dev, "inode": info.st_ino}


def _offsets(value):
    _require(type(value) is str)
    lines = value.splitlines()
    _require(len(lines) == 2)
    parsed = {}
    for line in lines:
        fields = line.split()
        _require(len(fields) == 3 and fields[0] in {"monotonic", "boottime"}
            and fields[0] not in parsed and fields[1:] == ["0", "0"])
        parsed[fields[0]] = {"seconds": 0, "nanoseconds": 0}
    _require(parsed == _ZERO_OFFSETS)
    return parsed


def measure_clock_domain():
    """Measure this process, its kernel and current namespace, fail closed.

    PID 1 is the persistent container process in the supported proof profile.
    A different/hidden namespace or inaccessible procfs is not guessed away.
    """
    try:
        _require(sys.platform == "linux" and os.name == "posix")
        info = time.get_clock_info("monotonic")
        _require(info.implementation == IMPLEMENTATION and info.monotonic is True and info.adjustable is False
            and type(info.resolution) in {int, float} and math.isfinite(info.resolution) and info.resolution > 0)
        boot = _read_ascii("/proc/sys/kernel/random/boot_id", 64).strip()
        _require(_BOOT.fullmatch(boot) is not None)
        current = _namespace(_CURRENT)
        _require(current == _namespace(_INIT_CURRENT) == _namespace(_CHILDREN))
        offsets = _offsets(_read_ascii("/proc/self/timens_offsets", 256))
        _require(current == _namespace(_CURRENT))
        return parse_clock_domain(_from_fingerprints(hashlib.sha256(boot.encode("ascii")).hexdigest(),
            _sha(current), _sha(offsets)))
    except Exception:
        # Kernel/import errors can contain paths or host details. Preserve only
        # an unambiguous finite rejection; do not downgrade to host timing.
        raise LinuxClockDomainError("invalid Linux monotonic clock evidence") from None


def parse_clock_sample(value):
    """Validate one exact Linux stamp without claiming the producer is trusted."""
    try:
        _require(type(value) is dict and set(value) == _SAMPLE_FIELDS and value["schema_version"] == SAMPLE_VERSION)
        domain = parse_clock_domain(value["domain"])
        _require(type(value["monotonic_ns"]) is int and value["monotonic_ns"] >= 0
            and type(value["utc"]) is str and _UTC.fullmatch(value["utc"]) is not None)
        parsed = datetime.fromisoformat(value["utc"][:-1] + "+00:00")
        _require(parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") == value["utc"])
        return {"schema_version": SAMPLE_VERSION, "domain": domain,
            "monotonic_ns": value["monotonic_ns"], "utc": value["utc"]}
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError):
        raise LinuxClockDomainError("invalid Linux monotonic clock evidence") from None


def sample_clock():
    """Read actual monotonic/UTC clocks between two equal domain measurements.

    The two readings are nearby, not a clock-offset calibration. Callers sample
    before/after their whole callback; they never translate an inner timestamp.
    """
    try:
        before = measure_clock_domain()
        timestamp = time.monotonic_ns()
        utc = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        domain = require_same_domain(before, measure_clock_domain())
        return parse_clock_sample({"schema_version": SAMPLE_VERSION, "domain": domain,
            "monotonic_ns": timestamp, "utc": utc})
    except Exception:
        raise LinuxClockDomainError("invalid Linux monotonic clock evidence") from None
