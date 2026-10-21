"""DEC-068 local CLI failure/safe-output behavior, using structural doubles."""

import hashlib
import json
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory

import pytest

from tcc_gateway.pilot_a3a_origin import prepare_origin_input
from tcc_gateway.pilot_a3a_origin_contract import MAX_ORIGIN_BYTES
from test_pilot_a3a_origin import structural_cohort

ROOT = Path(__file__).resolve().parents[1]
FAIL = '{"status":"FAIL","code":"PILOT_A3A_ORIGIN_INVALID"}\n'


@pytest.fixture
def cli():
    return runpy.run_path(str(ROOT / "scripts/prepare_pilot_a3a_origin.py"))


@pytest.fixture
def local(tmp_path):
    path = tmp_path / ".runtime" / "origin"
    path.mkdir(parents=True)
    return path


@pytest.fixture(scope="module")
def package():
    return prepare_origin_input(structural_cohort())


def test_check_only_finite_summary_without_raw_documents(cli, local, capsys, package):
    path = local / (package.sha256 + ".json")
    path.write_bytes(package._encoded)
    assert cli["main"](["--check", str(path)]) == 0
    output = capsys.readouterr().out
    value = json.loads(output)
    assert value["origin_input_sha256"] == package.sha256 and value["fixture_count"] == 4
    assert value["approval_generated"] is value["scientific_execution_allowed"] is value["human_review_complete"] is False
    assert not any(word in output for word in ("pdf_base64", "SCN-", "document_ref", "TEXT", str(path)))
    assert path.read_bytes() == package._encoded


@pytest.mark.parametrize("kind", ["missing", "directory", "malformed", "oversized", "noncanonical", "outside"])
def test_failure_no_raw_output_or_repair(cli, local, capsys, package, kind):
    path = local / "PRIVATE-MARKER.json"
    if kind == "outside":
        with TemporaryDirectory(prefix="tcc-a3a-origin-test-") as directory:
            external = Path(directory) / path.name
            external.write_bytes(package._encoded)
            assert cli["main"](["--check", str(external)]) == 1
            assert capsys.readouterr().out == FAIL
            assert external.read_bytes() == package._encoded
        return
    raw = package._encoded
    if kind == "directory":
        path.mkdir()
    elif kind != "missing":
        raw = {"malformed": b'{"PRIVATE-MARKER":NaN}', "oversized": b" " * (MAX_ORIGIN_BYTES + 1),
               "noncanonical": raw + b"\n"}[kind]
        path.write_bytes(raw)
    assert cli["main"](["--check", str(path)]) == 1
    assert capsys.readouterr().out == FAIL
    if path.is_file():
        assert path.read_bytes() == raw


def test_generation_codebook_verified_and_exclusive_no_overwrite(cli, local, monkeypatch, capsys):
    codebook = hashlib.sha256((ROOT / "dataset/codebook.md").read_text(encoding="utf-8-sig").encode()).hexdigest()
    cohort = structural_cohort(codebook)
    calls = []
    def read(root, digest):
        calls.append((root, digest))
        return cohort
    monkeypatch.setitem(cli["main"].__globals__, "read_pilot_cohort", read)
    args = ["--cohort-root", str(local), "--cohort-sha256", "a" * 64, "--output-root", str(local)]
    assert cli["main"](args) == 0
    summary = json.loads(capsys.readouterr().out)
    path = local / (summary["origin_input_sha256"] + ".json")
    original = path.read_bytes()
    assert cli["main"](args) == 1 and capsys.readouterr().out == FAIL
    assert path.read_bytes() == original and len(calls) == 2
    monkeypatch.setitem(cli["main"].__globals__, "read_pilot_cohort", lambda *_: structural_cohort("f" * 64))
    assert cli["main"](args) == 1 and capsys.readouterr().out == FAIL


def test_check_cannot_mix_generation_options(cli, local, capsys):
    assert cli["main"](["--check", str(local / "x.json"), "--cohort-sha256", "a" * 64]) == 1
    assert capsys.readouterr().out == FAIL


@pytest.mark.parametrize("member_index", ["-1", "0", "1", "2"])
def test_check_rejects_any_explicit_member_selection_without_reinterpreting_package(
        cli, local, capsys, package, member_index):
    path = local / (package.sha256 + ".json")
    path.write_bytes(package._encoded)
    assert cli["main"](["--check", str(path), "--member-index", member_index]) == 1
    assert capsys.readouterr().out == FAIL
    assert path.read_bytes() == package._encoded


@pytest.mark.parametrize("member_index", [0, 1])
def test_generation_member_selection_keeps_finite_summary_and_exclusive_output(
        cli, local, monkeypatch, capsys, member_index):
    codebook = hashlib.sha256((ROOT / "dataset/codebook.md").read_text(encoding="utf-8-sig").encode()).hexdigest()
    cohort = structural_cohort(codebook)
    monkeypatch.setitem(cli["main"].__globals__, "read_pilot_cohort", lambda *_: cohort)
    expected = prepare_origin_input(cohort, member_index=member_index)
    args = ["--cohort-root", str(local), "--cohort-sha256", "a" * 64,
            "--output-root", str(local), "--member-index", str(member_index)]
    assert cli["main"](args) == 0
    summary = json.loads(capsys.readouterr().out)
    assert set(summary) == {"status", "origin_input_sha256", "seed_sha256", "cohort_sha256",
                           "codebook_sha256", "fixture_count", "counterpart_count", "human_review_complete",
                           "scientific_execution_allowed", "approval_generated"}
    assert summary["origin_input_sha256"] == expected.sha256
    assert summary["fixture_count"] == summary["counterpart_count"] == 4
    assert summary["approval_generated"] is summary["human_review_complete"] is summary["scientific_execution_allowed"] is False
    path = local / (expected.sha256 + ".json")
    assert path.read_bytes() == expected._encoded
    assert cli["main"](args) == 1
    assert capsys.readouterr().out == FAIL
    assert path.read_bytes() == expected._encoded
    assert sorted(item.name for item in local.iterdir()) == [path.name]


@pytest.mark.parametrize("member_index", ["-1", "2"])
def test_generation_rejects_out_of_range_selection_with_finite_failure(
        cli, local, monkeypatch, capsys, member_index):
    inspected = []
    def reject_cohort(*values):
        inspected.append(values)
        raise AssertionError("invalid selection must not read a cohort")
    monkeypatch.setitem(cli["main"].__globals__, "read_pilot_cohort", reject_cohort)
    assert cli["main"](["--cohort-root", str(local), "--cohort-sha256", "a" * 64,
                        "--output-root", str(local), "--member-index", member_index]) == 1
    assert capsys.readouterr().out == FAIL
    assert inspected == []
    assert not list(local.iterdir())
