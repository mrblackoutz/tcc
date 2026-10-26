"""DEC-080 exact zero-offset clock equivalence, not namespace identity.

On one native Linux kernel, each time namespace adds its constant offset to
the common CLOCK_MONOTONIC base. Exact zero preserves both epoch and rate.
Physical domain v1 remains strict and is retained independently by producers.

The same-kernel/local-runc premise is an explicit trusted administrative
deployment assertion, not something a boot fingerprint authenticates. Callers
must measure the actual owned daemon/runtime and reattest each producer's
physical domain before/after use. No clock is sampled, adjusted or converted.
This deliberately excludes unknown runtimes, remote hosts and nonzero offsets.
"""

from __future__ import annotations

import hashlib
import json
import re

from .linux_clock_domain import IMPLEMENTATION, _ZERO_OFFSETS_SHA256, parse_clock_domain


SCOPE_VERSION = "linux-clock-scope/v1"
RUNTIME_VERSION = "local-linux-runtime/v1"
PROFILE = "local-runc-zero-offset/v1"
_RUNTIME_FIELDS = frozenset({"schema_version", "daemon_sha256", "kernel_sha256", "runtime",
    "endpoint_kind", "os_type", "platform"})
_SCOPE_FIELDS = frozenset({"schema_version", "profile", "runtime_binding", "boot_sha256",
    "offsets_sha256", "implementation", "host_id", "clock_id", "scope_sha256"})
_DIGEST = re.compile(r"[0-9a-f]{64}", re.ASCII)


class LinuxClockScopeError(ValueError):
    """Finite failure without payloads, host details, paths or credentials."""


def _fail():
    raise LinuxClockScopeError("invalid Linux zero-offset clock scope") from None


def _require(value):
    if not value:
        _fail()


def _digest(value):
    _require(type(value) is str and _DIGEST.fullmatch(value) is not None)


def _runtime(value):
    _require(type(value) is dict and set(value) == _RUNTIME_FIELDS
        and all(type(item) is str for item in value.values())
        and value["schema_version"] == RUNTIME_VERSION
        and value["runtime"] == "runc" and value["endpoint_kind"] == "local-npipe"
        and value["os_type"] == "linux" and value["platform"] == "linux/amd64")
    _digest(value["daemon_sha256"])
    _digest(value["kernel_sha256"])
    return dict(value)


def _from_base(boot_sha256, runtime_binding):
    _digest(boot_sha256)
    runtime_binding = _runtime(runtime_binding)
    base = {"schema_version": SCOPE_VERSION, "profile": PROFILE,
        "runtime_binding": runtime_binding, "boot_sha256": boot_sha256,
        "offsets_sha256": _ZERO_OFFSETS_SHA256, "implementation": IMPLEMENTATION}
    raw = json.dumps(base, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")
    fingerprint = hashlib.sha256(raw).hexdigest()
    return {**base, "host_id": "kernel-" + boot_sha256[:24],
        "clock_id": "monotonic-zero-" + fingerprint[:40], "scope_sha256": fingerprint}


def parse_clock_scope(value):
    """Recompute a closed administrative scope without I/O or clock access."""
    try:
        _require(type(value) is dict and set(value) == _SCOPE_FIELDS
            and all(type(item) is str for key, item in value.items() if key != "runtime_binding")
            and value["schema_version"] == SCOPE_VERSION and value["profile"] == PROFILE
            and value["implementation"] == IMPLEMENTATION
            and value["offsets_sha256"] == _ZERO_OFFSETS_SHA256)
        expected = _from_base(value["boot_sha256"], value["runtime_binding"])
        _require(value == expected)
        return expected
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError):
        _fail()


def build_clock_scope(domain, runtime_binding):
    """Build an exact-zero scope from a validated physical observation.

    ``runtime_binding`` must come from the independent owned Docker harness,
    never be inferred from the boot ID or a proposed action/model output.
    """
    try:
        observed = parse_clock_domain(domain)
        return _from_base(observed["boot_sha256"], runtime_binding)
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError):
        _fail()


def require_clock_in_scope(domain, scope):
    """Require actual zero-offset physical evidence in the declared scope.

    Deliberately do NOT assert equal namespaces. The strict physical parser
    still validates that observation's own namespace and derived identities.
    The producer/host must separately establish the scope's runtime premise.
    """
    try:
        observed, expected = parse_clock_domain(domain), parse_clock_scope(scope)
        _require(observed["boot_sha256"] == expected["boot_sha256"]
            and observed["offsets_sha256"] == expected["offsets_sha256"]
            and observed["implementation"] == expected["implementation"])
        return expected
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError):
        _fail()


def require_same_scope(*scopes):
    """Compare all closed scope bindings, including daemon and kernel hashes."""
    try:
        _require(bool(scopes))
        expected = parse_clock_scope(scopes[0])
        for value in scopes[1:]:
            _require(parse_clock_scope(value) == expected)
        return expected
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError, RecursionError):
        _fail()
