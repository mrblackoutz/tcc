"""DEC-067 local CLI; structural doubles only, never scientific payloads."""

import hashlib
import json
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "gateway/tests"))
    return runpy.run_path(str(ROOT / "scripts/prepare_pilot_business_seed.py"))


@pytest.fixture
def local(tmp_path):
    path = tmp_path / ".runtime" / "business-seed"
    path.mkdir(parents=True)
    return path


def test_check_private_seed_is_readonly_and_stdout_contains_no_records(cli, local, capsys):
    from test_pilot_seed import sample_seed
    from tcc_gateway.pilot_seed_contract import parse_business_seed
    seed = parse_business_seed(sample_seed())
    path = local / "candidate.json"
    path.write_bytes(seed._encoded)
    assert cli["main"](["--check", str(path)]) == 0
    output = capsys.readouterr().out
    value = json.loads(output)
    assert value["seed_sha256"] == seed.sha256 and value["fixture_count"] == 12
    assert value["human_review_complete"] is False and value["scientific_execution_allowed"] is False
    assert "VENDOR-" not in output and "fixtures" not in output and str(path) not in output
    assert path.read_bytes() == seed._encoded


@pytest.mark.parametrize("kind", ["missing", "outside", "malformed", "oversized", "noncanonical", "directory"])
def test_failures_finite_preserve_input_and_reveal_no_path_or_raw_values(cli, local, tmp_path, capsys, kind):
    from test_pilot_seed import sample_seed
    from tcc_gateway.pilot_seed_contract import parse_business_seed, MAX_SEED_BYTES
    raw = parse_business_seed(sample_seed())._encoded
    path = local / "PRIVATE-MARKER.json"
    if kind == "outside":
        # --basetemp itself lives under .runtime; use a real external temp
        # directory, not a sibling still inside that permitted ancestor.
        with TemporaryDirectory(prefix="tcc-pilot-seed-test-") as directory:
            external = Path(directory) / path.name
            external.write_bytes(raw)
            assert cli["main"](["--check", str(external)]) == 1
            assert capsys.readouterr().out == '{"status":"FAIL","code":"PILOT_BUSINESS_SEED_INVALID"}\n'
            assert external.read_bytes() == raw
        return
    if kind == "malformed":
        raw = b'{"PRIVATE-MARKER":NaN}'
    elif kind == "oversized":
        raw = b" " * (MAX_SEED_BYTES + 1)
    elif kind == "noncanonical":
        raw += b"\n"
    if kind == "directory":
        path.mkdir()
    elif kind != "missing":
        path.write_bytes(raw)
    assert cli["main"](["--check", str(path)]) == 1
    assert capsys.readouterr().out == '{"status":"FAIL","code":"PILOT_BUSINESS_SEED_INVALID"}\n'
    if path.is_file():
        assert path.read_bytes() == raw


def test_prepare_reuses_cohort_guard_codebook_and_exclusive_output(cli, local, monkeypatch, capsys):
    from test_pilot_dataset import sample_recipes
    from tcc_gateway.pilot_dataset import parse_pilot_recipes, prepare_pilot_cohort
    recipes = sample_recipes()
    for index, row in enumerate(recipes["pairs"]):
        row["pair"]["truth"]["purchase_order_ref"] = f"PO-{index:02d}"
    codebook = hashlib.sha256((ROOT / "dataset/codebook.md").read_text(encoding="utf-8-sig").encode()).hexdigest()
    cohort = prepare_pilot_cohort(parse_pilot_recipes(recipes), codebook)
    observed = []

    def read(root, digest):
        observed.append((root, digest))
        return cohort

    monkeypatch.setitem(cli["main"].__globals__, "read_pilot_cohort", read)
    args = ["--cohort-root", str(local), "--cohort-sha256", "a" * 64, "--output-root", str(local)]
    assert cli["main"](args) == 0
    result = json.loads(capsys.readouterr().out)
    output = local / (result["seed_sha256"] + ".json")
    assert observed == [(local, "a" * 64)] and output.is_file()
    before = output.read_bytes()
    assert cli["main"](args) == 1
    assert "FAIL" in capsys.readouterr().out and output.read_bytes() == before
    assert len(list(local.iterdir())) == 1


def test_codebook_drift_refuses_output(cli, local, monkeypatch, capsys):
    from test_pilot_dataset import sample_recipes
    from tcc_gateway.pilot_dataset import parse_pilot_recipes, prepare_pilot_cohort
    cohort = prepare_pilot_cohort(parse_pilot_recipes(sample_recipes()), "0" * 64)
    monkeypatch.setitem(cli["main"].__globals__, "read_pilot_cohort", lambda *_args: cohort)
    assert cli["main"](["--cohort-root", str(local), "--cohort-sha256", "a" * 64,
                        "--output-root", str(local)]) == 1
    assert "FAIL" in capsys.readouterr().out and list(local.iterdir()) == []


@pytest.mark.parametrize("extra", [["--output-root", "unused"], ["--cohort-sha256", "a" * 64]])
def test_check_cannot_mix_generation_arguments(cli, local, extra, capsys):
    assert cli["main"](["--check", str(local / "absent.json"), *extra]) == 1
    assert "FAIL" in capsys.readouterr().out
