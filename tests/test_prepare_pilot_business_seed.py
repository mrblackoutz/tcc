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


def test_alternative_catalog_check_bound_readonly_and_sanitized(cli, local, capsys):
    from test_pilot_seed import sample_seed
    from test_pilot_alternatives import sample_catalog
    from tcc_gateway.pilot_seed_contract import parse_business_seed, parse_alternative_catalog
    seed = parse_business_seed(sample_seed())
    catalog = parse_alternative_catalog(sample_catalog(seed))
    seed_path, path = local / "seed.json", local / "catalog.json"
    seed_path.write_bytes(seed._encoded)
    path.write_bytes(catalog._encoded)
    assert cli["main"](["--check-alternatives", str(path), "--seed-file", str(seed_path)]) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["catalog_sha256"] == catalog.sha256 and result["seed_sha256"] == seed.sha256
    assert result["bank_count"] == result["vendor_count"] == result["order_count"] == 1
    assert result["human_review_complete"] is result["scientific_execution_allowed"] is False
    assert all(text not in output for text in ("BANK-", "VENDOR-", "PO-01", str(local)))
    assert path.read_bytes() == catalog._encoded and seed_path.read_bytes() == seed._encoded


@pytest.mark.parametrize("kind", ["missing-seed", "wrong-seed", "malformed", "noncanonical", "output", "cohort", "mixed"])
def test_catalog_cli_requires_separate_bound_canonical_private_input(cli, local, capsys, kind):
    from test_pilot_seed import sample_seed
    from test_pilot_alternatives import sample_catalog
    from tcc_gateway.pilot_seed_contract import parse_business_seed, parse_alternative_catalog
    seed = parse_business_seed(sample_seed())
    value = sample_catalog(seed)
    if kind == "wrong-seed":
        value["seed_sha256"] = "e" * 64
    catalog = parse_alternative_catalog(value)
    seed_path, path = local / "seed.json", local / "PRIVATE-MARKER.json"
    seed_path.write_bytes(seed._encoded)
    raw = b'{"PRIVATE-MARKER":NaN}' if kind == "malformed" else catalog._encoded
    if kind == "noncanonical":
        raw += b"\n"
    path.write_bytes(raw)
    args = ["--check-alternatives", str(path)]
    if kind != "missing-seed":
        args.extend(["--seed-file", str(seed_path)])
    if kind == "output":
        args.extend(["--output-root", str(local)])
    elif kind == "cohort":
        args.extend(["--cohort-sha256", "a" * 64])
    elif kind == "mixed":
        args = ["--check", str(seed_path), "--seed-file", str(seed_path)]
    assert cli["main"](args) == 1
    assert capsys.readouterr().out == '{"status":"FAIL","code":"PILOT_BUSINESS_SEED_INVALID"}\n'
    assert path.read_bytes() == raw


def test_prepare_explicit_catalog_is_exclusive_and_does_not_read_notes(cli, local, capsys):
    from test_pilot_seed import sample_seed
    from test_pilot_alternatives import sample_catalog
    from tcc_gateway.pilot_seed_contract import parse_business_seed
    seed = parse_business_seed(sample_seed())
    seed_path, source = local / "seed.json", local / "source.json"
    seed_path.write_bytes(seed._encoded)
    source.write_text(json.dumps(sample_catalog(seed), indent=2), encoding="utf-8")
    before = source.read_bytes()
    args = ["--alternatives-source", str(source), "--seed-file", str(seed_path), "--output-root", str(local)]
    assert cli["main"](args) == 0
    result = json.loads(capsys.readouterr().out)
    prepared = local / (result["catalog_sha256"] + ".json")
    assert prepared.is_file() and result["scientific_execution_allowed"] is False
    raw = prepared.read_bytes()
    assert cli["main"](args) == 1
    assert capsys.readouterr().out == '{"status":"FAIL","code":"PILOT_BUSINESS_SEED_INVALID"}\n'
    assert prepared.read_bytes() == raw and source.read_bytes() == before


@pytest.mark.parametrize("kind", ["no-output", "missing-source", "outside-catalog", "outside-source", "oversized"])
def test_catalog_paths_and_generation_limits_are_fail_closed(cli, local, capsys, kind):
    from test_pilot_seed import sample_seed
    from test_pilot_alternatives import sample_catalog
    from tcc_gateway.pilot_seed_contract import parse_business_seed, parse_alternative_catalog, MAX_ALTERNATIVES_BYTES
    seed = parse_business_seed(sample_seed())
    catalog = parse_alternative_catalog(sample_catalog(seed))
    seed_path, source = local / "seed.json", local / "PRIVATE-MARKER.json"
    seed_path.write_bytes(seed._encoded)
    if kind != "missing-source":
        source.write_bytes(catalog._encoded if kind != "oversized" else b" " * (MAX_ALTERNATIVES_BYTES + 1))
    if kind.startswith("outside-"):
        with TemporaryDirectory(prefix="tcc-catalog-negative-") as directory:
            external = Path(directory) / source.name
            external.write_bytes(catalog._encoded)
            operation = "--check-alternatives" if kind == "outside-catalog" else "--alternatives-source"
            args = [operation, str(external), "--seed-file", str(seed_path)]
            if operation == "--alternatives-source":
                args += ["--output-root", str(local)]
            assert cli["main"](args) == 1
            assert capsys.readouterr().out == '{"status":"FAIL","code":"PILOT_BUSINESS_SEED_INVALID"}\n'
            assert external.read_bytes() == catalog._encoded
        return
    args = ["--alternatives-source", str(source), "--seed-file", str(seed_path)]
    if kind != "no-output":
        args += ["--output-root", str(local)]
    assert cli["main"](args) == 1
    assert capsys.readouterr().out == '{"status":"FAIL","code":"PILOT_BUSINESS_SEED_INVALID"}\n'
