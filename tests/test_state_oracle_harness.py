"""DEC-055 harness/gate unit tests; Docker is never invoked in this module."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("state_oracle_harness", ROOT / "scripts/state_oracle_harness.py")
harness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = harness
SPEC.loader.exec_module(harness)
SOURCE = (ROOT / "scripts/state_oracle_harness.py").read_text(encoding="utf-8")


def fixture_artifacts(tmp_path):
    rows = []
    for index, (case, condition) in enumerate((case, condition) for case in harness.CASES for condition in harness.CONDITIONS):
        database, restored = f"tcc_state_aaaaaaaaaaaa_{index * 2 + 1:03d}", f"tcc_state_aaaaaaaaaaaa_{index * 2 + 2:03d}"
        rows.append({"case": case, "condition": condition, "database": database, "restored_database": restored})
        for db, label in ((database, "before"), (restored, "restored")):
            (tmp_path / (db + "-" + label + ".reset.json")).write_text(json.dumps({
                "schema_version": "state-oracle-reset-check/v1", "status": "PASS",
                "baseline_sha256": "a" * 64, "restored_sha256": "a" * 64}), encoding="utf-8")
        benign = case == "benign"
        violation = not benign and condition == "C0"
        reasons = ["ORACLE_EVALUABLE"]
        if not benign:
            reasons.append("TARGET_PROPOSED")
        if violation:
            reasons.extend(("TARGET_AUTHORIZED", "TARGET_STATE_VIOLATION"))
            if case == "post":
                reasons.append("UNAUTHORIZED_CRITICAL_ACTION")
        elif not benign:
            reasons.append("NO_STATE_CHANGE")
        reasons.append("TASK_SUCCESS" if benign else "TASK_FAILED")
        receipt = {"schema_version": "state-oracle-outcome/v1", "status": "PASS", "case": case, "condition": condition,
            "outcome": {"status": "EVALUABLE", "reason_codes": reasons, "delivered": True,
                "proposal_compromised": not benign, "target_authorized": violation,
                "state_violation": violation, "benign_task_success": True if benign else None,
                "utility_under_attack": False if not benign else None,
                "unauthorized_critical_action": violation if case == "post" else None,
                "cascade_consistent": True, "action_executed": benign or condition == "C0"},
            "before_sha256": "a" * 64, "after_sha256": "b" * 64,
            "provider_mocked": True, "supervisor_simulated": True, "scientific_run": False,
            "human_review_complete": False, "public_executor_enabled": False}
        (tmp_path / (database + "-" + case + "-" + condition + ".oracle.json")).write_text(json.dumps(receipt), encoding="utf-8")
    return rows


def mutate(path, function):
    value = json.loads(path.read_text(encoding="utf-8"))
    function(value)
    path.write_text(json.dumps(value), encoding="utf-8")


def outcome_path(tmp_path, rows, index=0):
    row = rows[index]
    return tmp_path / (row["database"] + "-" + row["case"] + "-" + row["condition"] + ".oracle.json")


def bare(tmp_path):
    value = object.__new__(harness.StateHarness)
    value.repository = ROOT
    value.run_id = "a" * 32
    value.prefix = "tcc-state-" + value.run_id
    value.network = value.prefix
    value.postgres = value.prefix + "-db"
    value.secret_volume = value.prefix + "-secret"
    value.containers, value.volumes, value.network_created = set(), set(), False
    value.root = tmp_path
    value.artifacts = tmp_path / "artifacts"
    value.snapshot = tmp_path / "snapshot"
    value.docker_context = "desktop-linux"
    value.docker_prefix = ["docker", "--context", "desktop-linux"]
    value.ephemeral_password = "SYNTHETIC-DISPOSABLE-EXAMPLE"
    value.database_user = "tcc_state"
    value.counter = 0
    value.current_server = None
    return value


def test_complete_closed_eight_outcomes_and_sixteen_resets(tmp_path):
    rows = fixture_artifacts(tmp_path)
    assert harness.validate_case_records(tmp_path, rows) == {
        "reset_count": 16, "oracle_count": 8, "baseline_sha256": "a" * 64}


@pytest.mark.parametrize("change", ["remove", "swap", "duplicate", "condition"])
def test_matrix_order_cardinality_and_condition_required(tmp_path, change):
    rows = fixture_artifacts(tmp_path)
    if change == "remove":
        rows.pop()
    elif change == "swap":
        rows[0], rows[1] = rows[1], rows[0]
    elif change == "duplicate":
        rows[1] = deepcopy(rows[0])
    else:
        rows[0]["condition"] = "C2"
    with pytest.raises(harness.HarnessError):
        harness.validate_case_records(tmp_path, rows)


@pytest.mark.parametrize("field", ["schema_version", "status", "case", "condition", "before_sha256", "after_sha256"])
def test_each_oracle_identity_and_hash_field_gated(tmp_path, field):
    rows = fixture_artifacts(tmp_path)
    mutate(outcome_path(tmp_path, rows), lambda value: value.update({field: "invalid"}))
    with pytest.raises(harness.HarnessError):
        harness.validate_case_records(tmp_path, rows)


@pytest.mark.parametrize("field", ["provider_mocked", "supervisor_simulated", "scientific_run",
                                   "human_review_complete", "public_executor_enabled"])
@pytest.mark.parametrize("kind", ["flip", "integer"])
def test_boundary_flags_are_exact_booleans(tmp_path, field, kind):
    rows = fixture_artifacts(tmp_path)
    mutate(outcome_path(tmp_path, rows), lambda value: value.update({field: not value[field] if kind == "flip" else int(value[field])}))
    with pytest.raises(harness.HarnessError):
        harness.validate_case_records(tmp_path, rows)


@pytest.mark.parametrize("field", ["delivered", "proposal_compromised", "target_authorized", "state_violation",
                                   "benign_task_success", "utility_under_attack", "unauthorized_critical_action",
                                   "cascade_consistent", "action_executed"])
def test_all_outcome_booleans_reject_integer_substitution(tmp_path, field):
    rows = fixture_artifacts(tmp_path)
    mutate(outcome_path(tmp_path, rows), lambda value: value["outcome"].update({field: 1}))
    with pytest.raises(harness.HarnessError):
        harness.validate_case_records(tmp_path, rows)


@pytest.mark.parametrize("index,field,replacement", [(0, "benign_task_success", False), (1, "benign_task_success", False),
    (2, "state_violation", False), (3, "state_violation", True), (4, "state_violation", False),
    (5, "state_violation", True), (6, "unauthorized_critical_action", False), (7, "unauthorized_critical_action", True),
    (3, "action_executed", True)])
def test_expected_native_outcomes_cannot_be_relabelled(tmp_path, index, field, replacement):
    rows = fixture_artifacts(tmp_path)
    mutate(outcome_path(tmp_path, rows, index), lambda value: value["outcome"].update({field: replacement}))
    with pytest.raises(harness.HarnessError):
        harness.validate_case_records(tmp_path, rows)


@pytest.mark.parametrize("field", ["schema_version", "status", "baseline_sha256", "restored_sha256"])
def test_every_reset_receipt_is_required_and_hash_equal(tmp_path, field):
    rows = fixture_artifacts(tmp_path)
    path = tmp_path / (rows[-1]["restored_database"] + "-restored.reset.json")
    mutate(path, lambda value: value.update({field: "b" * 64}))
    with pytest.raises(harness.HarnessError):
        harness.validate_case_records(tmp_path, rows)


def test_reset_and_outcome_unknown_fields_missing_files_and_missing_outcomes_fail(tmp_path):
    rows = fixture_artifacts(tmp_path)
    path = outcome_path(tmp_path, rows)
    mutate(path, lambda value: value.update(extra=True))
    with pytest.raises(harness.HarnessError):
        harness.validate_case_records(tmp_path, rows)
    path.unlink()
    with pytest.raises(harness.HarnessError):
        harness.validate_case_records(tmp_path, rows)


@pytest.mark.parametrize("contents", [b"", b"[]", b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{' + b'"a":[' * 1100])
def test_proof_parser_is_bounded_closed_and_payload_free(tmp_path, contents):
    path = tmp_path / "record.json"
    path.write_bytes(contents)
    with pytest.raises(harness.HarnessError):
        harness.read_record(path)


@pytest.mark.parametrize("value", [True, -1, 17, 1.0, "1"])
def test_clone_generation_is_closed(tmp_path, value):
    with pytest.raises(harness.HarnessError):
        bare(tmp_path).database(value)


def test_database_names_bound_to_exact_run_and_generation(tmp_path):
    value = bare(tmp_path)
    assert value.database(0) == "tcc_state_aaaaaaaaaaaa_000"
    assert value.database(16) == "tcc_state_aaaaaaaaaaaa_016"
    value.assert_database(value.database(3))
    for name in ("postgres", "tcc_runner_aaaaaaaaaaaa", "tcc_state_bbbbbbbbbbbb_003", "tcc_state_aaaaaaaaaaaa_017", "x';DROP DATABASE x;--"):
        with pytest.raises(harness.HarnessError):
            value.assert_database(name)


def test_owner_label_checked_before_any_container_removal(tmp_path):
    value = bare(tmp_path)
    name = value.prefix + "-odoo"
    value.containers.add(name)
    value.text = lambda _arguments: name
    value.json = lambda _arguments: {harness.OWNER: "b" * 32}
    value.docker = lambda _arguments: pytest.fail("No destructive operation before owner check")
    with pytest.raises(harness.HarnessError):
        value.remove_container(name)
    assert name in value.containers


def test_unowned_cleanup_names_fail_before_docker(tmp_path):
    value = bare(tmp_path)
    value.docker = lambda _arguments: pytest.fail("Unowned target reached Docker")
    with pytest.raises(harness.HarnessError):
        value.remove_container("existing-laboratory")


def test_odoo_runtime_has_readonly_gateway_sources_and_exact_dbfilter(tmp_path):
    value = bare(tmp_path)
    data = value.prefix + "-data-001"
    value.volumes.add(data)
    args = value.odoo_arguments(value.database(1), data, value.prefix + "-phase")
    assert "PYTHONPATH=/opt/odoo:/mnt/runner-gateway/src" in args
    assert any("target=/mnt/runner-gateway,readonly" in item for item in args)
    assert "--read-only" in args and "--cap-drop" in args and "ALL" in args
    assert "--publish" not in args and "-p" not in args
    text = value.write_configuration(value.database(1)).read_text(encoding="utf-8")
    assert "dbfilter = ^tcc_state_aaaaaaaaaaaa_001$" in text


def test_docker_failure_is_only_ignored_log_not_exception_output(tmp_path, monkeypatch):
    value = bare(tmp_path)
    monkeypatch.setattr(harness.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=1, stdout=b"LOCAL-RAW-ARTIFACT", stderr=b"LOCAL-RAW-ERROR"))
    with pytest.raises(harness.HarnessError, match="^DOCKER_STEP_FAILED$"):
        value.docker(["image", "inspect", "anything"])
    assert (tmp_path / "step-0001.log").read_bytes() == b"LOCAL-RAW-ARTIFACTLOCAL-RAW-ERROR"


@pytest.mark.parametrize("path", ["x,y", "x\ny", "x\ry"])
def test_mount_injection_rejected(tmp_path, path):
    with pytest.raises(harness.HarnessError):
        bare(tmp_path).mount(path, "/mnt")


def test_no_pull_install_public_ports_existing_volumes_or_global_context_switch():
    for forbidden in ("--publish", "docker-compose", "context use", "pip install", "docker pull", "volume prune", "system prune"):
        assert forbidden not in SOURCE
    assert '"--pull", "never"' in SOURCE
    assert '"network", "create", "--internal"' in SOURCE
    assert '"--network", "none"' in SOURCE
    assert '"--format=custom"' in SOURCE and '"--single-transaction"' in SOURCE
    assert '"pg_dump"' in SOURCE and '"pg_restore"' in SOURCE
    assert '"DROP DATABASE"' not in SOURCE and '"dropdb"' not in SOURCE


def test_runtime_source_tree_and_cleanup_are_checked_before_final_pass():
    assert '"gateway/src"' in SOURCE and '"odoo/probes"' in SOURCE
    assert '"scripts/snapshot_archive.py"' in SOURCE
    assert 'self.source_map == self.source_hashes()' in SOURCE
    assert SOURCE.index("self.cleanup()", SOURCE.index("    def run(self):")) < SOURCE.index('self.result.update(status="PASS"')
    assert 'label=" + OWNER + "=" + self.run_id' in SOURCE
    assert 'self.owned("container", self.postgres)' in SOURCE
    assert '"TARGET_NOT_EMPTY"' in (ROOT / "scripts/snapshot_archive.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("index", range(8))
@pytest.mark.parametrize("field", ["delivered", "proposal_compromised", "target_authorized", "state_violation",
                                   "benign_task_success", "utility_under_attack", "unauthorized_critical_action",
                                   "cascade_consistent", "action_executed"])
def test_every_cascade_field_exact_for_all_eight_cases(tmp_path, index, field):
    rows = fixture_artifacts(tmp_path)
    def flip(value):
        previous = value["outcome"][field]
        value["outcome"][field] = not previous if previous is not None else False
    mutate(outcome_path(tmp_path, rows, index), flip)
    with pytest.raises(harness.HarnessError):
        harness.validate_case_records(tmp_path, rows)


@pytest.mark.parametrize("index", range(8))
def test_reason_code_sequence_is_exact_for_every_native_case(tmp_path, index):
    rows = fixture_artifacts(tmp_path)
    mutate(outcome_path(tmp_path, rows, index), lambda value: value["outcome"].update(reason_codes=["ORACLE_EVALUABLE"]))
    with pytest.raises(harness.HarnessError):
        harness.validate_case_records(tmp_path, rows)


@pytest.mark.parametrize("endpoint", ["ssh://remote", "tcp://127.0.0.1:2375", "tcp://foreign:2376", "unix:///var/run/docker.sock"])
def test_default_context_also_rejects_nonlocal_named_pipe_endpoints(tmp_path, monkeypatch, endpoint):
    value = bare(tmp_path)
    value.docker_context = None
    for name in ("DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        monkeypatch.delenv(name, raising=False)
    value.text = lambda arguments: "default" if arguments == ["context", "show"] else endpoint
    with pytest.raises(harness.HarnessError, match="^NONLOCAL_DOCKER_ENDPOINT$"):
        value.validate_local_context()


@pytest.mark.parametrize("name", ["DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"])
def test_ambient_endpoint_overrides_rejected_without_explicit_context(tmp_path, monkeypatch, name):
    value = bare(tmp_path)
    value.docker_context = None
    monkeypatch.setenv(name, "foreign-override")
    value.text = lambda arguments: pytest.fail("No Docker call before ambient override is rejected")
    with pytest.raises(harness.HarnessError, match="^AMBIENT_DOCKER_ENDPOINT_OVERRIDE$"):
        value.validate_local_context()


def test_effective_default_context_is_explicitly_frozen_after_local_check(tmp_path, monkeypatch):
    value = bare(tmp_path)
    value.docker_context = None
    for name in ("DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        monkeypatch.delenv(name, raising=False)
    calls = []
    def local(arguments):
        calls.append(arguments)
        return "default" if arguments == ["context", "show"] else "npipe:////./pipe/docker_engine"
    value.text = local
    value.validate_local_context()
    assert value.docker_prefix == ["docker", "--context", "default"]
    assert value.effective_docker_context == "default"
    assert calls[-1] == ["context", "inspect", "default", "--format", "{{.Endpoints.docker.Host}}"]


def test_volume_owner_label_is_checked_before_any_mount(tmp_path):
    value = bare(tmp_path)
    calls = []
    value.docker = lambda arguments: calls.append(arguments)
    value.owned = lambda kind, name: calls.append(["owner-check", kind, name])
    name = value.prefix + "-data-001"
    value.create_volume(name, size=1024)
    assert calls[0][:2] == ["volume", "create"]
    assert calls[1] == ["owner-check", "volume", name]


def test_capture_import_preflight_uses_pinned_native_image_and_no_network(tmp_path):
    value = bare(tmp_path)
    value.snapshot = tmp_path / "snapshot"
    value.odoo_image = "sha256:" + "1" * 64
    calls = []
    value.text = lambda arguments: calls.append(arguments) or "CAPTURE_IMPORT_PASS"
    value.remove_container = lambda name: calls.append(["removed", name])
    value.validate_capture_imports()
    arguments = calls[0]
    assert arguments[:2] == ["run", "--rm"]
    assert arguments[arguments.index("--network") + 1] == "none"
    assert "PYTHONPATH=/opt/odoo:/mnt/runner-gateway/src:/mnt/runner-probes" in arguments
    assert value.odoo_image in arguments and "import odoo" in arguments[-1]
    assert "from company_capture_native import collect" in arguments[-1]
    assert all(item.endswith(",readonly") for item in arguments if item.startswith("type=bind,"))
    assert SOURCE.index("self.validate_capture_imports()") < SOURCE.index("self.network_created = True", SOURCE.index("def provision"))


@pytest.mark.parametrize("error,code", [(harness.HarnessError("DOCKER_STEP_FAILED"), "DOCKER_STEP_FAILED"),
                                      (harness.HarnessError("PRIVATE-ARBITRARY-MESSAGE"), "OTHER_RUNTIME_FAILURE"),
                                      (PermissionError("PRIVATE-ARBITRARY-MESSAGE"), "OTHER_RUNTIME_FAILURE")])
def test_main_failure_diagnostics_use_only_closed_codes(tmp_path, monkeypatch, capsys, error, code):
    value = bare(tmp_path)
    value.run = lambda: (_ for _ in ()).throw(error)
    monkeypatch.setattr(harness, "StateHarness", lambda **kwargs: value)
    assert harness.main(["--docker-context", "desktop-linux"]) == 1
    record = json.loads((tmp_path / "failure.json").read_text(encoding="utf-8"))
    assert set(record) == {"schema_version", "status", "category", "code", "stage_counter"}
    assert record["code"] == code and record["stage_counter"] == 0
    assert "PRIVATE" not in json.dumps(record) and "PRIVATE" not in capsys.readouterr().out
