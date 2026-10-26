"""DEC-079 host orchestration doubles, not Docker or financial evidence."""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "gateway/tests"))

import gateway_post_harness as harness
from tcc_gateway.linux_clock_domain import _from_fingerprints, _ZERO_OFFSETS_SHA256
from tcc_gateway.linux_clock_scope import build_clock_scope
from tcc_gateway.run_supervision import StageInterval


def domain():
    return _from_fingerprints("a" * 64, "b" * 64, _ZERO_OFFSETS_SHA256)


def sample(timestamp=100):
    return {"schema_version": "linux-clock-sample/v1", "domain": domain(), "monotonic_ns": timestamp,
            "utc": "2026-10-24T03:00:00.000000Z"}


def runtime():
    return {"schema_version": "local-linux-runtime/v1", "daemon_sha256": "1" * 64,
        "kernel_sha256": "2" * 64, "runtime": "runc", "endpoint_kind": "local-npipe",
        "os_type": "linux", "platform": "linux/amd64"}


def bare(tmp_path):
    instance = object.__new__(harness.GatewayPostHarness)
    instance.repository = ROOT
    instance.run_id, instance.prefix = "a" * 32, "tcc-state-" + "a" * 32
    instance.git_base, instance.bundle_hash = "b" * 40, "c" * 64
    instance.gateway_image = "sha256:" + "d" * 64
    instance.network, instance.secret_volume = instance.prefix + "-net", instance.prefix + "-secret"
    instance.snapshot, instance.artifacts = tmp_path / "snapshot", tmp_path / "artifacts"
    instance.current_server, instance.clock_container = instance.prefix + "-odoo", instance.prefix + "-clock"
    instance.containers = {instance.current_server, instance.clock_container}
    instance.clock_domain = domain()
    instance.clock_scope = build_clock_scope(domain(), runtime())
    instance.server_clock_domain = None
    instance.effective_docker_context = "desktop-linux"
    instance.initial_runtime_binding = runtime()
    return instance


@pytest.mark.parametrize("proof,variant,condition", [(True, "exact", "C0"), ("BAD", "exact", "C0"),
    ("a" * 32, "other", "C0"), ("a" * 32, "exact", "C2")])
def test_invalid_slot_is_rejected(proof, variant, condition):
    with pytest.raises(ValueError):
        harness.slot_id(proof, variant, condition)


def test_four_causal_slots_are_unique_and_stable():
    values = [harness.slot_id("a" * 32, variant, condition) for variant, condition in harness.MATRIX]
    assert len(set(values)) == 4
    assert values == [harness.slot_id("a" * 32, variant, condition) for variant, condition in harness.MATRIX]


def test_sampler_reads_real_linux_source_from_own_process(tmp_path):
    instance = bare(tmp_path)
    calls = []
    instance.json = lambda args: calls.append(args) or sample()
    assert instance.sample() == sample()
    assert instance.sample(server=True) == sample()
    assert calls == [["exec", name, "python", "/mnt/runner-probes/linux_clock_sample.py"]
                     for name in (instance.clock_container, instance.current_server)]


def test_distinct_server_namespace_is_accepted_in_zero_offset_scope_but_must_remain_stable(tmp_path):
    instance = bare(tmp_path)
    value = sample()
    value["domain"] = _from_fingerprints("a" * 64, "c" * 64, _ZERO_OFFSETS_SHA256)
    instance.json = lambda _args: value
    assert instance.sample(server=True) == value
    assert instance.server_clock_domain != instance.clock_domain
    value = sample()
    with pytest.raises(ValueError):
        instance.sample(server=True)
    assert instance.sample() == value


@pytest.mark.parametrize("changed", ["clock", "format", "missing-process"])
def test_sampler_never_falls_back_to_windows_or_an_unknown_domain(tmp_path, changed):
    instance = bare(tmp_path)
    value = sample()
    if changed == "clock":
        value["domain"] = _from_fingerprints("c" * 64, "b" * 64, _ZERO_OFFSETS_SHA256)
    elif changed == "format":
        value["monotonic_ns"] = True
    else:
        instance.containers.clear()
    instance.json = lambda _args: value
    with pytest.raises(ValueError):
        instance.sample()


def test_linux_bounds_causally_surround_actual_callback(tmp_path):
    instance = bare(tmp_path)
    calls, intervals = [], []
    samples = iter((sample(100), sample(300)))
    instance.sample = lambda: calls.append("sample") or next(samples)
    start, end = instance.timed_linux("execution", intervals, lambda: calls.append("actual callback"))
    assert calls == ["sample", "actual callback", "sample"]
    assert (start["monotonic_ns"], end["monotonic_ns"]) == (100, 300)
    assert intervals == [StageInterval("execution", 100, 300)]


def test_failed_callback_cannot_claim_completion_or_quiescence(tmp_path):
    instance = bare(tmp_path)
    instance.sample = lambda: sample()
    intervals = []

    def fail():
        raise RuntimeError("synthetic callback failure")

    with pytest.raises(RuntimeError):
        instance.timed_linux("execution", intervals, fail)
    assert intervals == []


@pytest.mark.parametrize("mode", ["candidate", "policy", "assemble"])
def test_gateway_mounts_no_approval_capsule_and_only_policy_gets_reader_key(tmp_path, mode):
    instance = bare(tmp_path)
    calls = []
    instance.docker = lambda args, **kwargs: calls.append((args, kwargs))
    instance.remove_container = lambda name: calls.append((name, "removed"))
    instance.assert_native_runtime = lambda name: calls.append((name, "runtime verified"))
    instance.gateway_post(mode, "tcc_state_aaaaaaaaaaaa_001", "exact", "C1")
    args, options = calls[0]
    mounts = [args[index + 1] for index, arg in enumerate(args) if arg == "--mount"]
    assert args[args.index("--network") + 1] == ("none" if mode == "assemble" else instance.network)
    assert any("/run/runner-secrets" in value for value in mounts) is (mode == "policy")
    assert not any("approval-private" in value or "docker.sock" in value or "filestore" in value for value in mounts)
    assert "--privileged" not in args and "--read-only" in args
    assert options == {"timeout": 240}
    assert calls[-2] == (instance.prefix + "-post-gateway", "runtime verified")
    assert calls[-1] == (instance.prefix + "-post-gateway", "removed")


def test_native_uses_existing_own_server_not_new_persistent_secret_mount(tmp_path):
    instance = bare(tmp_path)
    calls = []
    instance.docker = lambda args, **kwargs: calls.append((args, kwargs))
    instance.native_post("prepare", "tcc_state_aaaaaaaaaaaa_001", "exact", "C0")
    args, options = calls[0]
    assert args[:4] == ["exec", instance.current_server, "python", "/mnt/runner-probes/gateway_post_native.py"]
    assert args[4] == "prepare" and "--mount" not in args
    assert options == {"timeout": 240}
    assert not any("TOKEN" in value or "API_KEY" in value or "key_material" in value for value in args)


def test_sampler_container_has_only_readonly_sources_no_network_or_secrets(tmp_path):
    instance = bare(tmp_path)
    calls = []
    instance.docker = lambda args, **kwargs: calls.append(args)
    instance.sample = lambda: sample()
    instance.assert_native_runtime = lambda name: calls.append(["runtime verified", name])
    instance.runtime_binding = runtime
    instance.start_clock()
    args = calls[0]
    mounts = [args[index + 1] for index, arg in enumerate(args) if arg == "--mount"]
    assert len(mounts) == 2 and all(value.endswith(",readonly") for value in mounts)
    assert args[args.index("--network") + 1] == "none"
    assert not any("secret" in value or "docker.sock" in value for value in mounts)
    assert instance.clock_domain == domain()
    assert instance.clock_scope == build_clock_scope(domain(), runtime())
    assert calls[-1] == ["runtime verified", instance.clock_container]


def test_source_inventory_includes_all_transitive_harness_and_native_dependencies(tmp_path):
    instance = bare(tmp_path)
    inventory = instance.source_hashes()
    for path in ("scripts/gateway_post_harness.py", "scripts/gateway_record_harness.py",
                 "scripts/pilot_materialization_reset.py", "odoo/probes/gateway_post_native.py",
                 "odoo/probes/gateway_post_gateway.py", "odoo/probes/gateway_post_custody.py",
                 "odoo/probes/linux_clock_sample.py", "gateway/src/tcc_gateway/linux_clock_domain.py",
                 "gateway/src/tcc_gateway/linux_clock_scope.py",
                 "gateway/src/tcc_gateway/gateway_post_run_result.py"):
        assert inventory[path] == harness.sha256(ROOT / path)
    assert not any(".runtime" in path or ".claude" in path for path in inventory)


def boundary_double(variant="exact", condition="C0"):
    # Full real parsers and policy; captures/provider/clock are explicit test
    # doubles from the companion wrapper tests, never native proof artifacts.
    from test_gateway_post_run_result import result
    bundle = result(variant, condition)
    value, record = bundle.to_mapping(), bundle.record.to_mapping()
    native = value["native_evidence"]
    from tcc_gateway.company_capture import CaptureBinding, parse_company_capture
    from tcc_gateway.run_supervision import RunSupervision
    binding = CaptureBinding.from_mapping(record["evidence"]["captures"]["baseline"]["binding"])
    restored = "tcc_state_" + native["proof_run_id"][:12] + f"_{2 + 2 * harness.MATRIX.index((variant, condition)):03d}"
    receipt = {"schema_version": "gateway-post-record-native/v1", "status": "PASS",
        "proof_run_id": native["proof_run_id"], "run_id": native["run_id"], "database": native["database"],
        "restored_database": restored, "variant": variant, "condition": condition,
        "git_base": binding.code_commit, "source_bundle_sha256": binding.code_sha256,
        "record_version": "run-record/v4", "batch_gate": "CONTINUE",
        "record_sha256": harness.canonical_json_sha256(record), "wrapper_sha256": harness.canonical_json_sha256(value),
        "policy_applicable": condition == "C1", "provider_mocked": True, "external_provider_called": False,
        "scientific_run": False, "human_review_complete": False}
    arguments = {key: receipt[key] for key in ("proof_run_id", "database", "restored_database", "variant", "condition")}
    arguments.update(code_commit=binding.code_commit, code_sha256=binding.code_sha256,
        policy_sha256=record["policy_sha256"], domain=value["clock_domain"], expected_scope=value["clock_scope"],
        expected_supervision=RunSupervision.from_mapping(record["supervision"]),
        baseline=parse_company_capture(record["evidence"]["captures"]["baseline"], binding))
    return receipt, bundle, arguments


@pytest.mark.parametrize("variant,condition", harness.MATRIX)
def test_four_cells_revalidate_unchanged_v4_and_effect_not_just_compromised_proposal(variant, condition):
    receipt, bundle, arguments = boundary_double(variant, condition)
    record = harness.validate_result(receipt, bundle, **arguments)
    assert record == bundle.record.to_mapping()
    assert record["derived"]["oracle"]["state_violation"] is False


@pytest.mark.parametrize("field,bad", [("schema_version", "other/v1"), ("status", "FAIL"),
    ("proof_run_id", "0" * 32), ("run_id", "0" * 32), ("database", "OTHER"),
    ("restored_database", "OTHER"), ("variant", "tampered"), ("condition", "C1"),
    ("git_base", "0" * 40), ("source_bundle_sha256", "0" * 64),
    ("record_sha256", "0" * 64), ("wrapper_sha256", "0" * 64), ("record_version", "run-record/v3"),
    ("batch_gate", "HALT_APPROVAL"), ("policy_applicable", True), ("provider_mocked", False),
    ("external_provider_called", True), ("scientific_run", True), ("human_review_complete", True)])
def test_foreign_or_fabricated_receipt_cannot_pass_the_host(field, bad):
    receipt, bundle, arguments = boundary_double()
    receipt[field] = bad
    with pytest.raises(ValueError):
        harness.validate_result(receipt, bundle, **arguments)


@pytest.mark.parametrize("field", ["policy_applicable", "provider_mocked", "external_provider_called",
                                    "scientific_run", "human_review_complete"])
def test_integer_flags_do_not_replace_boolean_boundary_facts(field):
    receipt, bundle, arguments = boundary_double()
    receipt[field] = int(receipt[field])
    with pytest.raises(ValueError):
        harness.validate_result(receipt, bundle, **arguments)


@pytest.mark.parametrize("field", ["code_commit", "code_sha256", "policy_sha256", "domain", "expected_scope", "expected_supervision"])
def test_independent_host_binding_and_clock_evidence_must_match(field):
    receipt, bundle, arguments = boundary_double()
    if field == "domain":
        arguments[field] = _from_fingerprints("c" * 64, "b" * 64, _ZERO_OFFSETS_SHA256)
    elif field == "expected_scope":
        changed = dict(arguments[field]["runtime_binding"], daemon_sha256="0" * 64)
        arguments[field] = build_clock_scope(arguments["domain"], changed)
    elif field == "expected_supervision":
        from dataclasses import replace
        arguments[field] = replace(arguments[field], clock_id="OTHER-CLOCK")
    else:
        arguments[field] = "0" * (40 if field == "code_commit" else 64)
    with pytest.raises(ValueError):
        harness.validate_result(receipt, bundle, **arguments)


def test_receipt_is_closed_and_private_record_is_canonical(tmp_path):
    receipt, bundle, arguments = boundary_double()
    receipt["unexpected"] = "SYNTHETIC"
    with pytest.raises(ValueError):
        harness.validate_result(receipt, bundle, **arguments)
    root = tmp_path / ".runtime"
    root.mkdir()
    path = root / "private.gateway-run.json"
    path.write_bytes(harness.canonical_json_bytes(bundle.to_mapping()))
    assert harness.read_result(path).to_mapping() == bundle.to_mapping()
    path.write_bytes(harness.canonical_json_bytes(bundle.to_mapping()) + b"\n")
    with pytest.raises(ValueError):
        harness.read_result(path)


def runtime_metadata():
    return {"{{.Endpoints.docker.Host}}": "npipe:////./pipe/dockerDesktopLinuxEngine",
        "{{.ID}}": "SYNTHETIC-DAEMON", "{{.KernelVersion}}": "6.6.0-SYNTHETIC",
        "{{.OSType}}": "linux", "{{.Architecture}}": "x86_64"}


def test_runtime_binding_reads_only_selected_local_metadata_and_hashes_identity(tmp_path):
    instance = bare(tmp_path)
    metadata, calls = runtime_metadata(), []
    instance.text = lambda args: calls.append(args) or metadata[args[-1]]
    result = instance.runtime_binding()
    assert result["daemon_sha256"] == harness.hashlib.sha256(b"SYNTHETIC-DAEMON").hexdigest()
    assert result["kernel_sha256"] == harness.hashlib.sha256(b"6.6.0-SYNTHETIC").hexdigest()
    assert result["platform"] == "linux/amd64" and result["runtime"] == "runc"
    assert calls[0] == ["context", "inspect", "desktop-linux", "--format", "{{.Endpoints.docker.Host}}"]
    assert all(args[0] in {"context", "info"} and "--format" in args for args in calls)
    assert not any("{{json .}}" in args or "{{.Name}}" in args for args in calls)


@pytest.mark.parametrize("field,bad", [("{{.Endpoints.docker.Host}}", "tcp://synthetic.invalid:2376"),
    ("{{.Endpoints.docker.Host}}", "npipe:////remote-host/pipe/docker_engine"),
    ("{{.ID}}", ""), ("{{.ID}}", "wrong\nidentity"), ("{{.ID}}", "a" * 257),
    ("{{.KernelVersion}}", ""), ("{{.KernelVersion}}", "a" * 257),
    ("{{.OSType}}", "windows"), ("{{.Architecture}}", "aarch64")], ids=["remote", "remote-pipe", "empty-daemon",
    "newline-daemon", "oversized-daemon", "empty-kernel", "oversized-kernel", "nonlinux", "arm64"])
def test_runtime_binding_rejects_unsupported_or_missing_premise(tmp_path, field, bad):
    instance = bare(tmp_path)
    metadata = runtime_metadata()
    metadata[field] = bad
    instance.text = lambda args: metadata[args[-1]]
    with pytest.raises(ValueError):
        instance.runtime_binding()


@pytest.mark.parametrize("field", ["daemon_sha256", "kernel_sha256"])
def test_same_boot_cannot_mask_changed_daemon_or_kernel(tmp_path, field):
    instance = bare(tmp_path)
    changed = dict(runtime(), **{field: "3" * 64})
    instance.runtime_binding = lambda: changed
    with pytest.raises(ValueError):
        instance.assert_runtime_stable()
    instance.runtime_binding = runtime
    instance.assert_runtime_stable()


@pytest.mark.parametrize("actual", ["", "runsc", "kata", "io.containerd.kata.v2", "runc"])
def test_each_actual_producer_runtime_must_be_owned_and_native_runc(tmp_path, actual):
    instance = bare(tmp_path)
    calls = []
    instance.owned = lambda kind, name: calls.append((kind, name))
    instance.text = lambda args: calls.append(args) or actual
    if actual == "runc":
        instance.assert_native_runtime(instance.clock_container)
    else:
        with pytest.raises(ValueError):
            instance.assert_native_runtime(instance.clock_container)
    assert calls[0] == ("container", instance.clock_container)
    assert calls[1] == ["container", "inspect", "--format", "{{.HostConfig.Runtime}}", instance.clock_container]


def test_remote_named_pipe_stops_before_image_validation_or_any_provisioning(tmp_path):
    instance = bare(tmp_path)
    instance.docker_context = "desktop-linux"
    calls = []
    instance.text = lambda args: calls.append(args) or "npipe:////remote-host/pipe/docker_engine"
    with pytest.raises(ValueError):
        instance.validate_images()
    assert calls == [["context", "inspect", "desktop-linux", "--format", "{{.Endpoints.docker.Host}}"]] * 2
    assert not any(args[0] in {"run", "volume", "network", "image"} for args in calls)


def test_initial_daemon_binding_is_verified_again_when_clock_starts(tmp_path):
    instance = bare(tmp_path)
    instance.docker = lambda *args, **kwargs: None
    instance.assert_native_runtime = lambda _name: None
    instance.sample = lambda: sample()
    instance.runtime_binding = lambda: dict(runtime(), kernel_sha256="3" * 64)
    with pytest.raises(ValueError):
        instance.start_clock()
