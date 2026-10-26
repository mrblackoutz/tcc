"""DEC-079 sampler CLI: closed stdout or finite stderr, no native proof."""

import importlib.util
import json
from pathlib import Path

import pytest

from tcc_gateway import linux_clock_domain as clock


SOURCE = Path(__file__).resolve().parents[2] / "odoo/probes/linux_clock_sample.py"
spec = importlib.util.spec_from_file_location("_tcc_linux_clock_sample_test", SOURCE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def sample():
    return {"schema_version": "linux-clock-sample/v1", "domain": clock._from_fingerprints(
        "a" * 64, "b" * 64, clock._ZERO_OFFSETS_SHA256), "monotonic_ns": 123,
        "utc": "2026-10-23T14:00:00.000000Z"}


def test_success_prints_only_one_exact_canonical_closed_sample(monkeypatch, capsys):
    monkeypatch.setattr(clock, "sample_clock", sample)
    assert probe.main([]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out == json.dumps(sample(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert clock.parse_clock_sample(json.loads(output.out)) == sample()


@pytest.mark.parametrize("arguments", [["--help"], ["--file", "PRIVATE-MARKER"], ["PRIVATE-MARKER"], None, True])
def test_sampler_accepts_no_arguments_and_never_echoes_received_values(arguments, monkeypatch, capsys):
    if arguments is None:
        monkeypatch.setattr(probe.sys, "argv", ["linux_clock_sample.py", "PRIVATE-MARKER"])

    def forbidden():
        pytest.fail("bad arguments reached the clock/procfs reader")

    monkeypatch.setattr(clock, "sample_clock", forbidden)
    assert probe.main(arguments) == 1
    output = capsys.readouterr()
    assert output.out == "" and output.err == "LINUX_CLOCK_SAMPLE_FAILED\n"


def test_failure_has_no_traceback_or_os_error_text(monkeypatch, capsys):
    def failed():
        raise PermissionError("PRIVATE-MARKER")

    monkeypatch.setattr(clock, "sample_clock", failed)
    assert probe.main([]) == 1
    output = capsys.readouterr()
    assert output.out == "" and output.err == "LINUX_CLOCK_SAMPLE_FAILED\n"
