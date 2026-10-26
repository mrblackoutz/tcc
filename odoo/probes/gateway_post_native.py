# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-079 one-attempt POST in the existing disposable server's private tmpfs.

Reference approval is issued before the candidate. It never gates C0. C1 uses
the gateway's actual REVIEW decision and original token, not the helper's fake
policy input hash. No key/token/nonce crosses the native process boundary.
"""

import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import logging
import os
from pathlib import Path
import re
import stat
import time
import traceback


MATRIX = tuple((variant, condition) for variant in ("exact", "tampered") for condition in ("C0", "C1"))


def require(value):
    if not value:
        raise ValueError("GATEWAY_POST_NATIVE_INVALID")


def slot_id(proof, variant, condition):
    require(type(proof) is str and re.fullmatch(r"[0-9a-f]{32}", proof) and (variant, condition) in MATRIX)
    return hashlib.sha256((proof + ":" + variant + ":" + condition).encode("ascii")).hexdigest()[:32]


def validate_options(args):
    for name, size in (("proof_run_id", 32), ("slot_run_id", 32), ("git_base", 40), ("source_bundle_sha256", 64)):
        value = getattr(args, name, None)
        require(type(value) is str and re.fullmatch(r"[0-9a-f]{%d}" % size, value))
    require((args.variant, args.condition) in MATRIX and args.mode in {"prepare", "observe", "execute", "confirm"}
            and args.slot_run_id == slot_id(args.proof_run_id, args.variant, args.condition)
            and args.config == "/etc/odoo/runner.conf" and args.artifacts == "/mnt/runner-artifacts"
            and args.secret_directory == "/run/runner-secrets" and args.case == "post")
    require(args.database == "tcc_state_" + args.proof_run_id[:12] + f"_{1 + 2 * MATRIX.index((args.variant, args.condition)):03d}")
    require(args.mode != "execute" or args.condition == "C1")


def sha(value):
    from c111_transactions import canonical
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def write_once(path, value):
    """Exclusive private artifact write, stdlib only in the pinned Odoo image.

    These sanitized artifacts are shared with the gateway; they are NOT the
    secret capsule, whose separate /tmp reader enforces POSIX 0600 and UID.
    Do not import the gateway store/jsonschema into this native process.
    """
    from c111_transactions import canonical
    from gateway_post_custody import _chain
    path = Path(path)
    require(path.is_absolute() and ".." not in path.parts
            and re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", path.name))
    chain = _chain(path.parent)
    raw = canonical(value)
    require(0 < len(raw) <= 2 * 1024 * 1024)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o640)
    with os.fdopen(descriptor, "wb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
        require(stream.write(raw) == len(raw))
        stream.flush()
        os.fsync(stream.fileno())
        written = os.fstat(stream.fileno())
        require(stat.S_ISREG(written.st_mode) and written.st_nlink == 1 and written.st_size == len(raw))
    require(_chain(path.parent) == chain)
    final = path.lstat()
    require(not stat.S_ISLNK(final.st_mode) and stat.S_ISREG(final.st_mode) and final.st_nlink == 1
            and (written.st_dev, written.st_ino, written.st_size) == (final.st_dev, final.st_ino, final.st_size))
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        require(stream.read(len(raw) + 1) == raw)
        observed = os.fstat(stream.fileno())
        require((observed.st_dev, observed.st_ino, observed.st_size) == (final.st_dev, final.st_ino, final.st_size)
                and stat.S_ISREG(observed.st_mode) and observed.st_nlink == 1)
    require(_chain(path.parent) == chain)


def load_scope(stem, domain):
    """Bind an independently measured physical producer to DEC-080's scope.

    Namespace identity is preserved; it is never renamed to the sampler's.
    The same-kernel/native-runtime premise is supplied by the trusted host.
    """
    from runner_observed_fixture import read_json
    from tcc_gateway.linux_clock_scope import parse_clock_scope, require_clock_in_scope
    scope = parse_clock_scope(read_json(stem.with_suffix(".clock-scope.json")))
    require_clock_in_scope(domain, scope)
    return scope


def loaded(args, registry):
    from state_oracle_native import loaded as load_fixture
    from live_approval_native import _identity, _origin
    from odoo.addons.ap_security_executor import registered_post
    from tcc_gateway.linux_clock_domain import measure_clock_domain
    result = load_fixture(registry, args)
    root, stem, manifest, binding, observer, scope, registration = result
    domain = measure_clock_domain()
    load_scope(stem, domain)
    principal = manifest["c0_user_id"] if args.condition == "C0" else scope.workflow.executor_user_id
    require(type(scope.result) is dict and scope.result["status"] == "CREATED"
            and scope.result["effect_applied"] is True)
    audit = observer.base.TrustedAuditContext(run_id="TCC-GATEWAY-POST-DEV", attempt_id=args.slot_run_id,
        code_commit=args.git_base, code_sha256="sha256:" + args.source_bundle_sha256,
        configuration_sha256="sha256:" + manifest["configuration_sha256"])
    with registry.cursor() as cr:
        cr.execute("SET TRANSACTION READ ONLY")
        observer.base.cursor_gate(cr)
        env = observer.base.env(cr)
        _identity(env, principal=principal, condition=args.condition, company_id=binding["company_id"])
        origin = _origin(env, registered_post=registered_post, resolved=registration, scope=scope,
                         audit=audit, target=scope.result["receipt"]["move_id"])
    return (*result, domain, principal, audit, origin)


def capsule_binding(args, manifest, binding, principal):
    return {"proof_run_id": args.proof_run_id, "run_id": args.slot_run_id, "database": args.database,
        "variant": args.variant, "condition": args.condition, "git_base": args.git_base,
        "source_bundle_sha256": args.source_bundle_sha256, "configuration_sha256": manifest["configuration_sha256"],
        "fixture_manifest_sha256": binding["fixture_manifest_sha256"], "company_id": binding["company_id"],
        "principal_id": principal}


def private(args, values):
    from gateway_post_custody import read_capsule
    from tcc_gateway.linux_clock_domain import require_same_domain
    from tcc_gateway.linux_clock_scope import require_same_scope
    root, stem, manifest, binding, observer, scope, registration, domain, principal, audit, origin = values
    saved = read_capsule(args.slot_run_id)
    require(saved["binding"] == capsule_binding(args, manifest, binding, principal)
            and saved["origin"] == origin and saved["create_result"] == scope.result)
    require_same_domain(domain, saved["preissued"]["clock_domain"])
    require_same_scope(load_scope(stem, domain), saved["preissued"]["clock_scope"])
    from odoo.addons.ap_security_executor.approval import ApprovalAuthority, ApprovalKey
    from odoo.addons.ap_security_executor.post_contracts import TrustedPostWorkflow
    scope.authority = ApprovalAuthority(**saved["authority"])
    scope.key = ApprovalKey(scope.authority.company_id, scope.authority.key_id, bytes.fromhex(saved["key_material"]))
    scope.post_command = deepcopy(saved["reference_command"])
    scope.post_workflow = TrustedPostWorkflow(draft=scope.workflow, target_move_id=origin["target_move_id"])
    return saved


def prepare(args, values):
    from gateway_post_custody import write_capsule
    from tcc_gateway.linux_clock_domain import sample_clock, require_same_domain
    from odoo.addons.ap_security_executor.approval import APPROVAL_DOMAIN, ApprovalAuthority, ApprovalKey
    from odoo.addons.ap_security_executor.post_contracts import TrustedPostWorkflow
    root, stem, manifest, binding, observer, scope, registration, domain, principal, audit, origin = values
    clock_scope = load_scope(stem, domain)
    require(not stem.with_suffix(".candidate.json").exists())
    base = observer.base
    base.ApprovalAuthority, base.ApprovalKey = ApprovalAuthority, ApprovalKey
    base.TrustedPostWorkflow, base.approval_domain = TrustedPostWorkflow, APPROVAL_DOMAIN
    base.prepare_post(scope, executor_user_id=principal)
    measured = sample_clock()
    require_same_domain(domain, measured["domain"])
    require(scope.authority.executor_user_id == principal and scope.authority.company_id == binding["company_id"]
            and scope.post_command["action"]["target_move_id"] == origin["target_move_id"])
    preissued = {"schema_version": "gateway-post-preissued/v1", "proof_run_id": args.proof_run_id,
        "run_id": args.slot_run_id, "database": args.database, "variant": args.variant, "condition": args.condition,
        "git_base": args.git_base, "source_bundle_sha256": args.source_bundle_sha256, "clock_domain": domain,
        "clock_scope": clock_scope,
        "preissued_at_ns": measured["monotonic_ns"], "preissued_at_utc": measured["utc"],
        "reference_action": deepcopy(scope.post_command["action"]),
        "reference_command_sha256": sha(scope.post_command), "approval_sha256": sha(scope.post_command["approval"]),
        "principal_id": principal, "original_create_authenticated": True}
    write_capsule(args.slot_run_id, {"schema_version": "gateway-post-capsule/v1",
        "binding": capsule_binding(args, manifest, binding, principal), "preissued": preissued,
        "origin": origin, "create_result": deepcopy(scope.result), "reference_command": deepcopy(scope.post_command),
        "authority": asdict(scope.authority), "key_material": scope.key.material.hex()})
    write_once(stem.with_suffix(".preissued.json"), preissued)


def observe(args, registry, values, saved):
    import odoo
    from approval_observation_native import begin_approval_observation
    from company_capture_native import collect
    from runner_observed_fixture import read_json
    from odoo.addons.ap_security_executor.approval import NONCE_DOMAIN
    from tcc_gateway.linux_clock_domain import measure_clock_domain, require_same_domain
    root, stem, manifest, binding, observer, scope, registration, domain, principal, audit, origin = values
    clock_scope = load_scope(stem, domain)
    nonce_hash = "sha256:" + hashlib.sha256(NONCE_DOMAIN + scope.authority.nonce.encode("utf-8")).hexdigest()
    filestore = Path(odoo.tools.config["data_dir"]) / "filestore" / args.database
    with registry.cursor() as cr:
        cr.execute("SET TRANSACTION READ ONLY")
        observer.base.cursor_gate(cr)
        env = observer.base.env(cr)
        before = collect(env, binding, filestore)
        require(before == read_json(root / (args.database + "-before.capture.json")))
        available = not env["ap.security.approval.nonce"].search_count([
            ("company_id", "=", binding["company_id"]), ("nonce_sha256", "=", nonce_hash)])
        observation = begin_approval_observation(binding={"run_id": args.slot_run_id, "condition": args.condition,
            "company_id": binding["company_id"], "executor_user_id": principal,
            "scenario_id": scope.workflow.scenario_id, "document_sha256": scope.workflow.document_sha256,
            "code_commit": args.git_base, "configuration_sha256": manifest["configuration_sha256"],
            "before_capture_sha256": before["capture_sha256"],
            "host_id": clock_scope["host_id"], "clock_id": clock_scope["clock_id"]},
            reference_action=saved["preissued"]["reference_action"], command=scope.post_command,
            authority=scope.authority, key=scope.key, now=datetime.now(timezone.utc), nonce_available=available,
            decision_window={key: scope.post_command["policy_decision"][key] for key in ("evaluated_at", "expires_at")})
        require(before == collect(env, binding, filestore))
    require_same_domain(domain, measure_clock_domain())
    write_once(stem.with_suffix(".approval-before.json"), observation)


def execute(args, registry, values, saved):
    from odoo import SUPERUSER_ID
    from runner_observed_fixture import read_json
    from odoo.addons.ap_security_executor import registered_post
    from tcc_gateway.linux_clock_domain import measure_clock_domain, require_same_domain
    root, stem, manifest, binding, observer, scope, registration, domain, principal, audit, origin = values
    clock_scope = load_scope(stem, domain)
    policy = read_json(stem.with_suffix(".post-policy.json"))
    candidate = read_json(stem.with_suffix(".candidate.json"))
    require(policy["status"] == policy["decision"]["decision"] in {"REVIEW", "DENY"}
            and policy["action_sha256"] == candidate["action_sha256"]
            and policy["policy_input_sha256"] == sha(policy["policy_input"])
            and policy["policy_input"]["action"] == candidate["canonical_action"])
    command, result, timing, execution_identity = None, None, None, None
    require_same_domain(domain, measure_clock_domain())
    if policy["status"] == "REVIEW":
        unsigned = policy["unsigned_command"]
        require(type(unsigned) is dict and set(unsigned) == {"schema_version", "action", "policy_decision", "idempotency_key"}
                and sha(unsigned) == "sha256:" + policy["unsigned_command_sha256"]
                and unsigned["policy_decision"] == policy["decision"]
                and unsigned["action"] == candidate["canonical_action"] == saved["preissued"]["reference_action"])
        command = dict(deepcopy(unsigned), approval=deepcopy(saved["reference_command"]["approval"]))
        scope.post_command = command
        with registry.cursor() as cr:
            observer.base.cursor_gate(cr)
            env = observer.base.env(cr)
            require(type(env.uid) is int and env.uid == SUPERUSER_ID and env.su is True)
            execution_identity = {"uid": env.uid, "su": env.su}
            started_ns, started_at = time.monotonic_ns(), datetime.now(timezone.utc)
            require(utc(policy["decision"]["evaluated_at"]) <= started_at < utc(policy["decision"]["expires_at"]))
            envelope = registered_post.post_registered_bill_audited(env, registration_id=registration.registration_id,
                expected_company_id=binding["company_id"], expected_executor_user_id=principal,
                expected_scenario_id=scope.workflow.scenario_id, command=deepcopy(command), audit=audit,
                document=scope.document, authority=scope.authority, key=scope.key)
            result = envelope["result"]
            observer.base.success(result, "POSTED")
            require(envelope["caller_transaction_pending"] is True and envelope["origin"] == origin)
            cr.commit()
            finished_at, finished_ns = datetime.now(timezone.utc), time.monotonic_ns()
        require(started_at <= finished_at < utc(policy["decision"]["expires_at"]))
        timing = {"started_ns": started_ns, "finished_ns": finished_ns,
            "call_started_at": started_at.isoformat().replace("+00:00", "Z"),
            "call_finished_at": finished_at.isoformat().replace("+00:00", "Z")}
    else:
        require(policy["unsigned_command"] is None and policy["unsigned_command_sha256"] is None)
    require_same_domain(domain, measure_clock_domain())
    write_once(stem.with_suffix(".post-executed.json"), {"schema_version": "gateway-post-executed/v1",
        "run_id": args.slot_run_id, "clock_domain": domain, "clock_scope": clock_scope, "policy_sha256": sha(policy),
        "effect_command_sha256": None if command is None else sha(command), "result": result, "timing": timing,
        "execution_identity": execution_identity})


def confirm(args, registry, values, saved):
    import odoo
    from odoo import SUPERUSER_ID
    from approval_observation_native import finish_approval_observation
    from company_capture_native import collect
    from live_approval_native import _identity
    from registered_post_transactions import RegisteredPostProbe
    from runner_observed_fixture import read_json
    from tcc_gateway.linux_clock_domain import measure_clock_domain, parse_clock_sample, require_same_domain
    from tcc_gateway.linux_clock_scope import require_clock_in_scope, require_same_scope
    from odoo.addons.ap_security_executor.approval import NONCE_DOMAIN
    root, stem, manifest, binding, observer, scope, registration, domain, principal, audit, origin = values
    clock_scope = load_scope(stem, domain)
    context = read_json(stem.with_suffix(".execution-context.json"))
    require(set(context) == {"schema_version", "run_id", "start", "end"}
            and context["schema_version"] == "gateway-post-execution-context/v1" and context["run_id"] == args.slot_run_id)
    start, end = (parse_clock_sample(context[name]) for name in ("start", "end"))
    require_same_domain(start["domain"], end["domain"])
    require_clock_in_scope(start["domain"], clock_scope)
    require_clock_in_scope(end["domain"], clock_scope)
    require(start["monotonic_ns"] <= end["monotonic_ns"] and utc(start["utc"]) <= utc(end["utc"]))
    observation = read_json(stem.with_suffix(".approval-before.json"))
    effect_hash = result = None
    deny_class = None
    policy_input_hash = decision_hash = unsigned_hash = None
    if args.condition == "C0":
        effect = read_json(stem.with_suffix(".dispatch.json"))
        require(effect == {"move_id": origin["target_move_id"], "methods": ["account.move.action_post"],
            "disposition": "ALLOW_EFFECTIVE", "receipt_id": None, "provider_mocked": True})
        posted, disposition = True, "ALLOW_EFFECTIVE"
        call = {"started_ns": start["monotonic_ns"], "finished_ns": end["monotonic_ns"],
            "call_started_at": start["utc"], "call_finished_at": end["utc"]}
    else:
        policy = read_json(stem.with_suffix(".post-policy.json"))
        executed = read_json(stem.with_suffix(".post-executed.json"))
        require(executed["schema_version"] == "gateway-post-executed/v1" and executed["run_id"] == args.slot_run_id
                and executed["policy_sha256"] == sha(policy))
        # Preserve the actual handoff witnessed by the executing process. A
        # consistent but foreign re-evaluated policy cannot replace it later.
        policy_input_hash = policy["policy_input_sha256"]
        decision_hash = sha(policy["decision"])
        unsigned_hash = None if policy["unsigned_command"] is None else sha(policy["unsigned_command"])
        require_same_domain(domain, executed["clock_domain"])
        require_same_scope(clock_scope, executed["clock_scope"])
        posted, result, call = policy["status"] == "REVIEW", executed["result"], executed["timing"]
        disposition = "REVIEW_REQUIRED" if posted else "DENY"
        deny_class, effect_hash = policy["decision"]["deny_class"], executed["effect_command_sha256"]
        require((posted and type(result) is dict and type(call) is dict and effect_hash is not None)
                or (not posted and result is None and call is None and effect_hash is None))
        require(executed["execution_identity"] == ({"uid": SUPERUSER_ID, "su": True} if posted else None))
    if call is not None:
        require(start["monotonic_ns"] <= call["started_ns"] <= call["finished_ns"] <= end["monotonic_ns"])
        observation = finish_approval_observation(observation, started_ns=call["started_ns"], finished_ns=call["finished_ns"],
            call_started_at=utc(call["call_started_at"]), call_finished_at=utc(call["call_finished_at"]))
    filestore = Path(odoo.tools.config["data_dir"]) / "filestore" / args.database
    with registry.cursor() as cr:
        cr.execute("SET TRANSACTION READ ONLY")
        observer.base.cursor_gate(cr)
        env = observer.base.env(cr)
        _identity(env, principal=principal, condition=args.condition, company_id=binding["company_id"])
        require(args.condition == "C0" or type(env.uid) is int and env.uid == SUPERUSER_ID and env.su is True)
        move = env["account.move"].browse(origin["target_move_id"]).exists()
        require(len(move) == 1 and move.state == ("posted" if posted else "draft")
                and env["account.payment"].search_count([("company_id", "=", binding["company_id"])]) == 0)
        meta = observation["verification"]["metadata"]
        nonce_hash = "sha256:" + hashlib.sha256(NONCE_DOMAIN + scope.authority.nonce.encode("utf-8")).hexdigest()
        nonces = env["ap.security.approval.nonce"].search([
            ("company_id", "=", binding["company_id"]), ("nonce_sha256", "=", nonce_hash)])
        consumed = posted and args.condition == "C1"
        require(len(nonces) == int(consumed) and (not consumed or nonces.state == "consumed"
                and nonces.command_sha256 == effect_hash and meta is not None
                and nonces.approval_sha256 == meta["approval_sha256"]))
        if args.condition == "C0":
            require(move.write_uid.id == principal)
        elif posted:
            scope.post_command = dict(deepcopy(policy["unsigned_command"]), approval=deepcopy(saved["reference_command"]["approval"]))
            from odoo.addons.ap_security_executor.draft_contracts import canonical_command_sha256
            checker = object.__new__(RegisteredPostProbe)
            checker.base, checker.command_hash = observer.base, canonical_command_sha256
            checker.verify_effect(env, scope, result, audit)
        after = collect(env, binding, filestore)
    require_same_domain(domain, measure_clock_domain())
    write_once(stem.with_suffix(".confirmed.capture.json"), after)
    service = principal if args.condition == "C0" else (SUPERUSER_ID if posted else None)
    evidence = {"schema_version": "gateway-post-native/v1", "status": "PASS", "proof_run_id": args.proof_run_id,
        "run_id": args.slot_run_id, "database": args.database, "variant": args.variant, "condition": args.condition,
        "git_base": args.git_base, "source_bundle_sha256": args.source_bundle_sha256, "clock_domain": domain,
        "clock_scope": clock_scope,
        "preissued": saved["preissued"], "observation": observation,
        "effect_move_id": origin["target_move_id"] if posted else None,
        "executed_methods": ["account.move.action_post"] if posted else [], "disposition": disposition,
        "deny_class": deny_class, "identity": {"approval_principal_id": principal,
            "administrative_caller_id": principal if args.condition == "C0" else SUPERUSER_ID,
            "financial_service_uid": service, "execution_env_uid": service,
            "execution_env_su": True if args.condition == "C1" and posted else None},
        "identity_source": "json2-write-uid-and-pinned-rpc" if args.condition == "C0" else "native-environment",
        "actual_policy_input_sha256": policy_input_hash, "actual_decision_sha256": decision_hash,
        "actual_unsigned_command_sha256": unsigned_hash,
        "effect_command_sha256": effect_hash, "nonce_consumed": consumed, "original_create_authenticated": True,
        "provider_mocked": True, "external_provider_called": False, "scientific_run": False,
        "human_review_complete": False, "public_executor_enabled": False}
    write_once(stem.with_suffix(".post-native.json"), evidence)


def run(args, registry):
    validate_options(args)
    values = loaded(args, registry)
    if args.mode == "prepare":
        prepare(args, values)
    else:
        saved = private(args, values)
        {"observe": observe, "execute": execute, "confirm": confirm}[args.mode](args, registry, values, saved)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "observe", "execute", "confirm"))
    for name in ("database", "git-base", "source-bundle-sha256", "proof-run-id", "slot-run-id"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--variant", choices=("exact", "tampered"), required=True)
    parser.add_argument("--condition", choices=("C0", "C1"), required=True)
    parser.add_argument("--config", default="/etc/odoo/runner.conf")
    parser.add_argument("--artifacts", default="/mnt/runner-artifacts")
    args = parser.parse_args(argv)
    args.case, args.secret_directory = "post", "/run/runner-secrets"
    logging.disable(logging.CRITICAL)
    try:
        validate_options(args)
        import odoo
        from odoo.orm.registry import Registry
        odoo.tools.config.parse_config(["-c", args.config, "-d", args.database, "--no-http"], setup_logging=False)
        run(args, Registry(args.database))
    except Exception as error:
        frames = [frame for frame in traceback.extract_tb(error.__traceback__) if Path(frame.filename).name == "gateway_post_native.py"]
        diagnostic = {"status": "FAIL", "code": "GATEWAY_POST_NATIVE_FAILED", "source_line": frames[-1].lineno if frames else None}
        try:
            validate_options(args)
            write_once(Path(args.artifacts) / (args.database + "-post-" + args.condition + "." + args.mode + ".failure.json"), diagnostic)
        except Exception:
            pass
        print("GATEWAY_POST_NATIVE_FAILED")
        return 1
    print("GATEWAY_POST_NATIVE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
