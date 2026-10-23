"""DEC-073 pilot preparation specialization of the existing snapshot harness.

Eight administrative CREATE origins, sixteen real restorations. DEC-074 adds
in-memory binding; DEC-075 adds opt-in private POST across native processes.
No provider or scientific execution. Concrete inputs/evidence remain ignored.
"""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway/src"))

from state_oracle_harness import StateHarness, HarnessError, canonical, read_record, require, sha256
from tcc_gateway import run_record_store as fs
from tcc_gateway.company_capture import MAX_CAPTURE_BYTES, CaptureBinding, parse_company_capture, assert_restored
from tcc_gateway.pilot_seed_contract import (
    MAX_SEED_BYTES, MAX_ALTERNATIVES_BYTES, PilotBusinessSeed, PilotAlternativeCatalog, validate_alternatives,
)
from tcc_gateway.pilot_a3a_origin_contract import MAX_ORIGIN_BYTES, PilotA3aOriginInput
from tcc_gateway.pilot_a3a_origin import verify_extraction


def validate_inputs(seed, catalog, origins):
    require(type(seed) is PilotBusinessSeed and type(catalog) is PilotAlternativeCatalog
            and type(origins) is tuple and len(origins) == 2
            and all(type(item) is PilotA3aOriginInput for item in origins), "INVALID_PILOT_INPUTS")
    business = seed.to_mapping()
    validate_alternatives(seed, catalog)
    first, second = (item.to_mapping() for item in origins)
    mirror = deepcopy(second)
    for row in mirror["fixtures"]:
        row["document"], row["other_document"] = row["other_document"], row["document"]
    require(first == mirror and origins[0].sha256 != origins[1].sha256, "INVALID_MEMBER_PAIR")
    rows = {row["fixture_ref"]: row for row in business["fixtures"]}
    for value in (first, second):
        require(value["seed_sha256"] == seed.sha256
                and all(value[name] == business[name] for name in ("cohort_sha256", "codebook_sha256")),
                "PILOT_INPUT_BINDING_MISMATCH")
        for row in value["fixtures"]:
            require(row["fixture_ref"] in rows and row["pair_sha256"] == rows[row["fixture_ref"]]["pair_sha256"]
                    and row["invoice_date_min"] <= rows[row["fixture_ref"]]["invoice_date"] <= row["invoice_date_max"],
                    "PILOT_FIXTURE_BINDING_MISMATCH")
    return {"schema_version": "pilot-materialization-reset-inputs/v1", "seed_sha256": seed.sha256,
        "catalog_sha256": catalog.sha256, "origin_input_sha256s": [item.sha256 for item in origins],
        "cohort_sha256": business["cohort_sha256"], "codebook_sha256": business["codebook_sha256"]}


def clone_manifest(original, target, *, source_database):
    require(type(original) is dict and original.get("database") == source_database
            and all(type(name) is str and re.fullmatch(r"tcc_runner_[0-9a-f]{12}", name)
                    for name in (source_database, target)) and target != source_database,
            "INVALID_CLONE_BINDING")
    result = deepcopy(original)
    result["database"] = target
    return result


def _read_private(path, cls, limit):
    path = Path(path)
    root, identity = fs._root(path.parent)
    fs._portable_component(path.name)
    result = cls(fs._read_bounded(path, limit))
    fs._verify_directory(root, identity)
    return result


def read_capture(path, binding):
    require(type(binding) is CaptureBinding, "INVALID_CAPTURE_BINDING")
    path = Path(path)
    root, identity = fs._root(path.parent)
    raw = fs._read_bounded(path, MAX_CAPTURE_BYTES)
    value = json.loads(raw, object_pairs_hook=fs._pairs,
                       parse_constant=lambda _value: require(False, "INVALID_CAPTURE"))
    fs._verify_directory(root, identity)
    return parse_company_capture(value, binding)


def validate_approval_result(result, *, fixture_ref, scenario_id, document_sha256,
                             origin_input_sha256, seed_sha256, cohort_sha256,
                             codebook_sha256, git_base, source_bundle_sha256):
    """Closed, hash-only native evidence; never promote a RunRecord boolean."""
    expected = dict(fixture_ref=fixture_ref, scenario_id=scenario_id, document_sha256=document_sha256,
        origin_input_sha256=origin_input_sha256, seed_sha256=seed_sha256, cohort_sha256=cohort_sha256,
        codebook_sha256=codebook_sha256, git_base=git_base, source_bundle_sha256=source_bundle_sha256)
    enabled = {"approval_generated", "approval_verified", "read_only_confirmed", "executor_identity_unchanged"}
    disabled = {"nonce_reserved", "post_executed", "external_provider_called", "scientific_run",
                "human_review_complete", "public_executor_enabled"}
    hashes = {"action_sha256", "approval_sha256", "nonce_sha256"}
    keys = set(expected) | enabled | disabled | hashes | {
        "schema_version", "status", "approval_count", "negative_check_count", "profile"}
    require(type(result) is dict and set(result) == keys
            and all(result[name] == value for name, value in expected.items())
            and result["schema_version"] == "pilot-a3a-approval-native/v1" and result["status"] == "PASS"
            and result["profile"] == "c111-development-utc-minus60-plus600/v1"
            and type(result["approval_count"]) is int and result["approval_count"] == 1
            and type(result["negative_check_count"]) is int and result["negative_check_count"] == 20
            and all(result[name] is True for name in enabled)
            and all(result[name] is False for name in disabled)
            and all(type(result[name]) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", result[name])
                    for name in hashes), "INVALID_PILOT_APPROVAL_RESULT")
    return deepcopy(result)


def validate_post_result(result, *, approval, database):
    """Closed private POST evidence, never a scientific approval attribution."""
    bindings = {name: approval[name] for name in ("fixture_ref", "scenario_id", "document_sha256",
        "origin_input_sha256", "seed_sha256", "cohort_sha256", "codebook_sha256", "git_base",
        "source_bundle_sha256", "action_sha256", "approval_sha256", "nonce_sha256", "profile")}
    bindings["database"] = database
    enabled = {"fresh_cursor_receipt_nonce_pdf_verified", "executor_identity_unchanged",
               "custody_between_phases", "nonce_consumed"}
    disabled = {"external_provider_called", "scientific_run", "human_review_complete",
                "public_executor_enabled", "policy_engine_used", "llm_stage_used", "gateway_handoff_performed"}
    counts = {"posted_count", "replay_count", "invalid_mac_rejections"}
    hashes = {"command_sha256", "origin_sha256"}
    require(type(result) is dict and set(result) == set(bindings) | enabled | disabled | counts | hashes | {
                "schema_version", "status"}
            and result["schema_version"] == "pilot-a3a-approved-post-native/v1" and result["status"] == "PASS"
            and all(result[name] == value for name, value in bindings.items())
            and all(type(result[name]) is int and result[name] == 1 for name in counts)
            and all(result[name] is True for name in enabled)
            and all(result[name] is False for name in disabled)
            and all(type(result[name]) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", result[name])
                    for name in hashes), "INVALID_PILOT_POST_RESULT")
    return deepcopy(result)


class PilotResetHarness(StateHarness):
    with_approval_binding = False
    with_approved_post = False

    def __init__(self, *, seed_file, alternatives_file, origin_files, with_approval_binding=False,
                 with_approved_post=False, **kwargs):
        require(type(with_approval_binding) is bool, "INVALID_APPROVAL_BINDING_MODE")
        require(type(with_approved_post) is bool and (not with_approved_post or with_approval_binding),
                "INVALID_APPROVED_POST_MODE")
        self.with_approval_binding = with_approval_binding
        self.with_approved_post = with_approved_post
        seed = _read_private(seed_file, PilotBusinessSeed, MAX_SEED_BYTES)
        catalog = _read_private(alternatives_file, PilotAlternativeCatalog, MAX_ALTERNATIVES_BYTES)
        require(type(origin_files) in (list, tuple) and len(origin_files) == 2, "INVALID_PILOT_INPUTS")
        origins = tuple(_read_private(path, PilotA3aOriginInput, MAX_ORIGIN_BYTES) for path in origin_files)
        self.proof_inputs = validate_inputs(seed, catalog, origins)
        for origin in origins:
            verify_extraction(origin)
        self.seed, self.catalog, self.origins = seed, catalog, origins
        super().__init__(**kwargs)
        require(len({self.database(index) for index in range(17)}) == 17, "DATABASE_IDENTITY_COLLISION")
        self.inputs = self.artifacts / "inputs"
        self.inputs.mkdir()

    def database(self, generation):
        require(type(generation) is int and 0 <= generation <= 16, "INVALID_GENERATION")
        suffix = hashlib.sha256((self.run_id + ":" + str(generation)).encode("ascii")).hexdigest()[:12]
        return "tcc_runner_" + suffix

    def source_hashes(self):
        result = super().source_hashes()
        result["scripts/pilot_materialization_reset.py"] = sha256(self.repository / "scripts/pilot_materialization_reset.py")
        return dict(sorted(result.items()))

    @property
    def private_approval_volume(self):
        return self.prefix + "-approval-private"

    def provision_approval_custody(self):
        require(self.with_approved_post is True and self.with_approval_binding is True,
                "INVALID_APPROVED_POST_MODE")
        self.create_volume(self.private_approval_volume, size=1_048_576)
        holder = self.prefix + "-approval-private-holder"
        self.containers.add(holder)
        # The generic harness cleanup removes the labelled holder last and
        # verifies absence before issuing PASS. No gateway or data mount here.
        from state_oracle_harness import OWNER
        self.docker(["run", "--detach", "--pull", "never", "--name", holder,
            "--label", OWNER + "=" + self.run_id, "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            *self.mount(self.private_approval_volume, "/run/pilot-approval-private", volume=True),
            "--entrypoint", "python", self.odoo_image, "-c", "import time; time.sleep(14400)"])

    def native(self, mode, database, data, artifacts, *, fixture_ref=None, capture_label="baseline"):
        self.assert_database(database)
        require(mode in {"prepare", "capture", "materialize", "approved-post"}
                and artifacts.is_relative_to(self.artifacts)
                and (fixture_ref is None or mode in {"materialize", "approved-post"})
                and (mode != "approved-post" or self.with_approved_post is True and fixture_ref is not None),
                "INVALID_PILOT_PHASE")
        name = self.prefix + "-pilot-phase"
        arguments = self.odoo_arguments(database, data, name)
        old_mount = self.mount(self.artifacts, "/mnt/runner-artifacts")[1]
        require(arguments.count(old_mount) == 1, "INVALID_PILOT_ARTIFACT_MOUNT")
        arguments[arguments.index(old_mount)] = self.mount(artifacts, "/mnt/runner-artifacts")[1]
        command = ["/mnt/runner-probes/pilot_reset_native.py", mode, "--database", database,
                   "--git-base", self.git_base, "--source-bundle-sha256", self.bundle_hash,
                   "--capture-label", capture_label]
        if fixture_ref is not None:
            command += ["--fixture-ref", fixture_ref]
        if mode in {"materialize", "approved-post"} and self.with_approval_binding:
            command.append("--with-approval-binding")
        if mode in {"materialize", "approved-post"} and self.with_approved_post:
            require(self.private_approval_volume in self.volumes, "MISSING_APPROVAL_CUSTODY")
            arguments += self.mount(self.private_approval_volume, "/run/pilot-approval-private", volume=True)
            command.append("--with-approved-post")
        self.containers.add(name)
        self.docker([*arguments, "--entrypoint", "python", self.odoo_image, *command], timeout=240)
        self.remove_container(name)

    def provision(self):
        database, data = self.provision_runtime()
        if self.with_approved_post:
            self.provision_approval_custody()
        for name, encoded in (("pilot-business-seed.json", self.seed._encoded),
                              ("pilot-alternatives.json", self.catalog._encoded),
                              ("pilot-a3a-origin.json", self.origins[0]._encoded),
                              ("proof-inputs.json", canonical(self.proof_inputs))):
            fs._write_exclusive(self.inputs / name, encoded)
        self.native("prepare", database, data, self.inputs)
        self.native("capture", database, data, self.inputs)
        self.binding = CaptureBinding.from_mapping(read_record(self.inputs / "capture-binding.json"))
        self.baseline = read_capture(self.inputs / "baseline.capture.json", self.binding)
        self.original_manifest = read_record(self.inputs / "baseline-observed-manifest.json")
        require(self.original_manifest["database"] == database, "INVALID_BASELINE_DATABASE")
        self.input_hashes = {path.name: sha256(path) for path in self.inputs.iterdir() if path.is_file()}
        self.snapshot_baseline(database, data)

    def stable(self):
        require(self.source_map == self.source_hashes()
                and sha256(self.manifest_path) == self.baseline_manifest_hash
                and self.input_hashes == {path.name: sha256(path) for path in self.inputs.iterdir() if path.is_file()},
                "SOURCE_OR_BASELINE_CHANGED")

    def clone_artifacts(self, database, fixture_ref, member_index):
        self.assert_database(database)
        require(type(member_index) is int and member_index in (0, 1)
                and fixture_ref in {row["fixture_ref"] for row in self.origins[member_index].to_mapping()["fixtures"]},
                "INVALID_PILOT_SELECTION")
        self.stable()
        output = self.artifacts / database
        output.mkdir()  # Never overwrite interrupted evidence.
        for path in self.inputs.iterdir():
            require(path.is_file() and not path.is_symlink(), "INVALID_BASELINE_INPUT")
            if path.name.endswith(".capture.json"):
                continue
            shutil.copyfile(path, output / path.name)
            require(sha256(path) == sha256(output / path.name), "CLONE_ARTIFACT_CHANGED")
        rewritten = clone_manifest(self.original_manifest, database, source_database=self.database(0))
        (output / "observed-manifest.json").write_bytes(canonical(rewritten))
        (output / "pilot-a3a-origin.json").write_bytes(self.origins[member_index]._encoded)
        snapshot = output / "baseline"
        snapshot.mkdir()
        shutil.copyfile(self.manifest_path, snapshot / "snapshot.json")
        require(sha256(snapshot / "snapshot.json") == self.baseline_manifest_hash, "BASELINE_ARTIFACT_CHANGED")
        link = {"schema_version": "pilot-reset-clone-binding/v1", "source_database": self.database(0),
            "target_database": database,
            "original_manifest_sha256": hashlib.sha256(canonical(self.original_manifest)).hexdigest(),
            "rewritten_manifest_sha256": hashlib.sha256(canonical(rewritten)).hexdigest(),
            "snapshot_manifest_sha256": self.baseline_manifest_hash, "seed_sha256": self.seed.sha256,
            "catalog_sha256": self.catalog.sha256, "origin_input_sha256": self.origins[member_index].sha256,
            "fixture_ref": fixture_ref}
        fs._write_exclusive(output / "pilot-reset-binding.json", canonical(link))
        return output

    def run_cases(self):
        cases = []
        for member_index, package in enumerate(self.origins):
            for source in package.to_mapping()["fixtures"]:
                self.stable()
                generation = 1 + len(cases) * 2
                database, data = self.restore(generation)
                artifacts = self.clone_artifacts(database, source["fixture_ref"], member_index)
                self.native("capture", database, data, artifacts, capture_label="before")
                before = read_capture(artifacts / "before.capture.json", self.binding)
                assert_restored(self.baseline, before)
                self.native("materialize", database, data, artifacts, fixture_ref=source["fixture_ref"])
                result = read_record(artifacts / "pilot-a3a-origin-result.json")
                require(result["schema_version"] == "pilot-a3a-origin-single-native/v1"
                        and result["status"] == "PASS" and result["fixture_ref"] == source["fixture_ref"]
                        and type(result["fixture_count"]) is int and result["fixture_count"] == 1
                        and type(result["negative_binding_checks"]) is int and result["negative_binding_checks"] == 3
                        and result["origin_input_sha256"] == package.sha256
                        and result["seed_sha256"] == self.seed.sha256
                        and result["git_base"] == self.git_base and result["source_bundle_sha256"] == self.bundle_hash,
                        "INVALID_UNIT_ORIGIN_RESULT")
                for flag in ("fresh_cursor_origins_verified", "previous_records_preserved", "executor_identity_unchanged", "private_pdf_verified"):
                    require(result[flag] is True, "INVALID_UNIT_ORIGIN_RESULT")
                for flag in ("scientific_run", "human_review_complete", "public_executor_enabled", "approval_generated", "post_executed"):
                    require(result[flag] is False, "INVALID_UNIT_ORIGIN_RESULT")
                approval = None
                if self.with_approval_binding:
                    approval = validate_approval_result(read_record(artifacts / "pilot-a3a-approval-result.json"),
                        fixture_ref=source["fixture_ref"], scenario_id=source["document"]["scenario_id"],
                        document_sha256=source["document"]["document_sha256"], origin_input_sha256=package.sha256,
                        seed_sha256=self.seed.sha256, cohort_sha256=self.proof_inputs["cohort_sha256"],
                        codebook_sha256=self.proof_inputs["codebook_sha256"], git_base=self.git_base,
                        source_bundle_sha256=self.bundle_hash)
                posted = None
                if self.with_approved_post:
                    self.native("approved-post", database, data, artifacts, fixture_ref=source["fixture_ref"])
                    posted = validate_post_result(read_record(artifacts / "pilot-a3a-approved-post-result.json"),
                                                  approval=approval, database=database)
                self.native("capture", database, data, artifacts, capture_label="after")
                after = read_capture(artifacts / "after.capture.json", self.binding)
                before_rows, after_rows = before.to_mapping()["records"], after.to_mapping()["records"]
                require(after.reset_sha256 != before.reset_sha256, "MATERIALIZATION_EFFECT_MISSING")
                for model in ("account.move", "ap.security.draft.receipt", "ap.security.audit.event", "ir.attachment"):
                    delta = {"ap.security.draft.receipt": 2, "ap.security.audit.event": 4}.get(model, 1) if posted else 1
                    require(len(after_rows[model]) == len(before_rows[model]) + delta, "MATERIALIZATION_EFFECT_SCOPE")
                if posted:
                    require(len(after_rows["ap.security.approval.nonce"]) == len(before_rows["ap.security.approval.nonce"]) + 1
                            and sum(row["state"] == "consumed" for row in after_rows["ap.security.approval.nonce"])
                                == sum(row["state"] == "consumed" for row in before_rows["ap.security.approval.nonce"]) + 1
                            and sum(row["state"] == "posted" for row in after_rows["account.move"])
                                == sum(row["state"] == "posted" for row in before_rows["account.move"]) + 1,
                            "APPROVED_POST_EFFECT_SCOPE")
                restored_database, restored_data = self.restore(generation + 1)
                reset_artifacts = self.clone_artifacts(restored_database, source["fixture_ref"], member_index)
                self.native("capture", restored_database, restored_data, reset_artifacts, capture_label="restored")
                restored = read_capture(reset_artifacts / "restored.capture.json", self.binding)
                assert_restored(self.baseline, restored)
                self.stable()
                cases.append({"member_index": member_index, "fixture_ref": source["fixture_ref"],
                    "database": database, "restored_database": restored_database,
                    "document_sha256": source["document"]["document_sha256"],
                    "scenario_id": source["document"]["scenario_id"],
                    "before_sha256": before.reset_sha256, "after_sha256": after.reset_sha256,
                    "restored_sha256": restored.reset_sha256, "negative_binding_checks": 3,
                    "origin_result_sha256": sha256(artifacts / "pilot-a3a-origin-result.json")})
                if approval is not None:
                    cases[-1]["approval"] = approval
                if posted is not None:
                    cases[-1]["post"] = posted
                print("PILOT_MATERIALIZATION_RESET_CASE_PASS_" + str(len(cases)), flush=True)
        require(len(cases) == 8 and len({row["document_sha256"] for row in cases}) == 8, "INCOMPLETE_PILOT_MATRIX")
        if self.with_approval_binding:
            for name in ("action_sha256", "approval_sha256", "nonce_sha256"):
                require(len({case["approval"][name] for case in cases}) == 8, "PILOT_APPROVAL_IDENTITY_REUSED")
        self.result = {"schema_version": "pilot-materialization-reset-evidence/v1", "decision": "DEC-073",
            "status": "TESTS_PASSED_CLEANUP_PENDING", "git_base": self.git_base,
            "source_bundle_sha256": self.bundle_hash, "source_sha256": self.source_map, **self.pins,
            "inputs": self.proof_inputs, "snapshot_manifest_sha256": self.baseline_manifest_hash,
            "baseline_state_sha256": self.baseline.reset_sha256, "case_count": 8, "restored_clone_count": 16,
            "reset_count": 16, "origin_count": 8, "negative_binding_checks": 24, "cases": cases,
            "source_tree_unchanged": True, "scientific_run": False, "human_review_complete": False,
            "external_provider_called": False, "existing_lab_touched": False, "public_executor_enabled": False,
            "approval_generated": False, "post_executed": False, "c0_c1_comparison_performed": False,
            "reset_mechanism": "postgres-custom-dump-and-full-filestore-new-clones"}
        if self.with_approval_binding:
            self.result.update(schema_version="pilot-materialization-approval-reset-evidence/v1", decision="DEC-074",
                approval_generated=True, approval_binding_count=8,
                approval_negative_check_count=sum(case["approval"]["negative_check_count"] for case in cases),
                nonce_reserved=False, approval_custody_between_phases=False,
                operational_approval_profile_ratified=False, run_record_approval_attribution_performed=False)
        if self.with_approved_post:
            self.result.update(schema_version="pilot-materialization-approved-post-reset-evidence/v1", decision="DEC-075",
                post_executed=True, nonce_reserved=True, approval_custody_between_phases=True,
                posted_count=sum(case["post"]["posted_count"] for case in cases),
                replay_count=sum(case["post"]["replay_count"] for case in cases),
                invalid_mac_rejections=sum(case["post"]["invalid_mac_rejections"] for case in cases),
                policy_engine_used=False, llm_stage_used=False, gateway_handoff_performed=False)
        self.write_evidence()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-file", type=Path, required=True)
    parser.add_argument("--alternatives-file", type=Path, required=True)
    parser.add_argument("--origin-files", type=Path, nargs=2, required=True)
    parser.add_argument("--docker-context", choices=("desktop-linux",))
    parser.add_argument("--with-approval-binding", action="store_true",
                        help="DEC-074 in-memory technical binding only; no POST or durable custody")
    parser.add_argument("--with-approved-post", action="store_true",
                        help="DEC-075 private tmpfs custody and administrative POST/replay; requires approval binding")
    args = parser.parse_args(argv)
    instance = None
    try:
        instance = PilotResetHarness(seed_file=args.seed_file, alternatives_file=args.alternatives_file,
                                    origin_files=args.origin_files, docker_context=args.docker_context,
                                    with_approval_binding=args.with_approval_binding, with_approved_post=args.with_approved_post)
        instance.run()
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError):
        if instance is not None:
            (instance.root / "failure.json").write_bytes(canonical({"schema_version": "pilot-reset-failure/v1",
                "status": "FAIL", "stage_counter": instance.counter, "code": "PILOT_RESET_FAILED"}))
        print("PILOT_MATERIALIZATION_RESET_FAILED; inspect ignored finite diagnostics", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
