"""Offline DEC-066 harness/entry gates; no Docker or native proof is run here."""

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
HARNESS = (ROOT / "scripts/test_runner_native.ps1").read_text(encoding="utf-8")
ENTRY = ROOT / "odoo/probes/runner_observed_native.py"
NEW_MODES = (
    ("dataset-fixtures-prepare", "runner_dataset_fixture_native"),
    ("dataset-fixtures", "runner_dataset_fixture_gateway"),
    ("dataset-fixtures-confirm", "runner_dataset_fixture_native"),
)


def entry_module():
    spec = importlib.util.spec_from_file_location("dataset_fixture_native_cli_test", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def arguments(mode):
    return [str(ENTRY), mode, "--database", "tcc_runner_" + "a" * 12,
            "--git-base", "a" * 40, "--source-bundle-sha256", "b" * 64]


def test_dataset_opt_in_requires_observed_before_any_resource_or_directory_creation():
    guard = "if ($WithDatasetFixtures -and -not $WithObserved)"
    assert "param([switch]$WithObserved, [switch]$WithDatasetFixtures," in HARNESS
    assert HARNESS.index(guard) < HARNESS.index("$runId =")
    assert HARNESS.index(guard) < HARNESS.index("New-Item")
    assert HARNESS.index(guard) < HARNESS.index("Invoke-RunnerDocker")
    assert "throw 'Dataset fixture proof requires -WithObserved'" in HARNESS


def test_dataset_sources_are_conditional_and_snapshotted_by_existing_hash_gate():
    start = HARNESS.index("    if ($WithDatasetFixtures) {")
    source_block = HARNESS[start:HARNESS.index("    foreach ($path", start)]
    for name in ("odoo/probes/runner_dataset_fixture_native.py",
                 "odoo/probes/runner_dataset_fixture_gateway.py",
                 "scripts/validate_dataset_fixture_evidence.py"):
        assert repr(name) in source_block
    assert "$sourceHashes = Get-RunnerSourceHashes" in HARNESS
    assert "Assert-RunnerSources $sourceHashes (Get-RunnerSourceHashes)" in HARNESS


def test_fixture_currency_mode_is_forwarded_only_by_the_explicit_harness_flag():
    assignment = "$probeArguments = @('--database', $databaseName, '--git-base', $gitBase, '--source-bundle-sha256', $bundleHash)"
    forwarding = "if ($WithDatasetFixtures) { $probeArguments += '--dataset-fixture-mode' }"
    assert HARNESS.index(assignment) < HARNESS.index(forwarding)
    assert HARNESS.index(forwarding) < HARNESS.index("'prepare') + $probeArguments")
    assert HARNESS.count("'--dataset-fixture-mode'") == 1


def dataset_flow():
    start = HARNESS.index("        Invoke-NativeMode 'dataset-fixtures-prepare'")
    end = HARNESS.index("    if ($WithObserved) {\n        $null = Invoke-RunnerDocker", start)
    return HARNESS[start:end]


def test_dataset_gate_runs_before_unchanged_observed_candidates_and_all_effects():
    flow = dataset_flow()
    fragments = (
        "Invoke-NativeMode 'dataset-fixtures-prepare'", "'dataset-fixtures') + $probeArguments",
        "Invoke-NativeMode 'dataset-fixtures-confirm'", "Assert-RunnerSources",
        "'scripts/validate_dataset_fixture_evidence.py'", "'--artifacts'", "'--git-base'",
        "'--source-bundle-sha256'", "'--output'", "$datasetValidationExitCode -ne 0",
        "$datasetFixtureValidation.status -cne 'PASS'", "$datasetFixtureValidation.case_count -ne 2",
    )
    positions = [flow.index(fragment) for fragment in fragments]
    assert positions == sorted(positions)
    assert "dataset-fixture-validation.json" in flow
    assert "Invoke-NativeMode 'execute'" not in flow
    assert "'candidate'" not in flow
    assert "Get-Content -Raw -Encoding UTF8 -LiteralPath $datasetValidationPath" in flow


@pytest.mark.parametrize("fragment", (
    "$datasetFixtureValidation.schema_version -cne 'dataset-fixture-validation/v1'",
    "$datasetFixtureValidation.git_base -cne $gitBase",
    "$datasetFixtureValidation.source_bundle_sha256 -cne $bundleHash",
    "$datasetFixtureValidation.configuration_sha256 -cnotmatch '^[0-9a-f]{64}$'",
    "$datasetFixtureValidation.case_count -isnot [int]",
    "$datasetFixtureValidation.native_json2_request_count -isnot [int]",
    "$datasetFixtureValidation.native_json2_request_count -le 0",
    "$datasetFixtureValidation.scientific_run -isnot [bool]",
    "$datasetFixtureValidation.human_review_complete -isnot [bool]",
    "$datasetFixtureValidation.public_executor_enabled -isnot [bool]",
))
def test_dataset_proof_rejects_missing_wrong_typed_or_promoted_gate_values(fragment):
    assert fragment in dataset_flow()


def test_opt_in_uses_new_envelope_and_retains_historical_defaults_and_cleanup():
    start = HARNESS.index("        $result.schema_version = 'runner-dataset-fixture-probe-evidence/v1'")
    assert HARNESS.rfind("    if ($WithDatasetFixtures) {", 0, start) >= 0
    extra = HARNESS[start:HARNESS.index("    [System.IO.File]::WriteAllText", start)]
    assert "$result.decision = 'DEC-066'" in extra
    for name in ("dataset_fixture_validation_sha256", "dataset_fixture_case_count",
                 "dataset_fixture_json2_request_count"):
        assert "$result['" + name + "']" in extra
    assert "configuration_sha256 -cne $result.configuration_sha256" in HARNESS[:start]
    assert "schema_version = 'runner-observed-probe-evidence/v1'" in HARNESS
    assert "schema_version = 'runner-native-probe-evidence/v1'" in HARNESS
    assert "$result.status = 'PASS'" in HARNESS
    assert HARNESS.index("$result.status = 'PASS'") > HARNESS.index("'absence-check'")
    assert "Remove-Item" not in HARNESS and "'prune'" not in HARNESS


@pytest.mark.parametrize("mode,module_name", NEW_MODES)
def test_cli_dispatches_dataset_phase_only_to_its_separate_runtime(monkeypatch, capsys, mode, module_name):
    observed = []

    def forbidden(_args):
        raise AssertionError("wrong runtime imported")

    for other in ("runner_observed_fixture", "runner_observed_gateway",
                  "runner_dataset_fixture_native", "runner_dataset_fixture_gateway"):
        monkeypatch.setitem(sys.modules, other, SimpleNamespace(run=forbidden))
    monkeypatch.setitem(sys.modules, module_name, SimpleNamespace(run=lambda args: observed.append(args.mode)))
    monkeypatch.setattr(sys, "argv", arguments(mode))
    entry_module().main()
    assert observed == [mode]
    assert capsys.readouterr().out == "RUNNER_OBSERVED_PASS_" + mode.upper() + "\n"


@pytest.mark.parametrize("enabled", (False, True))
@pytest.mark.parametrize("mode,module_name", (("prepare", "runner_observed_fixture"), *NEW_MODES))
def test_dataset_fixture_cli_mode_defaults_false_and_requires_explicit_flag(
        monkeypatch, capsys, mode, module_name, enabled):
    received = []
    monkeypatch.setitem(sys.modules, module_name,
                        SimpleNamespace(run=lambda args: received.append(args.dataset_fixture_mode)))
    cli = arguments(mode) + (["--dataset-fixture-mode"] if enabled else [])
    monkeypatch.setattr(sys, "argv", cli)
    entry_module().main()
    assert received == [enabled]
    assert capsys.readouterr().out == "RUNNER_OBSERVED_PASS_" + mode.upper() + "\n"


@pytest.mark.parametrize("mode,module_name", NEW_MODES)
@pytest.mark.parametrize("error_name,expected_category", (
    ("DatasetFixtureError", "DatasetFixtureError"), ("ObservedRunnerError", "ObservedRunnerError"),
    ("PrivateUnexpectedName", "OTHER_RUNTIME_FAILURE"),
))
def test_dataset_failure_is_finite_and_never_echoes_raw_context(
        monkeypatch, capsys, mode, module_name, error_name, expected_category):
    private_marker = "PRIVATE-DETAIL-MUST-NOT-APPEAR"
    error_type = type(error_name, (Exception,), {})

    def fail(_args):
        raise error_type(private_marker)

    written = []
    monkeypatch.setitem(sys.modules, module_name, SimpleNamespace(run=fail))
    monkeypatch.setattr(sys, "argv", arguments(mode))
    monkeypatch.setattr(Path, "write_text", lambda path, body, **_kwargs: written.append((path.name, body)))
    with pytest.raises(SystemExit) as caught:
        entry_module().main()
    assert caught.value.code == 1
    assert capsys.readouterr().out == "RUNNER_OBSERVED_FAILED_" + mode.upper() + "\n"
    (name, encoded), = written
    assert name == "observed-failure-" + mode + ".json"
    assert private_marker not in encoded
    diagnostic = json.loads(encoded)
    assert set(diagnostic) == {"schema_version", "status", "mode", "category", "source_file", "source_line"}
    assert diagnostic["schema_version"] == "runner-observed-failure/v1"
    assert diagnostic["status"] == "FAIL" and diagnostic["mode"] == mode
    assert diagnostic["category"] == expected_category
    assert diagnostic["source_file"] == "runner_observed_native.py"
    assert type(diagnostic["source_line"]) is int and diagnostic["source_line"] > 0


@pytest.mark.parametrize("mode,module_name", NEW_MODES)
def test_dataset_cli_still_rejects_path_and_database_drift_before_runtime(
        monkeypatch, mode, module_name):
    def forbidden(_args):
        raise AssertionError("runtime must not run")

    monkeypatch.setitem(sys.modules, module_name, SimpleNamespace(run=forbidden))
    monkeypatch.setattr(sys, "argv", arguments(mode) + ["--database", "production"])
    with pytest.raises(SystemExit, match="RUNNER_OBSERVED_INVALID_CONFIGURATION"):
        entry_module().main()


@pytest.mark.parametrize("code,expected", [("WORKFLOW_STATE_INVALID", "WORKFLOW_STATE_INVALID"),
                                         ("PRIVATE-DETAIL-MUST-NOT-APPEAR", "UNCLASSIFIED")])
def test_opt_in_chained_diagnostic_preserves_old_schema_and_has_only_finite_metadata(
        monkeypatch, capsys, code, expected):
    marker = "PRIVATE-DETAIL-MUST-NOT-APPEAR"
    error_type = type("WorkflowRegistryError", (Exception,), {})

    def fail(_args):
        error = error_type(marker)
        error.code = code
        raise error from ValueError(marker)

    written = []
    monkeypatch.setitem(sys.modules, "runner_observed_fixture", SimpleNamespace(run=fail))
    monkeypatch.setattr(sys, "argv", arguments("prepare") + ["--dataset-fixture-mode"])
    monkeypatch.setattr(Path, "write_text", lambda path, body, **_kwargs: written.append((path.name, body)))
    with pytest.raises(SystemExit):
        entry_module().main()
    assert marker not in capsys.readouterr().out
    assert len(written) == 2 and all(marker not in body for _name, body in written)
    old, extra = (json.loads(body) for _name, body in written)
    assert set(old) == {"schema_version", "status", "mode", "category", "source_file", "source_line"}
    assert extra["schema_version"] == "dataset-fixture-failure/v1" and extra["code"] == expected
    assert extra["locations"] and len(extra["locations"]) <= 16
    for location in extra["locations"]:
        assert set(location) == {"source_file", "source_line"}
        assert type(location["source_line"]) is int and location["source_line"] > 0
