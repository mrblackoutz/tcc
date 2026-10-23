# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-075 private cross-process POST using the original preissued capsule.

This is an administrative command, not a model output or policy-engine result.
No issuer, public execution method, gateway handoff or persistent grant exists.
"""

from copy import deepcopy
import hashlib
import json
import secrets


def _require(value):
    if not value:
        raise ValueError("PILOT_APPROVED_POST_INVALID")


def _hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def run(args, registry):
    _require(args.mode == "approved-post" and args.with_approved_post is True
             and args.with_approval_binding is True and type(args.fixture_ref) is str)
    from c111_transactions import Scope, canonical
    from pilot_approval_native import PROFILE
    from pilot_post_custody import read_capsule
    from pilot_reset_native import _validated
    from registered_post_transactions import RegisteredPostProbe
    from runner_approved_post_native import _unchanged_except_audit
    from runner_observed_fixture import load_inputs, load_scope, read_json, write_json
    from runner_pilot_a3a_origin_native import _command, _configuration, _input, _target
    from tcc_gateway.pilot_seed_contract import MAX_SEED_BYTES, PilotBusinessSeed
    from tcc_gateway.pilot_a3a_origin_contract import MAX_ORIGIN_BYTES, PilotA3aOriginInput, document_bytes
    from odoo.addons.ap_security_executor import registered_post, workflow_registry
    from odoo.addons.ap_security_executor.approval import ApprovalAuthority, ApprovalKey, verify_approval
    from odoo.addons.ap_security_executor.draft_contracts import canonical_command_sha256
    from odoo.addons.ap_security_executor.identity import assert_executor_identity
    from odoo.addons.ap_security_executor.post_contracts import TrustedPostWorkflow
    from odoo.addons.ap_security_executor.workflow_contracts import WorkflowProvenance
    from datetime import datetime, timezone

    root, proof, validated_manifest, _capture_binding = _validated(args)
    capsule = read_capsule(args.database)
    link = read_json(root / "pilot-reset-binding.json")
    _require(capsule["clone_binding"] == link and link["fixture_ref"] == args.fixture_ref
             and capsule["git_base"] == args.git_base and capsule["source_bundle_sha256"] == args.source_bundle_sha256
             and all(capsule[name] == proof[name] for name in ("cohort_sha256", "codebook_sha256")))
    seed = _input(root / "pilot-business-seed.json", PilotBusinessSeed, MAX_SEED_BYTES, proof["seed_sha256"])
    package = _input(root / "pilot-a3a-origin.json", PilotA3aOriginInput, MAX_ORIGIN_BYTES, link["origin_input_sha256"])
    rows = [row for row in seed.to_mapping()["fixtures"] if row["fixture_ref"] == args.fixture_ref]
    sources = [row for row in package.to_mapping()["fixtures"] if row["fixture_ref"] == args.fixture_ref]
    _require(len(rows) == len(sources) == 1)
    row, source = rows[0], sources[0]
    _require(row["pair_sha256"] == source["pair_sha256"]
             and capsule["scenario_id"] == source["document"]["scenario_id"]
             and capsule["document_sha256"] == source["document"]["document_sha256"])
    _artifacts, manifest, native = load_inputs(args)
    _require(manifest == validated_manifest)
    observer, support_scope, _support_registration = load_scope(registry, args, manifest, native["cases"][0])
    base = observer.base
    _require(capsule["company_id"] == base.company_id and capsule["executor_user_id"] == base.user_id)
    document = base.SourceDocument(raw=document_bytes(source["document"]), mimetype="application/pdf")
    config_sha = "sha256:" + hashlib.sha256(canonical(
        _configuration(package.sha256, seed.sha256, args.fixture_ref))).hexdigest()
    provenance = WorkflowProvenance(args.git_base, "sha256:" + args.source_bundle_sha256, config_sha)

    def audit():
        return base.TrustedAuditContext(run_id="TCC-PILOT-A3A-APPROVED-POST", attempt_id=secrets.token_hex(16),
            code_commit=args.git_base, code_sha256=provenance.code_sha256, configuration_sha256=config_sha)

    arguments = dict(registration_id=capsule["registration_id"], expected_company_id=base.company_id,
        expected_executor_user_id=base.user_id, expected_scenario_id=source["document"]["scenario_id"],
        document=document, provenance=provenance)
    approval = read_json(root / "pilot-a3a-approval-result.json")
    _require(approval["schema_version"] == "pilot-a3a-approval-native/v1" and approval["status"] == "PASS"
             and approval["profile"] == PROFILE and approval["approval_count"] == 1
             and approval["negative_check_count"] == 20
             and all(approval[name] == value for name, value in {
                 "fixture_ref": args.fixture_ref, "scenario_id": capsule["scenario_id"],
                 "document_sha256": capsule["document_sha256"], "origin_input_sha256": package.sha256,
                 "seed_sha256": seed.sha256, "cohort_sha256": proof["cohort_sha256"],
                 "codebook_sha256": proof["codebook_sha256"], "git_base": args.git_base,
                 "source_bundle_sha256": args.source_bundle_sha256}.items()))
    with registry.cursor() as cr:
        cr.execute("SET TRANSACTION READ ONLY")
        base.cursor_gate(cr)
        _require(cr.dbname == args.database)
        env = base.env(cr)
        resolved = workflow_registry.resolve_draft_workflow(env, **arguments)
        _require(resolved.registration_sha256 == capsule["registration_sha256"])
        origin = _target(env, resolved, audit(), capsule["create_result"], row, source, document)
        _require(origin == capsule["origin"])
        command = _command(base, resolved.workflow, row, source)
        trusted_action = dict(deepcopy(command["action"]), action="POST_VENDOR_BILL", executor_mode="POST_APPROVED",
                              target_move_id=origin["target_move_id"])
        scope = Scope(resolved.workflow, command, document, resolved.workflow.vendor_id,
                      resolved.workflow.purchase_order_id, result=deepcopy(capsule["create_result"]))
        scope.post_workflow = TrustedPostWorkflow(draft=resolved.workflow, target_move_id=origin["target_move_id"])
        scope.authority = ApprovalAuthority(**capsule["authority"])
        scope.key = ApprovalKey(base.company_id, scope.authority.key_id, bytes.fromhex(capsule["key_material"]))
        scope.post_command = deepcopy(capsule["command"])
        _require(scope.post_command["action"] == trusted_action
                 and scope.post_command["idempotency_key"] == command["idempotency_key"]
                 and scope.authority.company_id == base.company_id and scope.authority.executor_user_id == base.user_id)
        verified = verify_approval(scope.post_command, trusted_action=trusted_action,
            authority=scope.authority, key=scope.key, now=datetime.now(timezone.utc))
        _require(verified.action_hash == approval["action_sha256"]
                 and verified.approval_sha256 == approval["approval_sha256"]
                 and verified.nonce_sha256 == approval["nonce_sha256"])
        identity = assert_executor_identity(env, env["res.users"].browse(base.user_id), company=env.company)
        before = observer.projection(env, support_scope)
        _require(identity["inventory_sha256"] == capsule["identity_sha256"]
                 and _hash(before) == capsule["before_projection_sha256"])

    def post(env, body, current_audit):
        envelope = registered_post.post_registered_bill_audited(env,
            registration_id=resolved.registration_id, expected_company_id=base.company_id,
            expected_executor_user_id=base.user_id, expected_scenario_id=scope.workflow.scenario_id,
            command=body, audit=current_audit, document=document, authority=scope.authority, key=scope.key)
        _require(envelope["caller_transaction_pending"] is True and envelope["origin"] == origin
                 and envelope["registration"] == {"registration_id": resolved.registration_id,
                     "registration_sha256": resolved.registration_sha256})
        return envelope["result"]

    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        tampered = deepcopy(scope.post_command)
        signature = tampered["approval"]["signature"]
        tampered["approval"]["signature"] = signature[:-1] + ("0" if signature[-1] != "0" else "1")
        rejected = post(env, tampered, audit())
        _require(rejected["status"] == "DENIED" and rejected["effect_applied"] is False
                 and rejected["audit_complete"] is True and rejected["reason_codes"] == ["SIGNATURE_INVALID"])
        _unchanged_except_audit(before, observer.projection(env, support_scope), "DENIED")
        cr.commit()
    _unchanged_except_audit(before, observer.fresh_projection(support_scope), "DENIED")
    posted_audit = audit()
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        posted = post(base.env(cr), deepcopy(scope.post_command), posted_audit)
        base.success(posted, "POSTED")
        cr.commit()
    checker = object.__new__(RegisteredPostProbe)
    checker.base, checker.command_hash = base, canonical_command_sha256
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        checker.verify_effect(env, scope, posted, posted_audit)
        _require(registered_post._origin(env, resolved, posted_audit)[1] == origin
                 and assert_executor_identity(env, env["res.users"].browse(base.user_id), company=env.company)["inventory_sha256"]
                 == capsule["identity_sha256"])
    posted_after = observer.fresh_projection(support_scope)
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        replay = post(env, deepcopy(scope.post_command), audit())
        base.success(replay, "REPLAY")
        _require(replay["receipt"] == posted["receipt"])
        _unchanged_except_audit(posted_after, observer.projection(env, support_scope), "REPLAY", workflow=scope.workflow)
        cr.commit()
    _unchanged_except_audit(posted_after, observer.fresh_projection(support_scope), "REPLAY", workflow=scope.workflow)
    _require(read_capsule(args.database) == capsule)
    _validated(args)
    write_json(root / "pilot-a3a-approved-post-result.json", {
        "schema_version": "pilot-a3a-approved-post-native/v1", "status": "PASS",
        **{name: approval[name] for name in ("fixture_ref", "scenario_id", "document_sha256", "origin_input_sha256",
            "seed_sha256", "cohort_sha256", "codebook_sha256", "git_base", "source_bundle_sha256")},
        "database": args.database, "profile": PROFILE,
        "action_sha256": verified.action_hash, "approval_sha256": verified.approval_sha256,
        "nonce_sha256": verified.nonce_sha256, "command_sha256": canonical_command_sha256(scope.post_command),
        "origin_sha256": origin["origin_sha256"], "posted_count": 1, "replay_count": 1, "invalid_mac_rejections": 1,
        "fresh_cursor_receipt_nonce_pdf_verified": True, "executor_identity_unchanged": True,
        "custody_between_phases": True, "nonce_consumed": True,
        "external_provider_called": False, "scientific_run": False, "human_review_complete": False,
        "public_executor_enabled": False, "policy_engine_used": False, "llm_stage_used": False,
        "gateway_handoff_performed": False,
    })
    scope.key = scope.authority = scope.post_command = None
