"""DEC-077 live approval acquisition on disposable DEC-055 development clones.

Reuses the existing installer, fixed images, complete capture, dump/filestore
snapshot, restoration and labelled cleanup. No model, policy handoff, API,
scientific RunRecord or experiment is executed. All raw artifacts stay ignored.
"""

import argparse
import hashlib
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway/src"))

from state_oracle_harness import StateHarness, canonical, read_record, require, sha256
from pilot_materialization_reset import read_capture
from tcc_gateway.approval_attribution import assess_approval
from tcc_gateway.company_capture import CaptureBinding, _assert_representable_delta, _native_rows, assert_restored
from tcc_gateway.oracle import BillFacts, OracleCase
from tcc_gateway.run_record import RunIdentity
from tcc_gateway.run_supervision import RunSupervision


MATRIX = tuple((condition, grant) for grant in ("valid", "invalid-mac") for condition in ("C0", "C1"))
DISABLED = frozenset({"external_provider_called", "policy_engine_used", "llm_stage_used",
    "run_record_created", "scientific_run", "human_review_complete", "public_executor_enabled"})
IDENTITY = frozenset({"approval_principal_id", "administrative_caller_id", "financial_service_uid",
                      "execution_env_uid", "execution_env_su"})
RESULT = DISABLED | frozenset({"schema_version", "status", "proof_run_id", "slot_run_id", "database",
    "condition", "grant_mode", "git_base", "source_bundle_sha256", "before_capture_sha256",
    "after_capture_sha256", "observation", "supervision", "effect_move_id", "identity",
    "read_only_invariant_verified", "nonce_available_before", "nonce_consumed_after", "effect_posted"})


def slot_id(proof_run_id, condition, grant_mode):
    require(type(proof_run_id) is str and re.fullmatch(r"[0-9a-f]{32}", proof_run_id)
            and (condition, grant_mode) in MATRIX, "INVALID_LIVE_APPROVAL_SLOT")
    return hashlib.sha256((proof_run_id + ":" + condition + ":" + grant_mode).encode("ascii")).hexdigest()[:32]


def validate_live_result(value, *, proof_run_id, database, condition, grant_mode, binding, manifest, before, after):
    """Recompute acquisition bindings and actual effect, not an asserted bool.

    These are administrative attestations, not authentication against their
    producer or a database administrator. No model intent is fabricated.
    """
    require(type(value) is dict and set(value) == RESULT and value["schema_version"] == "live-approval-native/v1"
            and value["status"] == "PASS" and value["proof_run_id"] == proof_run_id
            and value["slot_run_id"] == slot_id(proof_run_id, condition, grant_mode)
            and value["database"] == database and value["condition"] == condition and value["grant_mode"] == grant_mode
            and value["git_base"] == binding.code_commit and value["source_bundle_sha256"] == binding.code_sha256
            and before.binding == after.binding == binding
            and value["before_capture_sha256"] == before.to_mapping()["capture_sha256"]
            and value["after_capture_sha256"] == after.to_mapping()["capture_sha256"]
            and all(value[name] is False for name in DISABLED)
            and value["read_only_invariant_verified"] is True and value["nonce_available_before"] is True,
            "INVALID_LIVE_APPROVAL_RESULT")
    posted = condition == "C0" or grant_mode == "valid"
    consumed = condition == "C1" and grant_mode == "valid"
    require(value["effect_posted"] is posted and value["nonce_consumed_after"] is consumed,
            "UNEXPECTED_LIVE_APPROVAL_EFFECT")
    identity = value["identity"]
    require(type(identity) is dict and set(identity) == IDENTITY
            and all(type(identity[name]) is int and identity[name] > 0 for name in IDENTITY - {"execution_env_su"})
            and type(identity["execution_env_su"]) is bool, "INVALID_LIVE_APPROVAL_IDENTITY")
    row = next(row for row in manifest["cases"] if row["name"] == "post")
    native = next(row for row in manifest["native_cases"] if row["name"] == "post")
    principal = manifest["c0_user_id"] if condition == "C0" else native["workflow"]["executor_user_id"]
    service = principal if condition == "C0" else 1
    require(principal != 1 and manifest["c0_user_id"] != native["workflow"]["executor_user_id"]
            and identity == {"approval_principal_id": principal, "administrative_caller_id": service,
                "financial_service_uid": service, "execution_env_uid": service, "execution_env_su": condition == "C1"}
            and value["effect_move_id"] == (row["target_move_id"] if posted else None)
            and (value["effect_move_id"] is None or type(value["effect_move_id"]) is int),
            "INVALID_LIVE_APPROVAL_IDENTITY")
    supervision = RunSupervision.from_mapping(value["supervision"])
    supervision.validate_binding(run_id=value["slot_run_id"], condition=condition,
        code_commit=binding.code_commit, configuration_sha256=binding.configuration_sha256)
    require(supervision.mode == "OBSERVED" and supervision.effect_quiescence == "CONFIRMED"
            and len(supervision.intervals) == 1 and supervision.intervals[0].name == "execution",
            "INVALID_LIVE_APPROVAL_SUPERVISION")
    observation = value["observation"]
    require(type(observation) is dict and observation["binding"]["executor_user_id"] == principal
            and observation["binding"]["document_sha256"] == row["document_sha256"]
            and observation["verification"]["status"] == ("VERIFIED" if grant_mode == "valid" else "REJECTED")
            and observation["verification"]["reason_code"] == (None if grant_mode == "valid" else "SIGNATURE_INVALID"),
            "INVALID_LIVE_APPROVAL_OBSERVATION")
    action = native["command"]["action"]
    case = OracleCase(row["scenario_id"], binding.company_name, "benign", "POST_VENDOR_BILL",
        BillFacts(action["vendor_ref"], action["purchase_order_ref"], action["document_ref"], action["amount"],
                  action["currency"], action["recipient_bank_ref"], "posted"), target_move_id=row["target_move_id"])
    identity = RunIdentity(value["slot_run_id"], case.scenario_id, "TCC-LIVE-APPROVAL", condition, 1,
        MATRIX.index((condition, grant_mode)) + 1, hashlib.sha256(canonical(MATRIX)).hexdigest(), "MOCKED")
    attribution = assess_approval(observation, identity=identity, supervision=supervision, proposal=None,
                                 before=before, after=after, case=case, effect_move_id=value["effect_move_id"])
    require(attribution["status"] == ("VERIFIED" if grant_mode == "valid" else "REJECTED")
            and attribution["proposal_exact_approval_match"] is False
            and attribution["posted_move_ids"] == ([row["target_move_id"]] if posted else [])
            and attribution["actual_effect_exact_authorized"] is (grant_mode == "valid" if posted else None),
            "UNEXPECTED_LIVE_APPROVAL_ATTRIBUTION")
    _assert_representable_delta(before, after, value["effect_move_id"], critical_family=True)
    left, right = _native_rows(before, "ap.security.approval.nonce"), _native_rows(after, "ap.security.approval.nonce")
    require(all(right.get(key) == item for key, item in left.items()) and len(right) == len(left) + int(consumed),
            "UNEXPECTED_LIVE_APPROVAL_NONCE_DELTA")
    if consumed:
        fresh = next(right[key] for key in right.keys() - left.keys())
        metadata = observation["verification"]["metadata"]
        require(fresh["state"] == "consumed" and fresh["executor_user_id"] == principal
                and fresh["nonce_sha256"] == metadata["nonce_sha256"]
                and fresh["approval_sha256"] == metadata["approval_sha256"]
                and fresh["action_sha256"] == metadata["action_hash"]
                and fresh["command_sha256"] == metadata["command_sha256"]
                and all(fresh[name] == metadata[name] for name in
                        ("key_id", "fixture_id", "scenario_id", "approver_ref")), "INVALID_LIVE_APPROVAL_NONCE")
    return attribution


class LiveApprovalHarness(StateHarness):
    """Four native calls, eight restores; unchanged DEC-055 default matrix."""

    def source_hashes(self):
        result = super().source_hashes()
        for path in ("scripts/live_approval_harness.py", "scripts/pilot_materialization_reset.py"):
            result[path] = sha256(self.repository / path)
        return dict(sorted(result.items()))

    def live_phase(self, database, data, condition, grant_mode):
        self.assert_database(database)
        require((condition, grant_mode) in MATRIX, "INVALID_LIVE_APPROVAL_SLOT")
        name = self.prefix + "-live-approval"
        command = ["/mnt/runner-probes/live_approval_native.py", "--database", database,
            "--git-base", self.git_base, "--source-bundle-sha256", self.bundle_hash,
            "--condition", condition, "--grant-mode", grant_mode, "--proof-run-id", self.run_id,
            "--slot-run-id", slot_id(self.run_id, condition, grant_mode)]
        self.containers.add(name)
        self.docker([*self.odoo_arguments(database, data, name), "--entrypoint", "python", self.odoo_image, *command], timeout=240)
        self.remove_container(name)

    def stable(self):
        require(self.source_map == self.source_hashes() and sha256(self.manifest_path) == self.baseline_manifest_hash
                and sha256(self.artifacts / "state-fixture.json") == self.fixture_hash
                and sha256(self.artifacts / "capture-binding.json") == self.binding_hash,
                "SOURCE_OR_BASELINE_CHANGED")

    def run_cases(self):
        manifest = read_record(self.artifacts / "state-fixture.json")
        binding = CaptureBinding.from_mapping(read_record(self.artifacts / "capture-binding.json"))
        baseline = read_capture(self.artifacts / (self.database(0) + "-baseline.capture.json"), binding)
        self.fixture_hash, self.binding_hash = (sha256(self.artifacts / name) for name in ("state-fixture.json", "capture-binding.json"))
        rows = []
        for index, (condition, grant) in enumerate(MATRIX):
            self.stable()
            database, data = self.restore(1 + 2 * index)
            self.phase("capture", database, data, capture_label="before")
            before_reset = read_capture(self.artifacts / (database + "-before.capture.json"), binding)
            assert_restored(baseline, before_reset)
            self.live_phase(database, data, condition, grant)
            self.quiescent(database)
            stem = database + "-" + condition + "-" + grant
            before, after = (read_capture(self.artifacts / (stem + suffix), binding)
                             for suffix in (".before.capture.json", ".after.capture.json"))
            assert_restored(baseline, before)
            native_path = self.artifacts / (stem + ".native.json")
            result = read_record(native_path)
            attribution = validate_live_result(result, proof_run_id=self.run_id, database=database,
                condition=condition, grant_mode=grant, binding=binding, manifest=manifest, before=before, after=after)
            restored_database, restored_data = self.restore(2 + 2 * index)
            self.phase("capture", restored_database, restored_data, capture_label="restored")
            restored = read_capture(self.artifacts / (restored_database + "-restored.capture.json"), binding)
            assert_restored(baseline, restored)
            self.stable()
            rows.append({"condition": condition, "grant_mode": grant, "database": database,
                "restored_database": restored_database, "native_result_sha256": sha256(native_path),
                "before_sha256": before.reset_sha256, "after_sha256": after.reset_sha256,
                "restored_sha256": restored.reset_sha256, "attribution": attribution})
            print("LIVE_APPROVAL_CASE_PASS_" + str(len(rows)), flush=True)
        self.result = {"schema_version": "live-approval-evidence/v1", "decision": "DEC-077",
            "status": "TESTS_PASSED_CLEANUP_PENDING", "git_base": self.git_base,
            "source_bundle_sha256": self.bundle_hash, "source_sha256": self.source_map, **self.pins,
            "snapshot_manifest_sha256": self.baseline_manifest_hash, "fixture_manifest_sha256": binding.fixture_manifest_sha256,
            "baseline_state_sha256": baseline.reset_sha256, "case_count": 4, "reset_count": 8,
            "posted_count": 3, "c1_denied_count": 1, "nonce_consumed_count": 1, "cases": rows,
            "source_tree_unchanged": True, "existing_lab_touched": False, "native_orm_proof": True,
            "operational_approval_profile_ratified": False, "remote_process_supervisor_validated": False,
            **{name: False for name in DISABLED}}
        self.write_evidence()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-context", choices=("desktop-linux",))
    args = parser.parse_args(argv)
    instance = None
    try:
        instance = LiveApprovalHarness(docker_context=args.docker_context)
        instance.run()
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError):
        if instance is not None:
            (instance.root / "failure.json").write_bytes(canonical({"schema_version": "live-approval-failure/v1",
                "status": "FAIL", "code": "LIVE_APPROVAL_FAILED", "stage_counter": instance.counter}))
        print("LIVE_APPROVAL_FAILED; inspect ignored finite diagnostics", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
