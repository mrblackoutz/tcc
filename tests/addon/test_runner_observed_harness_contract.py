"""Static harness checks supplement, but never replace, native DEC-054 proof."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "scripts/test_runner_native.ps1").read_text(encoding="utf-8")


def test_observed_roundtrip_is_explicit_opt_in_and_legacy_modes_remain():
    assert "param([switch]$WithObserved" in SOURCE
    assert "if ($WithObserved)" in SOURCE
    assert "'runner-observed-probe-evidence/v1'" in SOURCE
    assert "'runner-native-probe-evidence/v1'" in SOURCE
    assert "'DEC-054'" in SOURCE and "'DEC-051'" in SOURCE
    assert "Invoke-NativeMode 'c1'" in SOURCE


def test_real_observed_flow_is_ordered_before_validation_and_cleanup():
    start = SOURCE.index("if ($WithObserved) {\n        $null = Invoke-RunnerDocker")
    flow = SOURCE[start:SOURCE.index("    else {", start)]
    fragments = (
        "'candidate'", "Invoke-NativeMode 'observe'", "'policy'",
        "Invoke-NativeMode 'execute'", "Invoke-NativeMode 'confirm'",
        "Assert-RunnerSources", "validate_runner_observed_evidence.py",
        "$validationExitCode -ne 0", "$validation.status -cne 'PASS'",
        "'TESTS_PASSED_CLEANUP_PENDING'",
    )
    positions = [flow.index(fragment) for fragment in fragments]
    assert positions == sorted(positions)
    assert SOURCE.index("$result.status = 'PASS'") > SOURCE.index("'absence-check'")


def test_all_docker_calls_use_explicit_local_context_without_switching_global():
    assert "[ValidateSet('desktop-linux')]" in SOURCE
    assert "'npipe://'" in SOURCE
    calls = [line for line in SOURCE.splitlines() if re.search(r"& docker\s", line)]
    assert len(calls) == 3
    assert all("@dockerPrefix" in line for line in calls)
    assert "'context', 'use'" not in SOURCE
    assert "global_docker_context_changed = $false" in SOURCE


def test_new_producers_gate_and_all_gateway_schemas_are_hashed_in_snapshot():
    for name in (
        "runner_observed_native.py", "runner_observed_fixture.py", "runner_observed_gateway.py",
        "operational_observation_transactions.py", "validate_runner_observed_evidence.py",
    ):
        assert "'" + ("scripts/" if name.startswith("validate_") else "odoo/probes/") + name + "'" in SOURCE
    assert "'odoo/addons/ap_security_executor' 'gateway/src'" in SOURCE
    assert "'Source drift during snapshot'" in SOURCE
    assert "$sourceHashes[$path]" in SOURCE
    assert "Assert-RunnerSources $sourceHashes (Get-RunnerSourceHashes)" in SOURCE


def test_roundtrip_does_not_promote_public_scientific_or_human_acceptance():
    start = SOURCE.index("schema_version = 'runner-observed-probe-evidence/v1'")
    result = SOURCE[start:SOURCE.index("    else {", start)]
    for fragment in (
        "public_c1_executor_opened = $false", "scientific_run = $false",
        "complete_scientific_snapshot = $false", "human_review_complete = $false",
        "external_provider_called = $false", "existing_lab_touched = $false",
    ):
        assert fragment in result
    assert "'--publish'" not in SOURCE and "'prune'" not in SOURCE
