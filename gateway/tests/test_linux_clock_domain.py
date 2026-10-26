"""DEC-079 pure contracts and mocked Linux kernel observations.

These doubles do not establish that Docker namespaces agree. That requires the
separate pinned-image native proof; Windows never serves as a timing fallback.
"""

import ast
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from tcc_gateway import linux_clock_domain as clock


BOOT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
NS = "time:[4026531834]"


def domain(**changes):
    value = clock._from_fingerprints("a" * 64, "b" * 64, clock._ZERO_OFFSETS_SHA256)
    return dict(value, **changes)


def sample(**changes):
    return dict(schema_version=clock.SAMPLE_VERSION, domain=domain(), monotonic_ns=123456789,
                utc="2026-10-23T14:00:00.123456Z", **changes)


def linux(monkeypatch):
    reads = {"/proc/sys/kernel/random/boot_id": BOOT + "\n",
             "/proc/self/timens_offsets": "monotonic           0         0\nboottime            0         0\n"}
    links = {clock._CURRENT: NS, clock._INIT_CURRENT: NS, clock._CHILDREN: NS}
    info = SimpleNamespace(implementation=clock.IMPLEMENTATION, monotonic=True, adjustable=False, resolution=1e-9)

    def read(path, limit):
        text = reads[path]
        assert len(text.encode("ascii")) <= limit
        return text

    def stat_ns(path):
        return SimpleNamespace(st_dev=4, st_ino=int(links[path].split("[")[1][:-1]), st_mode=stat.S_IFREG | 0o444)

    monkeypatch.setattr(clock, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(clock, "os", SimpleNamespace(name="posix", readlink=lambda path: links[path], stat=stat_ns))
    monkeypatch.setattr(clock, "time", SimpleNamespace(get_clock_info=lambda name: info, monotonic_ns=lambda: 123456789))
    monkeypatch.setattr(clock, "_read_ascii", read)
    return reads, links, info


def rejected(call):
    with pytest.raises(clock.LinuxClockDomainError, match="^invalid Linux monotonic clock evidence$"):
        call()


def test_closed_domain_recomputes_derived_ids_and_returns_a_detached_value():
    original = domain()
    parsed = clock.parse_clock_domain(original)
    assert parsed == original and parsed is not original
    parsed["host_id"] = "CHANGED"
    assert original == domain()
    assert original["host_id"] == "kernel-" + "a" * 24
    assert original["clock_id"] == "monotonic-" + original["domain_sha256"][:40]
    assert len(original["clock_id"]) <= 64


@pytest.mark.parametrize("key,value", [
    ("schema_version", "linux-clock-domain/v2"), ("implementation", "QueryPerformanceCounter()"),
    ("implementation", "clock_gettime(CLOCK_MONOTONIC_RAW)"), ("boot_sha256", "A" * 64),
    ("boot_sha256", "a" * 63), ("time_namespace_sha256", True),
    ("offsets_sha256", "c" * 64), ("domain_sha256", "c" * 64),
    ("host_id", "container-hostname"), ("clock_id", "Windows-clock"),
    ("unapproved_extra", "PRIVATE-MARKER"),
])
def test_domain_rejects_tampering_unknown_fields_and_fallbacks(key, value):
    candidate = domain(**{key: value})
    rejected(lambda: clock.parse_clock_domain(candidate))


@pytest.mark.parametrize("value", [None, [], True, {"schema_version": clock.DOMAIN_VERSION}])
def test_domain_requires_exact_closed_mapping(value):
    rejected(lambda: clock.parse_clock_domain(value))


def test_same_domain_revalidates_every_argument_and_never_changes_it():
    one, two = domain(), domain()
    original = deepcopy((one, two))
    result = clock.require_same_domain(one, two)
    assert result == one and result is not one and result is not two
    assert (one, two) == original
    assert clock.require_same_domain(one) == one


@pytest.mark.parametrize("kind", ["boot", "namespace", "invalid"])
def test_valid_but_different_domain_is_not_a_conversion_or_relabel(kind):
    other = clock._from_fingerprints("c" * 64 if kind == "boot" else "a" * 64,
        "d" * 64 if kind == "namespace" else "b" * 64, clock._ZERO_OFFSETS_SHA256)
    if kind == "invalid":
        other["clock_id"] = domain()["clock_id"]
        other["domain_sha256"] = "f" * 64
    rejected(lambda: clock.require_same_domain(domain(), other))


def test_domain_comparison_needs_at_least_one_actual_envelope():
    rejected(clock.require_same_domain)


def test_mock_linux_measurement_checks_current_init_and_for_children_without_raw_ids(monkeypatch):
    reads, links, _info = linux(monkeypatch)
    value = clock.measure_clock_domain()
    assert value["boot_sha256"] == hashlib.sha256(BOOT.encode("ascii")).hexdigest()
    assert clock.parse_clock_domain(value) == value
    assert BOOT not in str(value) and NS not in str(value)
    # Whitespace and line order do not change the zero-offset identity.
    reads["/proc/self/timens_offsets"] = "boottime\t0\t0\nmonotonic 0 0\n"
    assert clock.measure_clock_domain() == value
    assert set(links) == {"/proc/self/ns/time", "/proc/1/ns/time", "/proc/self/ns/time_for_children"}


@pytest.mark.parametrize("platform,os_name", [("win32", "nt"), ("darwin", "posix"), ("linux", "nt")])
def test_windows_and_other_platforms_fail_before_procfs_or_clock_access(monkeypatch, platform, os_name):
    monkeypatch.setattr(clock, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(clock, "os", SimpleNamespace(name=os_name))

    def forbidden(*_args):
        pytest.fail("unsupported platform attempted a clock or procfs fallback")

    monkeypatch.setattr(clock, "_read_ascii", forbidden)
    monkeypatch.setattr(clock, "time", SimpleNamespace(get_clock_info=forbidden))
    rejected(clock.measure_clock_domain)


@pytest.mark.parametrize("name,value", [
    ("implementation", "QueryPerformanceCounter()"), ("implementation", "clock_gettime(CLOCK_BOOTTIME)"),
    ("monotonic", False), ("monotonic", 1), ("adjustable", True), ("adjustable", 0),
    ("resolution", float("nan")), ("resolution", float("inf")), ("resolution", 0.0), ("resolution", True),
])
def test_clock_implementation_and_real_clock_properties_are_not_asserted_from_a_label(monkeypatch, name, value):
    _reads, _links, info = linux(monkeypatch)
    setattr(info, name, value)
    rejected(clock.measure_clock_domain)


@pytest.mark.parametrize("boot", ["NOT-A-BOOT-ID", BOOT.upper(), "", BOOT + " extra", "PRIVATE-SYNTHETIC-MARKER"])
def test_invalid_boot_identity_is_a_finite_rejection(monkeypatch, boot):
    reads, _links, _info = linux(monkeypatch)
    reads["/proc/sys/kernel/random/boot_id"] = boot
    rejected(clock.measure_clock_domain)


@pytest.mark.parametrize("path", [clock._INIT_CURRENT, clock._CHILDREN])
def test_current_namespace_is_not_replaced_by_init_or_for_children(monkeypatch, path):
    _reads, links, _info = linux(monkeypatch)
    links[path] = "time:[4026531999]"
    rejected(clock.measure_clock_domain)


@pytest.mark.parametrize("text", [
    "monotonic 1 0\nboottime 0 0\n", "monotonic -1 0\nboottime 0 0\n",
    "monotonic 0 1\nboottime 0 0\n", "monotonic 0 0\nboottime -1 0\n",
    "monotonic 0 0\nmonotonic 0 0\n", "monotonic 0 0\n", "",
    "monotonic 0 0\nboottime 0 0\nextra 0 0\n", "monotonic +0 0\nboottime 0 0\n",
    "monotonic 00 0\nboottime 0 0\n",
])
def test_nonzero_missing_duplicate_or_ambiguous_offsets_have_no_estimated_mapping(monkeypatch, text):
    reads, _links, _info = linux(monkeypatch)
    reads["/proc/self/timens_offsets"] = text
    rejected(clock.measure_clock_domain)


@pytest.mark.parametrize("failure", [PermissionError, FileNotFoundError, OSError, RuntimeError])
def test_inaccessible_kernel_evidence_never_echoes_error_text_or_falls_back(monkeypatch, failure):
    linux(monkeypatch)

    def fail(*_args):
        raise failure("PRIVATE-SYNTHETIC-MARKER")

    monkeypatch.setattr(clock.os, "readlink", fail)
    rejected(clock.measure_clock_domain)


def test_link_and_namespace_stat_must_concord_and_remain_stable(monkeypatch):
    linux(monkeypatch)
    monkeypatch.setattr(clock.os, "stat", lambda _path: SimpleNamespace(st_dev=4, st_ino=999, st_mode=stat.S_IFREG))
    rejected(clock.measure_clock_domain)


def test_measurement_rechecks_current_namespace_after_reading_offsets(monkeypatch):
    _reads, links, _info = linux(monkeypatch)
    old = clock._read_ascii

    def changed(path, limit):
        result = old(path, limit)
        if path == "/proc/self/timens_offsets":
            links[clock._CURRENT] = "time:[4026531999]"
        return result

    monkeypatch.setattr(clock, "_read_ascii", changed)
    rejected(clock.measure_clock_domain)


def test_bounded_proc_reader_is_not_dependent_on_proc_stat_size(tmp_path):
    path = tmp_path / "synthetic-kernel-text"
    path.write_bytes(b"short\n")
    assert clock._read_ascii(path, 6) == "short\n"
    rejected(lambda: clock._read_ascii(path, 5))


def test_clock_sample_is_closed_detached_and_utc_canonical():
    original = sample()
    checked = clock.parse_clock_sample(original)
    assert checked == original and checked is not original and checked["domain"] is not original["domain"]
    checked["domain"]["host_id"] = "mutated"
    assert original == sample()


@pytest.mark.parametrize("key,value", [
    ("schema_version", "linux-clock-sample/v2"), ("monotonic_ns", True), ("monotonic_ns", -1),
    ("monotonic_ns", 1.0), ("utc", "2026-10-23T14:00:00Z"),
    ("utc", "2026-10-23T14:00:00.123456+00:00"), ("utc", "2026-10-23T14:00:00.123456-03:00"),
    ("utc", "2026-02-30T14:00:00.123456Z"), ("utc", "2026-10-23T14:00:00.123456Z\n"),
    ("utc", None), ("extra", "PRIVATE-MARKER"),
])
def test_sample_cannot_smuggle_fallbacks_ambiguous_time_or_extra_data(key, value):
    candidate = sample()
    candidate[key] = value
    rejected(lambda: clock.parse_clock_sample(candidate))


def test_sample_reads_real_values_between_two_independent_equal_domain_measurements(monkeypatch):
    linux(monkeypatch)
    calls = []
    old = clock.measure_clock_domain

    def measured():
        calls.append("domain")
        return old()

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz):
            assert tz is timezone.utc
            calls.append("utc")
            return cls(2026, 10, 23, 14, 0, 0, 123456, tzinfo=tz)

    def stamp():
        calls.append("monotonic")
        return 987654321

    monkeypatch.setattr(clock, "measure_clock_domain", measured)
    monkeypatch.setattr(clock.time, "monotonic_ns", stamp)
    monkeypatch.setattr(clock, "datetime", FixedDateTime)
    value = clock.sample_clock()
    assert calls == ["domain", "monotonic", "utc", "domain"]
    assert value["monotonic_ns"] == 987654321 and value["utc"] == "2026-10-23T14:00:00.123456Z"


def test_domain_change_during_sample_does_not_emit_a_stamp(monkeypatch):
    domains = iter((domain(), clock._from_fingerprints("a" * 64, "c" * 64, clock._ZERO_OFFSETS_SHA256)))
    monkeypatch.setattr(clock, "measure_clock_domain", lambda: next(domains))
    rejected(clock.sample_clock)


def test_clock_contract_imports_only_the_standard_library():
    tree = ast.parse(Path(clock.__file__).read_text(encoding="utf-8"))
    allowed = {"__future__", "datetime", "hashlib", "json", "math", "os", "pathlib", "re", "stat", "sys", "time"}
    imported = {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    imported |= {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert imported <= allowed
