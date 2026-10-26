"""DEC-080 pure clock-value scope tests, not native kernel/runtime evidence.

The runtime and physical domains below are declared administrative doubles.
No syscall clock, namespace, daemon, provider or financial action is accessed.
"""

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from tcc_gateway import linux_clock_domain as physical
from tcc_gateway import linux_clock_scope as clock
from test_linux_clock_domain import domain


def runtime_binding(**changes):
    value = dict(schema_version="local-linux-runtime/v1", daemon_sha256="1" * 64,
        kernel_sha256="2" * 64, runtime="runc", endpoint_kind="local-npipe",
        os_type="linux", platform="linux/amd64")
    value.update(changes)
    return value


def scope():
    return clock.build_clock_scope(domain(), runtime_binding())


def rejected(callback):
    with pytest.raises(clock.LinuxClockScopeError, match="^invalid Linux zero-offset clock scope$"):
        callback()


def test_closed_scope_recomputes_hash_and_detaches_nested_runtime():
    value = scope()
    base = {key: value[key] for key in value.keys() - {"host_id", "clock_id", "scope_sha256"}}
    raw = json.dumps(base, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert value["scope_sha256"] == hashlib.sha256(raw).hexdigest()
    assert value["host_id"] == "kernel-" + domain()["boot_sha256"][:24]
    assert value["clock_id"] == "monotonic-zero-" + value["scope_sha256"][:40]
    assert len(value["clock_id"]) <= 64
    parsed = clock.parse_clock_scope(value)
    assert parsed == value and parsed is not value
    parsed["runtime_binding"]["kernel_sha256"] = "3" * 64
    assert value == scope()


def test_different_physical_namespaces_can_share_exact_zero_value_scope_without_relabelling():
    first = domain()
    second = physical._from_fingerprints(first["boot_sha256"], "c" * 64, first["offsets_sha256"])
    saved = deepcopy((first, second))
    first_scope = clock.build_clock_scope(first, runtime_binding())
    second_scope = clock.build_clock_scope(second, runtime_binding())
    assert first != second and first["domain_sha256"] != second["domain_sha256"]
    assert first["clock_id"] != second["clock_id"]
    assert first_scope == second_scope
    assert clock.require_clock_in_scope(first, second_scope) == first_scope
    assert clock.require_clock_in_scope(second, first_scope) == first_scope
    assert clock.require_same_scope(first_scope, second_scope) == first_scope
    with pytest.raises(physical.LinuxClockDomainError):
        physical.require_same_domain(first, second)
    assert (first, second) == saved


@pytest.mark.parametrize("key,new", [
    ("schema_version", "linux-clock-scope/v2"), ("profile", "estimated-clock-offset/v1"),
    ("boot_sha256", "b" * 64), ("boot_sha256", True), ("offsets_sha256", "c" * 64),
    ("implementation", "clock_gettime(CLOCK_MONOTONIC_RAW)"),
    ("implementation", "QueryPerformanceCounter()"), ("host_id", "container-hostname"),
    ("clock_id", "monotonic-physical-namespace"), ("scope_sha256", "b" * 64),
    ("extra", "SYNTHETIC-MARKER"), ("runtime_binding", []),
])
def test_scope_rejects_closed_contract_tampering_and_fallbacks(key, new):
    value = scope()
    value[key] = new
    rejected(lambda: clock.parse_clock_scope(value))


@pytest.mark.parametrize("field", sorted(clock._SCOPE_FIELDS))
def test_scope_requires_every_field(field):
    value = scope()
    del value[field]
    rejected(lambda: clock.parse_clock_scope(value))


@pytest.mark.parametrize("key,new", [
    ("schema_version", "local-linux-runtime/v2"), ("daemon_sha256", "D" * 64),
    ("daemon_sha256", "1" * 63), ("kernel_sha256", True),
    ("runtime", "runsc"), ("runtime", "kata-runtime"), ("runtime", "sysbox-runc"),
    ("runtime", "io.containerd.runc.v2"), ("runtime", "unknown"),
    ("endpoint_kind", "remote-tcp"), ("os_type", "windows"),
    ("platform", "linux/arm64"), ("extra", "SYNTHETIC-MARKER"),
])
def test_runtime_is_explicit_native_local_runc_profile_only(key, new):
    binding = runtime_binding()
    binding[key] = new
    rejected(lambda: clock.build_clock_scope(domain(), binding))
    candidate = scope()
    candidate["runtime_binding"] = binding
    rejected(lambda: clock.parse_clock_scope(candidate))


@pytest.mark.parametrize("field", sorted(clock._RUNTIME_FIELDS))
def test_runtime_binding_requires_every_field(field):
    binding = runtime_binding()
    del binding[field]
    rejected(lambda: clock.build_clock_scope(domain(), binding))


@pytest.mark.parametrize("field", ["daemon_sha256", "kernel_sha256"])
def test_same_boot_and_zero_offsets_do_not_permit_another_runtime_binding(field):
    first = scope()
    changed = runtime_binding()
    changed[field] = "3" * 64
    second = clock.build_clock_scope(domain(), changed)
    assert first["boot_sha256"] == second["boot_sha256"]
    assert first["clock_id"] != second["clock_id"]
    rejected(lambda: clock.require_same_scope(first, second))


def test_another_valid_kernel_boot_is_not_the_same_value_scope():
    other = physical._from_fingerprints("c" * 64, "b" * 64, physical._ZERO_OFFSETS_SHA256)
    rejected(lambda: clock.require_clock_in_scope(other, scope()))
    rejected(lambda: clock.require_same_scope(scope(), clock.build_clock_scope(other, runtime_binding())))


@pytest.mark.parametrize("key,new", [("offsets_sha256", "c" * 64),
    ("implementation", "clock_gettime(CLOCK_BOOTTIME)"),
    ("time_namespace_sha256", "A" * 64), ("domain_sha256", "0" * 64)])
def test_scope_membership_never_repairs_invalid_physical_evidence(key, new):
    value = domain()
    value[key] = new
    rejected(lambda: clock.build_clock_scope(value, runtime_binding()))
    rejected(lambda: clock.require_clock_in_scope(value, scope()))


def test_even_rehashed_nonzero_physical_offset_is_rejected_by_unchanged_v1_parser():
    value = physical._from_fingerprints("a" * 64, "b" * 64, "c" * 64)
    with pytest.raises(physical.LinuxClockDomainError):
        physical.parse_clock_domain(value)
    rejected(lambda: clock.build_clock_scope(value, runtime_binding()))
    rejected(lambda: clock.require_clock_in_scope(value, scope()))


@pytest.mark.parametrize("value", [None, [], True, "scope"])
def test_nonmapping_scope_or_physical_values_are_not_coerced(value):
    rejected(lambda: clock.parse_clock_scope(value))
    rejected(lambda: clock.build_clock_scope(value, runtime_binding()))
    rejected(lambda: clock.require_clock_in_scope(value, scope()))
    rejected(lambda: clock.require_clock_in_scope(domain(), value))


def test_same_scope_requires_nonempty_validated_arguments_and_returns_detached_value():
    rejected(lambda: clock.require_same_scope())
    rejected(lambda: clock.require_same_scope(scope(), {}))
    original = scope()
    result = clock.require_same_scope(original, deepcopy(original))
    result["runtime_binding"]["kernel_sha256"] = "3" * 64
    assert original == scope()


def test_custom_python_types_cannot_spoof_scope_or_runtime_values():
    class Dictionary(dict):
        pass

    class Text(str):
        pass

    rejected(lambda: clock.parse_clock_scope(Dictionary(scope())))
    value = scope()
    value["profile"] = Text(value["profile"])
    rejected(lambda: clock.parse_clock_scope(value))
    value = scope()
    value["runtime_binding"] = Dictionary(value["runtime_binding"])
    rejected(lambda: clock.parse_clock_scope(value))


def test_scope_builder_preserves_runtime_and_has_no_kernel_filesystem_or_clock_side_effects():
    binding = runtime_binding()
    baseline = deepcopy(binding)
    clock.build_clock_scope(domain(), binding)
    assert binding == baseline
    source = Path(__file__).resolve().parents[1] / "src/tcc_gateway/linux_clock_scope.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    dependencies = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert dependencies <= {"hashlib", "json", "re"}
    calls = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not calls & {"open", "eval", "exec", "measure_clock_domain", "sample_clock"}
