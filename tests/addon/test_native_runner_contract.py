"""Static safety gates of the disposable proof, not native effect evidence."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_harness_uses_internal_network_readonly_source_and_pinned_cached_images():
    source = (ROOT / "scripts/test_runner_native.ps1").read_text(encoding="utf-8")
    assert "'network', 'create', '--internal'" in source
    assert "'--pull', 'never'" in source
    assert "'image', 'inspect'" in source
    assert "Assert-RunnerSources $sourceHashes (Get-RunnerSourceHashes)" in source
    assert "source_tree_unchanged = $true" in source
    assert "'-p'" not in source and "'--publish'" not in source
    assert "'build'" not in source and "'pull'" not in source


def test_credential_volume_is_small_tmpfs_restricted_and_not_host_env_material():
    source = (ROOT / "scripts/test_runner_native.ps1").read_text(encoding="utf-8")
    assert "'type=tmpfs'" in source and "'device=tmpfs'" in source
    assert "'o=size=1048576,uid=10001,gid=10001,mode=0750'" in source
    assert "'--user', '10002:10001'" in source
    assert "target=/run/runner-secrets,readonly" in source
    assert "credential_transfer = 'labelled-restricted-docker-tmpfs'" in source
    assert ".runtime\\runner-native" in source
    assert "DeepSeek" not in source and "DEEPSEEK_API_KEY" not in source


def test_cleanup_validates_exact_names_ownership_and_absence():
    source = (ROOT / "scripts/test_runner_native.ps1").read_text(encoding="utf-8")
    assert "if ($Name -notin @($postgresName, $odooName, $gatewayName))" in source
    assert "$owner.Value -ne $runId" in source
    assert "'cleanup-final-containers.log'" in source
    assert "'cleanup-final-networks.log'" in source
    assert "'cleanup-final-volumes.log'" in source
    assert "'prune'" not in source and "Remove-Item" not in source


def test_evidence_requires_named_cases_not_only_positive_counts():
    source = (ROOT / "scripts/test_runner_native.ps1").read_text(encoding="utf-8")
    assert "'registered_fault_after_result_parent_commit'" in source
    assert "$proof.test_count -ne $expectedNames.Count" in source
    assert "($actualNames -join '|') -cne ($expectedNames -join '|')" in source
    assert "@($case.checks.PSObject.Properties).Count" in source
    assert "$case.status -ne 'PASS'" in source and "$check.Value -ne $true" in source


def test_failure_diagnostics_never_serialize_exception_values_or_traceback_lines():
    source = (ROOT / "odoo/probes/runner_native.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert "traceback.extract_tb" in calls
    assert "str(error)" not in source and "repr(error)" not in source
    assert "error.args" not in source and "frame.line" not in source
    assert "error.__dict__" not in source and "format_exc" not in source
    assert '"OTHER_RUNTIME_FAILURE"' in source and '"external-runtime"' in source


def test_native_gateway_uses_model_mock_but_real_odoo_client_and_never_calls_policy():
    source = (ROOT / "odoo/probes/runner_native_gateway.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert "httpx.MockTransport" in calls and "OdooJson2Client" in calls
    assert "dispatch_c0_llm_stage_v2" in calls
    assert "evaluate_policy" not in calls and "prepare_c1_draft_command_v2" not in calls
    assert '"provider_mocked": True' in source and '"external_provider_called": False' in source
    assert '"scientific_run": False' in source
