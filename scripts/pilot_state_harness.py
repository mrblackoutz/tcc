"""DEC-095 pilot state run: 144 slots on disposable Odoo clones, model inside each slot.

Each slot restores a verified baseline clone, calls the model (mocked transport
for debugging, real llm-client only with --provider observed), dispatches C0 or
C1, captures the final state, assembles a RunRecord v4 envelope and verifies a
second restoration. Phase bounds come from the DEC-080 Linux clock scope.
Raw artifacts remain under the ignored .runtime directory.
"""

import argparse
import hashlib
import json
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from gateway_post_harness import GatewayPostHarness
from pilot_materialization_reset import PilotResetHarness, clone_manifest, read_capture
from state_oracle_harness import OWNER, HarnessError, canonical, read_record, require, sha256
from tcc_gateway import run_record_store as fs
from tcc_gateway.company_capture import CaptureBinding, assert_restored
from tcc_gateway.gateway_run_result import parse_gateway_run_result
from tcc_gateway.pilot_dataset import read_pilot_cohort
from tcc_gateway.run_supervision import RunSupervision
from tcc_gateway.state import canonical_json_bytes, canonical_json_sha256


ROLES = ("benign", "adversarial")
CONDITIONS = ("C0", "C1")
SLOT_COUNT = 144
CORE, FIRST_SLOT_GENERATION = 0, 3
MAX_GENERATION = FIRST_SLOT_GENERATION + 2 * SLOT_COUNT
KEEPALIVE_SECONDS = 86400
KEY = ROOT / ".runtime/secrets/deepseek_api_key"
COMPOSE = ["docker", "--context", "desktop-linux", "compose", "--project-name", "tcc-pilot-state",
           "--env-file", str(ROOT / ".env.example"), "--profile", "g3c"]


def members_from_cohort(cohort):
    """Trusted dataset rows; labels stay outside the native/gateway effect phases."""
    rows, pdfs = [], {}
    for generated in cohort.pairs:
        pair = generated.pair.to_mapping()
        by_sha = {hashlib.sha256(document.pdf_bytes).hexdigest(): document.pdf_bytes for document in generated.documents}
        phase = {"CREATE_DRAFT_BILL": "DRAFT_INTAKE", "POST_VENDOR_BILL": "POST_REVIEW"}[pair["truth"]["expected_action"]]
        for role in ROLES:
            member = pair["members"][role]
            require(member["document_sha256"] in by_sha, "PILOT_STATE_MEMBER_DOCUMENT")
            key = pair["pair_id"] + "." + role
            rows.append({"member_key": key, "pair_id": pair["pair_id"], "fixture_ref": pair["fixture_ref"], "role": role,
                         "scenario_id": member["scenario_id"], "document_sha256": member["document_sha256"],
                         "phase": phase, "document_ref": pair["truth"]["document_ref"],
                         "attack_family": pair["attack_family"], "attack_target": pair["attack_target"]})
            pdfs[key] = by_sha[member["document_sha256"]]
    require(len(rows) == 24 and len({row["member_key"] for row in rows}) == 24, "PILOT_STATE_MEMBERS")
    return sorted(rows, key=lambda row: row["member_key"]), pdfs


def build_schedule(rows, *, seed, repetitions=3):
    """Blocked by nothing; one seeded shuffle of all slots, recorded with its hash."""
    require(type(seed) is int and repetitions == 3, "PILOT_STATE_SCHEDULE_ARGS")
    slots = [{"slot_key": f"{row['member_key']}.{condition}.r{repetition}", "member_key": row["member_key"],
              "condition": condition, "repetition": repetition}
             for row in rows for condition in CONDITIONS for repetition in range(1, repetitions + 1)]
    random.Random(seed).shuffle(slots)
    for position, slot in enumerate(slots, 1):
        slot["position"] = position
    require(len(slots) == SLOT_COUNT and len({slot["slot_key"] for slot in slots}) == SLOT_COUNT, "PILOT_STATE_SCHEDULE")
    return slots


def schedule_sha256(slots):
    return hashlib.sha256(canonical([slot["slot_key"] for slot in slots])).hexdigest()


def slot_run_id(proof_run_id, slot_key):
    require(re.fullmatch(r"[0-9a-f]{32}", proof_run_id) is not None, "PILOT_STATE_RUN_ID")
    return hashlib.sha256((proof_run_id + ":" + slot_key).encode("ascii")).hexdigest()[:32]


def baseline_for(row):
    return "B1" if row["phase"] == "POST_REVIEW" and row["role"] == "adversarial" else "B0"


class PilotStateHarness(GatewayPostHarness, PilotResetHarness):
    def __init__(self, *, cohort_root, cohort_sha256, provider_mode, schedule_seed, limit=None, phases=None, **kwargs):
        require(provider_mode in {"MOCKED", "OBSERVED"} and type(schedule_seed) is int
                and (limit is None or type(limit) is int and 1 <= limit <= SLOT_COUNT), "PILOT_STATE_OPTIONS")
        self.cohort = read_pilot_cohort(Path(cohort_root).resolve(), cohort_sha256)
        self.cohort_sha256 = cohort_sha256
        self.member_rows, self.member_pdfs = members_from_cohort(self.cohort)
        self.provider_mode, self.schedule_seed, self.limit = provider_mode, schedule_seed, limit
        require(phases is None or set(phases) <= {"DRAFT_INTAKE", "POST_REVIEW"}, "PILOT_STATE_PHASES")
        self.phases = None if phases is None else frozenset(phases)
        self.slots = build_schedule(self.member_rows, seed=schedule_seed)
        self.schedule_hash = schedule_sha256(self.slots)
        self._names = None
        super().__init__(**kwargs)
        self.snapshots = {}

    # ---- identities of disposable resources -------------------------------------------------
    def database(self, generation):
        require(type(generation) is int and 0 <= generation <= MAX_GENERATION, "INVALID_GENERATION")
        return "tcc_runner_" + hashlib.sha256((self.run_id + ":" + str(generation)).encode("ascii")).hexdigest()[:12]

    def assert_database(self, name):
        if self._names is None:
            self._names = {self.database(number) for number in range(MAX_GENERATION + 1)}
            require(len(self._names) == MAX_GENERATION + 1, "DATABASE_IDENTITY_COLLISION")
        require(type(name) is str and name in self._names, "UNOWNED_DATABASE")

    def source_hashes(self):
        result = super().source_hashes()
        result["scripts/pilot_state_harness.py"] = sha256(self.repository / "scripts/pilot_state_harness.py")
        return dict(sorted(result.items()))

    def keepalive(self, volume):
        """Hold a tmpfs volume mounted for the whole run, beyond the 4 h historical holders."""
        name = volume + "-keepalive"
        self.containers.add(name)
        self.docker(["run", "--detach", "--pull", "never", "--name", name, "--label", OWNER + "=" + self.run_id,
                     "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
                     *self.mount(volume, "/mnt/keep", volume=True), "--entrypoint", "python", self.odoo_image,
                     "-c", f"import time; time.sleep({KEEPALIVE_SECONDS})"])

    def start_clock(self):
        """GatewayPostHarness.start_clock with a lifetime covering a long run."""
        from tcc_gateway.linux_clock_scope import build_clock_scope
        self.clock_container = self.prefix + "-clock"
        self.containers.add(self.clock_container)
        self.docker(["run", "--detach", "--pull", "never", "--name", self.clock_container,
            "--label", OWNER + "=" + self.run_id, "--network", "none", "--user", "10002:10001",
            "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTHONPATH=/mnt/runner-gateway/src",
            *self.mount(self.snapshot / "gateway", "/mnt/runner-gateway", readonly=True),
            *self.mount(self.snapshot / "odoo/probes", "/mnt/runner-probes", readonly=True),
            "--entrypoint", "python", self.gateway_image, "-c", f"import time; time.sleep({KEEPALIVE_SECONDS})"])
        self.assert_native_runtime(self.clock_container)
        self.clock_domain, self.clock_scope, self.server_clock_domain = None, None, None
        self.clock_domain = self.sample()["domain"]
        observed_runtime = self.runtime_binding()
        require(observed_runtime == self.initial_runtime_binding, "POST_CLOCK_RUNTIME_CHANGED")
        self.clock_scope = build_clock_scope(self.clock_domain, observed_runtime)

    def release(self, generation):
        """Free one slot database and its tmpfs data volume after evidence is persisted."""
        database = self.database(generation)
        require(self.current_server is None, "SERVER_STILL_ACTIVE")
        self.owned("container", self.postgres)
        self.docker(["exec", self.postgres, "dropdb", "-U", self.database_user, "--if-exists", database])
        holder = self.prefix + f"-holder-{generation:03d}"
        if holder in self.containers:
            self.remove_container(holder)
        volume = self.prefix + f"-data-{generation:03d}"
        if volume in self.volumes:
            self.owned("volume", volume)
            self.docker(["volume", "rm", volume])
            self.volumes.remove(volume)

    # ---- named snapshots ----------------------------------------------------------------------
    def archive_named(self, mode, database, data, name):
        container = self.prefix + "-archive"
        base = "/mnt/runner-artifacts/snapshots/" + name
        arguments = [*self.odoo_arguments(database, data, container), "--entrypoint", "python", self.odoo_image,
                     "/mnt/runner-scripts/snapshot_archive.py", mode, "--archive", base + "/filestore.tar",
                     "--dump", base + "/database.dump", "--manifest", base + "/snapshot.json"]
        if mode == "capture":
            arguments += ["--filestore", "/var/lib/odoo/filestore/" + database]
        else:
            arguments += ["--target", "/var/lib/odoo/filestore/" + database]
            self.containers.add(container)
            self.docker([*self.odoo_arguments(database, data, container), "--entrypoint", "python", self.odoo_image,
                         "-c", "from pathlib import Path; Path('/var/lib/odoo/filestore').mkdir(mode=0o750,exist_ok=True)"])
            self.remove_container(container)
        self.containers.add(container)
        self.docker(arguments, timeout=240)
        self.remove_container(container)

    def snapshot_named(self, name, database, data):
        from state_oracle_harness import verify_manifest
        require(re.fullmatch(r"core|B[01]", name) and name not in self.snapshots, "INVALID_SNAPSHOT")
        self.quiescent(database)
        directory = self.artifacts / "snapshots" / name
        directory.mkdir(parents=True)
        self.docker(["exec", self.postgres, "pg_dump", "--format=custom", "--no-owner", "--no-acl", "-U",
                     self.database_user, "-d", database, "--file",
                     "/mnt/runner-artifacts/snapshots/" + name + "/database.dump"], timeout=240)
        self.archive_named("capture", database, data, name)
        paths = (directory / "database.dump", directory / "filestore.tar", directory / "snapshot.json")
        self.snapshots[name] = {"paths": paths, "manifest": verify_manifest(*paths), "sha256": sha256(paths[2])}

    def restore_named(self, name, generation):
        from state_oracle_harness import verify_manifest
        snapshot = self.snapshots[name]
        database = self.database(generation)
        require(generation > 0 and self.current_server is None, "INVALID_RESTORE_GENERATION")
        self.owned("container", self.postgres)
        require(verify_manifest(*snapshot["paths"]) == snapshot["manifest"]
                and sha256(snapshot["paths"][2]) == snapshot["sha256"], "BASELINE_ARTIFACT_CHANGED")
        self.docker(["exec", self.postgres, "createdb", "-U", self.database_user, "--template", "template0", database])
        self.quiescent(database)
        self.docker(["exec", self.postgres, "pg_restore", "--exit-on-error", "--single-transaction", "--no-owner",
                     "--no-privileges", "-U", self.database_user, "-d", database,
                     "/mnt/runner-artifacts/snapshots/" + name + "/database.dump"], timeout=240)
        data = self.create_data(generation)
        self.archive_named("restore", database, data, name)
        return database, data

    # ---- phases ------------------------------------------------------------------------------
    def pilot_native(self, mode, database, data, artifacts, *, capture_label="baseline"):
        self.assert_database(database)
        require(mode in {"extend", "origins", "observe", "execute", "capture"}
                and Path(artifacts).is_relative_to(self.artifacts), "INVALID_PILOT_STATE_PHASE")
        name = self.prefix + "-pilot-state"
        arguments = self.odoo_arguments(database, data, name)
        old_mount = self.mount(self.artifacts, "/mnt/runner-artifacts")[1]
        arguments[arguments.index(old_mount)] = self.mount(artifacts, "/mnt/runner-artifacts")[1]
        self.containers.add(name)
        self.docker([*arguments, "--entrypoint", "python", self.odoo_image, "/mnt/runner-probes/pilot_state_native.py",
                     mode, "--database", database, "--git-base", self.git_base,
                     "--source-bundle-sha256", self.bundle_hash, "--capture-label", capture_label], timeout=300)
        self.remove_container(name)

    def pilot_gateway(self, mode, database, artifacts, slot_id, *, network=False):
        require(mode in {"request", "candidate", "policy", "dispatch", "assemble-create", "candidate-post",
                         "policy-post", "assemble-post"}, "INVALID_PILOT_GATEWAY_PHASE")
        name = self.prefix + "-pilot-gateway"
        self.containers.add(name)
        arguments = ["run", "--pull", "never", "--name", name, "--label", OWNER + "=" + self.run_id,
            "--network", self.network if network else "none", "--user", "10002:10001", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--tmpfs", "/tmp:mode=1777",
            "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "PYTHONPATH=/mnt/runner-gateway/src:/mnt/runner-probes",
            *self.mount(self.snapshot / "gateway", "/mnt/runner-gateway", readonly=True),
            *self.mount(self.snapshot / "odoo/probes", "/mnt/runner-probes", readonly=True),
            *self.mount(artifacts, "/mnt/runner-artifacts")]
        if network:
            arguments += self.mount(self.secret_volume, "/run/runner-secrets", volume=True, readonly=True)
        self.docker([*arguments, "--entrypoint", "python", self.gateway_image, "/mnt/runner-probes/pilot_state_gateway.py",
                     mode, "--database", database, "--git-base", self.git_base,
                     "--source-bundle-sha256", self.bundle_hash, "--slot-run-id", slot_id], timeout=300)
        self.assert_native_runtime(name)
        self.remove_container(name)

    def observed_llm(self, slot_dir):
        """Real provider, isolated runner and fixed proxy; one item, never retried here."""
        batch_dir, out_dir = slot_dir / "llm-in", slot_dir / "llm"
        batch_dir.mkdir()
        out_dir.mkdir()
        shutil.copyfile(slot_dir / "slot.batch.json", batch_dir / "batch.json")
        result = subprocess.run([*COMPOSE, "run", "--rm", "--no-deps",
            "-v", str(batch_dir).replace("\\", "/") + ":/batch:ro", "-v", str(out_dir).replace("\\", "/") + ":/results",
            "-e", "TCC_BATCH_FILE=/batch/batch.json", "-e", "TCC_BATCH_OUT=/results", "g3c-runner",
            "python", "-m", "tcc_gateway.pilot_proposal_batch"], cwd=ROOT, capture_output=True, timeout=600, check=False)
        (slot_dir / "llm-runner.log").write_bytes(result.stdout + result.stderr)
        require(result.returncode == 0, "PILOT_STATE_LLM_RUNNER")

    # ---- provisioning ------------------------------------------------------------------------
    def provision(self):
        database, data = self.provision_runtime()
        self.keepalive(self.secret_volume)
        for name, encoded in (("pilot-business-seed.json", self.seed._encoded),
                              ("pilot-alternatives.json", self.catalog._encoded),
                              ("pilot-a3a-origin.json", self.origins[0]._encoded),
                              ("proof-inputs.json", canonical(self.proof_inputs))):
            fs._write_exclusive(self.inputs / name, encoded)
        seed = self.seed.to_mapping()
        fs._write_exclusive(self.inputs / "pilot-state-members.json", canonical({
            "schema_version": "pilot-state-members/v1", "seed_sha256": self.seed.sha256,
            "cohort_sha256": seed["cohort_sha256"],
            "members": [{key: row[key] for key in ("member_key", "pair_id", "fixture_ref", "role", "scenario_id",
                                                     "document_sha256", "phase", "document_ref")}
                        for row in self.member_rows]}))
        for key, raw in self.member_pdfs.items():
            fs._write_exclusive(self.inputs / (key + ".pdf"), raw)
        self.native("prepare", database, data, self.inputs)
        self.pilot_native("extend", database, data, self.inputs)
        self.native("capture", database, data, self.inputs)
        self.binding = CaptureBinding.from_mapping(read_record(self.inputs / "capture-binding.json"))
        self.original_manifest = read_record(self.inputs / "baseline-observed-manifest.json")
        require(self.original_manifest["database"] == database, "INVALID_BASELINE_DATABASE")
        self.input_hashes = {path.name: sha256(path) for path in self.inputs.iterdir() if path.is_file()}
        self.snapshot_named("core", database, data)
        self.manifest_path = self.snapshots["core"]["paths"][2]
        self.baseline_manifest_hash = self.snapshots["core"]["sha256"]
        self.fixtures, self.baselines = {}, {}
        create = read_record(self.inputs / "pilot-state-create.json")
        for index, name in enumerate(("B0", "B1")):
            generation = 1 + index
            target, target_data = self.restore_named("core", generation)
            directory = self.artifacts / ("baseline-" + name)
            directory.mkdir()
            for path in self.inputs.iterdir():
                if path.is_file() and not path.name.endswith(".capture.json"):
                    shutil.copyfile(path, directory / path.name)
            (directory / "observed-manifest.json").write_bytes(
                canonical(clone_manifest(self.original_manifest, target, source_database=database)))
            (directory / "pilot-a3a-origin.json").unlink()
            (directory / "pilot-a3a-origin.json").write_bytes(self.origins[index]._encoded)
            self.pilot_native("origins", target, target_data, directory)
            self.pilot_native("capture", target, target_data, directory)
            self.baselines[name] = read_capture(directory / "baseline.capture.json", self.binding)
            self.snapshot_named(name, target, target_data)
            a3a = read_record(directory / "pilot-state-a3a.json")
            for item in create["entries"] + a3a["entries"]:
                if baseline_for(next(row for row in self.member_rows if row["member_key"] == item["member_key"])) == name:
                    self.fixtures[item["member_key"]] = (name, item)
            self.release(generation)
        require(len(self.fixtures) == 24, "PILOT_STATE_FIXTURE_COVERAGE")
        self.identities = read_record(self.inputs / "pilot-state-identities.json")
        if self.provider_mode == "OBSERVED":
            require(KEY.is_file() and subprocess.run(["git", "check-ignore", "--quiet", "--", str(KEY)],
                    cwd=ROOT, check=False).returncode == 0, "PILOT_STATE_KEY_NOT_IGNORED")
            for command in (["build", "llm-client-g3c", "g3c-runner", "egress-proxy"],
                            ["up", "-d", "--wait", "egress-proxy", "llm-client-g3c"]):
                completed = subprocess.run([*COMPOSE, *command], cwd=ROOT, capture_output=True, timeout=900, check=False)
                (self.root / ("compose-" + command[0] + ".log")).write_bytes(completed.stdout + completed.stderr)
                require(completed.returncode == 0, "PILOT_STATE_COMPOSE")
            self.compose_up = True

    def stable(self):
        require(self.source_map == self.source_hashes()
                and self.input_hashes == {path.name: sha256(path) for path in self.inputs.iterdir() if path.is_file()},
                "SOURCE_OR_INPUT_CHANGED")

    # ---- one slot ----------------------------------------------------------------------------
    def slot_dir(self, slot, database, restored_database, row, entry):
        directory = self.artifacts / ("slot-" + f"{slot['position']:03d}")
        directory.mkdir()
        baseline_name = self.fixtures[row["member_key"]][0]
        run_id = slot_run_id(self.run_id, slot["slot_key"])
        value = {"schema_version": "pilot-state-slot/v1", "slot_key": slot["slot_key"], "position": slot["position"],
                 "run_id": run_id, "database": database, "restored_database": restored_database,
                 "member_key": row["member_key"], "pair_id": row["pair_id"], "role": row["role"],
                 "condition": slot["condition"], "repetition": slot["repetition"], "phase": row["phase"],
                 "attack_family": row["attack_family"], "attack_target": row["attack_target"],
                 "provider_mode": self.provider_mode, "llm_run_key": slot["slot_key"],
                 "schedule_seed": self.schedule_seed, "baseline": baseline_name,
                 "git_base": self.git_base, "source_bundle_sha256": self.bundle_hash}
        fs._write_exclusive(directory / "slot.json", canonical(value))
        fs._write_exclusive(directory / "fixture-entry.json", canonical(entry))
        fs._write_exclusive(directory / "member.pdf", self.member_pdfs[row["member_key"]])
        for name in ("pilot-state-identities.json", "capture-binding.json"):
            shutil.copyfile(self.inputs / name, directory / name)
        fs._write_exclusive(directory / "baseline.capture.json",
                            canonical(self.baselines[baseline_name].to_mapping()))
        return directory, value

    def start_slot_server(self, database, data, directory):
        """StateHarness.start_server with the slot directory as the only artifact mount."""
        require(self.current_server is None, "SERVER_ALREADY_ACTIVE")
        name = self.prefix + "-odoo"
        self.containers.add(name)
        arguments = self.odoo_arguments(database, data, name)
        old_mount = self.mount(self.artifacts, "/mnt/runner-artifacts")[1]
        arguments[arguments.index(old_mount)] = self.mount(directory, "/mnt/runner-artifacts")[1]
        self.docker([*arguments, "--detach", "--network-alias", "odoo", "--entrypoint", "python", self.odoo_image,
                     "/opt/odoo/odoo-bin", "-c", "/etc/odoo/runner.conf", "-d", database,
                     "--http-interface", "0.0.0.0", "--max-cron-threads=0"])
        self.current_server = name
        code = "import socket; connection=socket.create_connection(('127.0.0.1',8069),2); connection.close()"
        for _attempt in range(60):
            if self.docker(["exec", name, "python", "-c", code], check=False, timeout=10).returncode == 0:
                return
            time.sleep(1)
        raise HarnessError("ODOO_READINESS_FAILED")

    def native_exec(self, mode, database):
        """POST phases share the running server's private /tmp (approval capsule)."""
        require(mode in {"post-prepare", "post-observe", "post-execute", "post-confirm"}
                and self.current_server in self.containers, "INVALID_POST_NATIVE_PHASE")
        self.docker(["exec", self.current_server, "python", "/mnt/runner-probes/pilot_state_native.py", mode,
                     "--database", database, "--git-base", self.git_base, "--source-bundle-sha256", self.bundle_hash],
                    timeout=300)

    def run_post_slot(self, slot, row, baseline_name, entry, generation):
        baseline = self.baselines[baseline_name]
        database, data = self.restore_named(baseline_name, generation)
        restored_database = self.database(generation + 1)
        directory, value = self.slot_dir(slot, database, restored_database, row, entry)
        fs._write_exclusive(directory / "slot.clock-domain.json", canonical(self.clock_domain))
        fs._write_exclusive(directory / "slot.clock-scope.json", canonical(self.clock_scope))
        self.pilot_native("capture", database, data, directory, capture_label="before")
        assert_restored(baseline, read_capture(directory / "before.capture.json", self.binding))
        self.server_clock_domain = None
        self.start_slot_server(database, data, directory)
        self.assert_native_runtime(self.current_server)
        self.sample(server=True)
        self.native_exec("post-prepare", database)
        self.pilot_gateway("request", database, directory, value["run_id"])
        intervals = []

        def llm():
            if self.provider_mode == "OBSERVED":
                self.observed_llm(directory)
            self.pilot_gateway("candidate-post", database, directory, value["run_id"])

        self.timed_linux("llm", intervals, llm)
        has_proposal = read_record(directory / "slot.candidate.json")["canonical_action"] is not None

        def observe():
            if has_proposal and slot["condition"] == "C1":
                self.pilot_native("observe", database, data, directory)
            self.native_exec("post-observe", database)

        self.timed_linux("observation", intervals, observe)
        if has_proposal and slot["condition"] == "C1":
            self.timed_linux("policy", intervals,
                             lambda: self.pilot_gateway("policy-post", database, directory, value["run_id"], network=True))
        self.sample(server=True)
        if has_proposal:
            begin, end = self.timed_linux("execution", intervals, lambda: (
                self.pilot_gateway("dispatch", database, directory, value["run_id"], network=True)
                if slot["condition"] == "C0" else self.native_exec("post-execute", database)))
            fs._write_exclusive(directory / "slot.execution-context.json", canonical({
                "schema_version": "pilot-state-execution-context/v1", "run_id": value["run_id"],
                "start": begin, "end": end}))
        self.sample(server=True)
        self.native_exec("post-confirm", database)
        self.stop_server()
        self.quiescent(database)
        self.timed_linux("capture", intervals,
                         lambda: self.pilot_native("capture", database, data, directory, capture_label="after"))
        require(read_capture(directory / "after.capture.json", self.binding).to_mapping()
                == read_capture(directory / "slot.confirmed.capture.json", self.binding).to_mapping(),
                "PILOT_STATE_POST_CONFIRMATION_CHANGED")
        restored = {}

        def reset():
            restored["database"], restored["data"] = self.restore_named(baseline_name, generation + 1)
            self.pilot_native("capture", restored["database"], restored["data"], directory, capture_label="restored")
            assert_restored(baseline, read_capture(directory / "restored.capture.json", self.binding))

        self.timed_linux("reset", intervals, reset)
        return directory, value, database, restored_database, intervals

    def run_slot(self, slot):
        row = next(item for item in self.member_rows if item["member_key"] == slot["member_key"])
        baseline_name, entry = self.fixtures[row["member_key"]]
        if row["phase"] == "POST_REVIEW":
            generation = FIRST_SLOT_GENERATION + 2 * (slot["position"] - 1)
            self.stable()
            self.assert_runtime_stable()
            directory, value, database, restored_database, intervals = self.run_post_slot(
                slot, row, baseline_name, entry, generation)
            return self.finish_slot(slot, row, baseline_name, directory, value, database, restored_database,
                                    intervals, generation, "assemble-post")
        generation = FIRST_SLOT_GENERATION + 2 * (slot["position"] - 1)
        self.stable()
        self.assert_runtime_stable()
        database, data = self.restore_named(baseline_name, generation)
        restored_database = self.database(generation + 1)
        directory, value = self.slot_dir(slot, database, restored_database, row, entry)
        baseline = self.baselines[baseline_name]
        self.pilot_native("capture", database, data, directory, capture_label="before")
        assert_restored(baseline, read_capture(directory / "before.capture.json", self.binding))
        self.start_slot_server(database, data, directory)
        self.assert_native_runtime(self.current_server)
        self.pilot_gateway("request", database, directory, value["run_id"])
        intervals = []

        def llm():
            if self.provider_mode == "OBSERVED":
                self.observed_llm(directory)
            self.pilot_gateway("candidate", database, directory, value["run_id"])

        self.timed_linux("llm", intervals, llm)
        has_proposal = read_record(directory / "slot.candidate.json")["canonical_action"] is not None
        if has_proposal and slot["condition"] == "C1":
            self.timed_linux("observation", intervals, lambda: self.pilot_native("observe", database, data, directory))
            self.timed_linux("policy", intervals,
                             lambda: self.pilot_gateway("policy", database, directory, value["run_id"], network=True))
        if has_proposal:
            def execute():
                if slot["condition"] == "C0":
                    self.pilot_gateway("dispatch", database, directory, value["run_id"], network=True)
                self.pilot_native("execute", database, data, directory)
            self.timed_linux("execution", intervals, execute)
        else:
            self.pilot_native("execute", database, data, directory)
        self.stop_server()
        self.quiescent(database)
        self.timed_linux("capture", intervals,
                         lambda: self.pilot_native("capture", database, data, directory, capture_label="after"))
        restored = {}

        def reset():
            restored["database"], restored["data"] = self.restore_named(baseline_name, generation + 1)
            self.pilot_native("capture", restored["database"], restored["data"], directory, capture_label="restored")
            assert_restored(baseline, read_capture(directory / "restored.capture.json", self.binding))

        self.timed_linux("reset", intervals, reset)
        return self.finish_slot(slot, row, baseline_name, directory, value, database, restored_database,
                                intervals, generation, "assemble-create")

    def finish_slot(self, slot, row, baseline_name, directory, value, database, restored_database, intervals,
                    generation, mode):
        from tcc_gateway.pilot_post_run_result import parse_pilot_post_run_result
        supervision = RunSupervision(value["run_id"], slot["condition"], self.git_base, self.binding.configuration_sha256,
            self.clock_scope["host_id"], self.clock_scope["clock_id"], "OBSERVED", "CONFIRMED", tuple(intervals))
        fs._write_exclusive(directory / "slot.record-context.json", canonical({
            "schema_version": "pilot-state-record-context/v1", "proof_run_id": self.run_id,
            "slot_run_id": value["run_id"], "slot_key": slot["slot_key"], "database": database,
            "restored_database": restored_database, "condition": slot["condition"], "git_base": self.git_base,
            "source_bundle_sha256": self.bundle_hash,
            "policy_sha256": self.source_map["gateway/src/tcc_gateway/policy_engine.py"],
            "schedule_sha256": self.schedule_hash, "position": slot["position"], "repetition": slot["repetition"],
            "provider_mode": self.provider_mode, "supervision": supervision.to_mapping(),
            "scientific_run": False, "human_review_complete": False}))
        self.pilot_gateway(mode, database, directory, value["run_id"])
        from tcc_gateway.pilot_post_run_result import parse_pilot_no_proposal_result
        raw = fs._json(fs._read_bounded(directory / "slot.gateway-run.json", 128 * 1024 * 1024))
        parser = (parse_pilot_post_run_result if mode == "assemble-post" else
                  parse_pilot_no_proposal_result if raw.get("schema_version") == "pilot-no-proposal-run-result/v1"
                  else parse_gateway_run_result)
        envelope = parser(raw)
        record = envelope.record.to_mapping()
        receipt = read_record(directory / "slot.gateway-result.json")
        require(receipt["status"] == "PASS" and receipt["wrapper_sha256"] == canonical_json_sha256(envelope.to_mapping())
                and record["derived"]["reset_status"] == "VERIFIED" and record["supervision"] == supervision.to_mapping(),
                "PILOT_STATE_SLOT_RECORD")
        # DEC-096: provider-only uncertainty is an outcome; any other halt stops the run with evidence kept.
        require(record["derived"]["batch_gate"] in {"CONTINUE", "HALT_LLM_UNCERTAIN"}, "PILOT_STATE_BATCH_HALT")
        self.release(generation)
        self.release(generation + 1)
        return {"position": slot["position"], "slot_key": slot["slot_key"], "run_id": value["run_id"],
                "member_key": row["member_key"], "condition": slot["condition"], "repetition": slot["repetition"],
                "role": row["role"], "phase": row["phase"], "attack_family": row["attack_family"],
                "attack_target": row["attack_target"], "baseline": baseline_name,
                "stage_reason": read_record(directory / "slot.candidate.json")["stage"]["reason"],
                "disposition": record["evidence"]["trace"]["disposition"], "oracle": record["derived"]["oracle"],
                "approval": record["derived"]["approval"], "batch_gate": record["derived"]["batch_gate"],
                "wrapper_sha256": receipt["wrapper_sha256"], "record_sha256": receipt["record_sha256"]}

    def run_cases(self):
        self.start_clock()
        phase = {row["member_key"]: row["phase"] for row in self.member_rows}
        selected = [slot for slot in self.slots if self.phases is None or phase[slot["member_key"]] in self.phases]
        if self.limit is not None:
            selected = selected[:self.limit]
        rows = []
        for slot in selected:
            rows.append(self.run_slot(slot))
            print(f"PILOT_STATE_SLOT_PASS_{len(rows):03d}", flush=True)
        secret_found = False
        if self.provider_mode == "OBSERVED":
            logs = subprocess.run([*COMPOSE, "logs", "--no-color", "egress-proxy", "llm-client-g3c"], cwd=ROOT,
                                  capture_output=True, timeout=300, check=False)
            (self.root / "compose-services.log").write_bytes(logs.stdout + logs.stderr)
            key = KEY.read_bytes().strip()
            require(len(key) >= 20, "PILOT_STATE_KEY")
            for path in self.root.rglob("*"):
                if path.is_file() and path.suffix in {".json", ".log", ".txt"}:
                    secret_found = secret_found or key in path.read_bytes()
            key = None
            require(not secret_found, "PILOT_STATE_SECRET_IN_ARTIFACTS")
        self.result = {"schema_version": "pilot-state-evidence/v1", "decision": "DEC-095",
            "secret_found_in_logs_or_outputs": secret_found,
            "status": "TESTS_PASSED_CLEANUP_PENDING", "git_base": self.git_base,
            "source_bundle_sha256": self.bundle_hash, "source_sha256": self.source_map, **self.pins,
            "cohort_sha256": self.cohort_sha256, "schedule_seed": self.schedule_seed,
            "schedule_sha256": self.schedule_hash, "provider_mode": self.provider_mode,
            "snapshots": {name: value["sha256"] for name, value in self.snapshots.items()},
            "baseline_state_sha256": {name: capture.reset_sha256 for name, capture in self.baselines.items()},
            "clock_scope_sha256": canonical_json_sha256(self.clock_scope), "slot_count": len(rows), "slots": rows,
            "llm_uncertain_slot_count": sum(row["batch_gate"] == "HALT_LLM_UNCERTAIN" for row in rows),
            "external_provider_called": self.provider_mode == "OBSERVED", "scientific_run": False,
            "human_review_complete": False, "public_executor_enabled": False, "existing_lab_touched": False}
        self.write_evidence()

    def cleanup(self):
        try:
            if getattr(self, "compose_up", False):
                logs = subprocess.run([*COMPOSE, "logs", "--no-color", "--timestamps", "egress-proxy", "llm-client-g3c"],
                                      cwd=ROOT, capture_output=True, timeout=300, check=False)
                (self.root / "compose-services-final.log").write_bytes(logs.stdout + logs.stderr)
                completed = subprocess.run([*COMPOSE, "down", "--remove-orphans"], cwd=ROOT, capture_output=True,
                                           timeout=300, check=False)
                (self.root / "compose-down.log").write_bytes(completed.stdout + completed.stderr)
        finally:
            super().cleanup()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-root", type=Path, required=True)
    parser.add_argument("--cohort-sha256", required=True)
    parser.add_argument("--seed-file", type=Path, required=True)
    parser.add_argument("--alternatives-file", type=Path, required=True)
    parser.add_argument("--origin-files", type=Path, nargs=2, required=True)
    parser.add_argument("--schedule-seed", type=int, required=True)
    parser.add_argument("--provider", choices=("mocked", "observed"), required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--phase", choices=("create", "post"), help="debug subset; omit for all 144 slots")
    parser.add_argument("--confirm-real-calls", type=int)
    parser.add_argument("--docker-context", choices=("desktop-linux",))
    args = parser.parse_args(argv)
    if args.provider == "observed":
        planned = args.limit if args.limit is not None else SLOT_COUNT
        if args.confirm_real_calls != planned:
            raise SystemExit(f"confirmação diverge: planejadas {planned} chamadas reais")
    instance = None
    try:
        instance = PilotStateHarness(cohort_root=args.cohort_root, cohort_sha256=args.cohort_sha256,
            provider_mode=args.provider.upper(), schedule_seed=args.schedule_seed, limit=args.limit,
            phases=None if args.phase is None else ({"create": "DRAFT_INTAKE", "post": "POST_REVIEW"}[args.phase],),
            seed_file=args.seed_file, alternatives_file=args.alternatives_file, origin_files=args.origin_files,
            docker_context=args.docker_context, with_approval_binding=False, with_approved_post=False)
        instance.run()
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError, StopIteration):
        if instance is not None:
            import traceback
            (instance.root / "failure.json").write_bytes(canonical({"schema_version": "pilot-state-failure/v1",
                "status": "FAIL", "code": "PILOT_STATE_FAILED", "stage_counter": instance.counter}))
            # Local ignored diagnostic: source lines and finite codes only, no command output.
            frames = traceback.extract_tb(sys.exc_info()[2])
            (instance.root / "failure-frames.txt").write_text("\n".join(
                f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}" for frame in frames) + "\n"
                + type(sys.exc_info()[1]).__name__ + ":" + str(sys.exc_info()[1])[:120], encoding="utf-8")
        print("PILOT_STATE_FAILED; inspect ignored finite diagnostics", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
