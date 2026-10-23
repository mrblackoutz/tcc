# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-077 live, direct-ORM approval observation in disposable development clones.

An independently registered CREATE supplies the legitimate POST reference.
Its pre-issued grant remains in this one process; only a copy's MAC changes in
the negative cases. C0 observes the grant but never uses it as an execution
gate. This is neither a model run nor a public or gateway execution endpoint.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import secrets
import socket
import time
import traceback


VERSION = "live-approval-native/v1"


def _require(value):
    if not value:
        raise ValueError("LIVE_APPROVAL_NATIVE_INVALID")


def validate_options(args):
    """Validate before loading Odoo, a fixture, a key or an arbitrary path."""
    patterns = {"proof_run_id": r"[0-9a-f]{32}", "slot_run_id": r"[0-9a-f]{32}",
                "git_base": r"[0-9a-f]{40}", "source_bundle_sha256": r"[0-9a-f]{64}"}
    for name, pattern in patterns.items():
        value = getattr(args, name, None)
        _require(type(value) is str and re.fullmatch(pattern, value) is not None)
    _require(type(args.database) is str and re.fullmatch(
        r"tcc_state_" + args.proof_run_id[:12] + r"_[0-9]{3}", args.database) is not None)
    _require(type(args.condition) is str and args.condition in {"C0", "C1"}
             and type(args.grant_mode) is str and args.grant_mode in {"valid", "invalid-mac"}
             and args.case == "post" and args.config == "/etc/odoo/runner.conf"
             and args.artifacts == "/mnt/runner-artifacts"
             and args.secret_directory == "/run/runner-secrets")


def command_for_grant(command, grant_mode):
    """Never reissue, mutate the original grant, or change action arguments."""
    _require(type(grant_mode) is str and grant_mode in {"valid", "invalid-mac"})
    changed = deepcopy(command)
    signature = changed["approval"]["signature"]
    _require(type(signature) is str and re.fullmatch(r"hmac-sha256/v1:[0-9a-f]{64}", signature))
    if grant_mode == "invalid-mac":
        changed["approval"]["signature"] = signature[:-1] + ("0" if signature[-1] != "0" else "1")
    return changed


def _capture(registry, base, binding, filestore):
    from company_capture_native import collect
    with registry.cursor() as cr:
        cr.execute("SET TRANSACTION READ ONLY")
        base.cursor_gate(cr)
        value = collect(base.env(cr), binding, filestore)
    return value


def _identity(env, *, principal, condition, company_id):
    from odoo import SUPERUSER_ID, api
    from odoo.addons.ap_security_executor.identity import assert_executor_identity
    user = env["res.users"].browse(principal).exists()
    _require(len(user) == 1 and user.active and principal not in {
        SUPERUSER_ID, env.ref("base.user_admin").id}
        and user.company_id.id == company_id and user.company_ids.ids == [company_id])
    if condition == "C1":
        assert_executor_identity(env, user, company=env["res.company"].browse(company_id))
    else:
        actual = api.Environment(env.cr, principal, {
            "allowed_company_ids": [company_id], "force_company": company_id,
            "lang": "en_US", "tz": "UTC"}, su=False)
        _require(actual.uid == principal and actual.su is False
                 and actual.user.has_group("account.group_account_invoice")
                 and not actual.user.has_group("base.group_system")
                 and not actual.user.has_group("ap_security_executor.group_executor"))


def _origin(env, *, registered_post, resolved, scope, audit, target):
    """Authenticate the original returned CREATE against persisted receipt/event/PDF."""
    result = scope.result
    _require(type(result) is dict and result["status"] == "CREATED"
             and result["effect_applied"] is True and result["receipt"]["move_id"] == target)
    _workflow, origin = registered_post._origin(env, resolved, audit)
    _require(origin["target_move_id"] == target
             and origin["create_receipt_id"] == result["receipt"]["receipt_id"]
             and origin["create_event_id"] == result["audit_event"]["event_id"]
             and origin["create_event_sha256"] == result["audit_event"]["event_sha256"])
    event = env["ap.security.audit.event"].browse(origin["create_event_id"]).exists()
    _require(len(event) == 1 and event.attachment_id.raw == scope.document.raw
             and event.attachment_id.res_model == "account.move"
             and event.attachment_id.res_id == target and not event.attachment_id.public)
    return origin


def run(args, registry):
    validate_options(args)
    import odoo
    from odoo import SUPERUSER_ID, api
    from approval_observation_native import begin_approval_observation, finish_approval_observation
    from company_capture_native import collect
    from registered_post_transactions import RegisteredPostProbe
    from runner_observed_fixture import write_json
    from state_oracle_native import loaded
    from tcc_gateway.run_supervision import RunSupervision, StageInterval
    from odoo.addons.ap_security_executor import registered_post
    from odoo.addons.ap_security_executor.approval import (
        APPROVAL_DOMAIN, NONCE_DOMAIN, ApprovalAuthority, ApprovalKey)
    from odoo.addons.ap_security_executor.draft_contracts import canonical_command_sha256
    from odoo.addons.ap_security_executor.post_contracts import TrustedPostWorkflow

    root, _old_stem, manifest, binding, observer, scope, resolved = loaded(registry, args)
    base = observer.base
    row = next(row for row in manifest["cases"] if row["name"] == "post")
    target = row["target_move_id"]
    _require(type(target) is int and target > 0 and type(scope.result) is dict)
    principal = manifest["c0_user_id"] if args.condition == "C0" else scope.workflow.executor_user_id
    _require(type(principal) is int and principal > 0 and binding["company_id"] == base.company_id
             and binding["configuration_sha256"] == manifest["configuration_sha256"])
    audit = base.TrustedAuditContext(run_id="TCC-LIVE-APPROVAL-DEV", attempt_id=args.slot_run_id,
        code_commit=args.git_base, code_sha256="sha256:" + args.source_bundle_sha256,
        configuration_sha256="sha256:" + manifest["configuration_sha256"])
    filestore = Path(odoo.tools.config["data_dir"]) / "filestore" / args.database
    stem = root / (args.database + "-" + args.condition + "-" + args.grant_mode)

    with registry.cursor() as cr:
        cr.execute("SET TRANSACTION READ ONLY")
        base.cursor_gate(cr)
        env = base.env(cr)
        _identity(env, principal=principal, condition=args.condition, company_id=base.company_id)
        origin = _origin(env, registered_post=registered_post, resolved=resolved, scope=scope, audit=audit, target=target)
        _require(env["account.move"].browse(target).state == "draft")
    # The authentic CREATE already exists: prepare_post must never take its
    # fallback CREATE branch. The explicit principal is selected before issue.
    base.ApprovalAuthority, base.ApprovalKey = ApprovalAuthority, ApprovalKey
    base.TrustedPostWorkflow, base.approval_domain = TrustedPostWorkflow, APPROVAL_DOMAIN
    base.prepare_post(scope, executor_user_id=principal)
    _require(scope.authority.executor_user_id == principal
             and scope.authority.company_id == base.company_id
             and scope.post_command["action"]["target_move_id"] == target)
    command = command_for_grant(scope.post_command, args.grant_mode)
    nonce_sha256 = "sha256:" + hashlib.sha256(NONCE_DOMAIN + scope.authority.nonce.encode("utf-8")).hexdigest()
    host_id = "native-" + hashlib.sha256(socket.gethostname().encode("utf-8")).hexdigest()[:24]
    clock_id = "monotonic-" + secrets.token_hex(16)
    with registry.cursor() as cr:
        cr.execute("SET TRANSACTION READ ONLY")
        base.cursor_gate(cr)
        env = base.env(cr)
        _identity(env, principal=principal, condition=args.condition, company_id=base.company_id)
        before = collect(env, binding, filestore)
        nonce_available = not env["ap.security.approval.nonce"].search_count([
            ("company_id", "=", base.company_id), ("nonce_sha256", "=", nonce_sha256)])
        _require(nonce_available is True)
        observation = begin_approval_observation(binding={
            "run_id": args.slot_run_id, "condition": args.condition, "company_id": base.company_id,
            "executor_user_id": principal, "scenario_id": scope.workflow.scenario_id,
            "document_sha256": scope.workflow.document_sha256, "code_commit": args.git_base,
            "configuration_sha256": manifest["configuration_sha256"],
            "before_capture_sha256": before["capture_sha256"], "host_id": host_id, "clock_id": clock_id},
            reference_action=deepcopy(scope.post_command["action"]), command=command,
            authority=scope.authority, key=scope.key, now=datetime.now(timezone.utc),
            nonce_available=nonce_available,
            decision_window={name: command["policy_decision"][name] for name in ("evaluated_at", "expires_at")})
        # SQL READ ONLY is the primary invariant; identical captures also cover
        # the complete fixture projection and filestore around pure observation.
        _require(before == collect(env, binding, filestore))
    write_json(stem.with_suffix(".before.capture.json"), before)

    posted = None
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        if args.condition == "C0":
            execution_env = api.Environment(cr, principal, {
                "allowed_company_ids": [base.company_id], "force_company": base.company_id,
                "lang": "en_US", "tz": "UTC"}, su=False)
            _require(execution_env.uid == principal and execution_env.su is False)
        else:
            execution_env = base.env(cr)
            _require(execution_env.uid == SUPERUSER_ID and execution_env.su is True)
        actual_uid, actual_su = execution_env.uid, execution_env.su
        started_ns = time.monotonic_ns()
        call_started_at = datetime.now(timezone.utc)
        if args.condition == "C0":
            # Deliberately no branch on grant mode, verifier or nonce state.
            execution_env["account.move"].browse(target).action_post()
        else:
            envelope = registered_post.post_registered_bill_audited(execution_env,
                registration_id=resolved.registration_id, expected_company_id=base.company_id,
                expected_executor_user_id=scope.workflow.executor_user_id,
                expected_scenario_id=scope.workflow.scenario_id, command=deepcopy(command), audit=audit,
                document=scope.document, authority=scope.authority, key=scope.key)
            _require(envelope["caller_transaction_pending"] is True and envelope["origin"] == origin)
            posted = envelope["result"]
        cr.commit()
        call_finished_at = datetime.now(timezone.utc)
        finished_ns = time.monotonic_ns()
    observation = finish_approval_observation(observation, call_started_at=call_started_at,
        call_finished_at=call_finished_at, started_ns=started_ns, finished_ns=finished_ns)

    with registry.cursor() as cr:
        cr.execute("SET TRANSACTION READ ONLY")
        base.cursor_gate(cr)
        env = base.env(cr)
        _identity(env, principal=principal, condition=args.condition, company_id=base.company_id)
        _require(_origin(env, registered_post=registered_post, resolved=resolved, scope=scope,
                         audit=audit, target=target) == origin)
        move = env["account.move"].browse(target).exists()
        expected_posted = args.condition == "C0" or args.grant_mode == "valid"
        _require(len(move) == 1 and move.state == ("posted" if expected_posted else "draft")
                 and env["account.payment"].search_count([("company_id", "=", base.company_id)]) == 0)
        if args.condition == "C0":
            _require(move.write_uid.id == principal)
        else:
            event = env["ap.security.audit.event"].browse(posted["audit_event"]["event_id"]).exists()
            payload = base.audit_kernel._verify_event(event)
            _require(event.executor_user_id.id == principal and payload["subject"]["executor_user_id"] == principal
                     and payload["outcome"]["administrative_caller_id"] == actual_uid
                     and payload["outcome"]["financial_service_uid"] == SUPERUSER_ID)
            if expected_posted:
                checker = object.__new__(RegisteredPostProbe)
                checker.base, checker.command_hash = base, canonical_command_sha256
                checker.verify_effect(env, scope, posted, audit)
            else:
                _require(posted["status"] == "DENIED" and posted["effect_applied"] is False
                         and posted["audit_complete"] is True and posted["reason_codes"] == ["SIGNATURE_INVALID"])
        nonces = env["ap.security.approval.nonce"].search([
            ("company_id", "=", base.company_id), ("nonce_sha256", "=", nonce_sha256)])
        consumed = args.condition == "C1" and expected_posted
        _require(len(nonces) == (1 if consumed else 0)
                 and (not consumed or nonces.state == "consumed"))
        after = collect(env, binding, filestore)
    write_json(stem.with_suffix(".after.capture.json"), after)
    supervision = RunSupervision(run_id=args.slot_run_id, condition=args.condition, code_commit=args.git_base,
        configuration_sha256=manifest["configuration_sha256"], host_id=host_id, clock_id=clock_id,
        mode="OBSERVED", effect_quiescence="CONFIRMED",
        intervals=(StageInterval("execution", started_ns, finished_ns),))
    result = {"schema_version": VERSION, "status": "PASS", "proof_run_id": args.proof_run_id,
        "slot_run_id": args.slot_run_id, "database": args.database, "condition": args.condition,
        "grant_mode": args.grant_mode, "git_base": args.git_base,
        "source_bundle_sha256": args.source_bundle_sha256,
        "before_capture_sha256": before["capture_sha256"], "after_capture_sha256": after["capture_sha256"],
        "observation": observation, "supervision": supervision.to_mapping(),
        "effect_move_id": target if expected_posted else None,
        "identity": {"approval_principal_id": principal, "administrative_caller_id": actual_uid,
            "financial_service_uid": actual_uid, "execution_env_uid": actual_uid, "execution_env_su": actual_su},
        "read_only_invariant_verified": True, "nonce_available_before": nonce_available,
        "nonce_consumed_after": consumed, "effect_posted": expected_posted,
        "external_provider_called": False, "policy_engine_used": False, "llm_stage_used": False,
        "run_record_created": False, "scientific_run": False, "human_review_complete": False,
        "public_executor_enabled": False}
    write_json(stem.with_suffix(".native.json"), result)
    scope.key = scope.authority = scope.post_command = command = None
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="DEC-077 disposable native approval observation")
    for name in ("database", "git-base", "source-bundle-sha256", "proof-run-id", "slot-run-id"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--condition", choices=("C0", "C1"), required=True)
    parser.add_argument("--grant-mode", choices=("valid", "invalid-mac"), required=True)
    parser.add_argument("--config", default="/etc/odoo/runner.conf")
    parser.add_argument("--artifacts", default="/mnt/runner-artifacts")
    parser.add_argument("--secret-directory", default="/run/runner-secrets")
    args = parser.parse_args(argv)
    args.case = "post"
    logging.disable(logging.CRITICAL)
    try:
        validate_options(args)
        import odoo
        from odoo.orm.registry import Registry
        odoo.tools.config.parse_config(["-c", args.config, "-d", args.database, "--no-http"], setup_logging=False)
        run(args, Registry(args.database))
    except Exception as error:
        frames = [frame for frame in traceback.extract_tb(error.__traceback__)
                  if Path(frame.filename).name == "live_approval_native.py"]
        diagnostic = {"schema_version": "live-approval-native-failure/v1", "status": "FAIL",
            "category": type(error).__name__ if type(error).__name__ in {
                "ValueError", "TypeError", "KeyError", "ImportError", "ModuleNotFoundError", "ProbeFailure",
                "AccessError", "ValidationError", "RegisteredPostError"} else "OTHER_RUNTIME_FAILURE",
            "source_file": "live_approval_native.py", "source_line": frames[-1].lineno if frames else None}
        try:
            validate_options(args)
            path = Path(args.artifacts) / (args.database + "-" + args.condition + "-" + args.grant_mode + ".failure.json")
            path.write_text(json.dumps(diagnostic, sort_keys=True) + "\n", encoding="utf-8")
        except Exception:
            pass
        print("LIVE_APPROVAL_NATIVE_FAILED")
        return 1
    print("LIVE_APPROVAL_NATIVE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
