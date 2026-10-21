# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-074 exact legitimate fixture approval, in one native process only.

No candidate/model output is read or signed. Key, authority, token and nonce
remain in memory; this proof neither persists a grant nor reserves a nonce.
The development issuer's policy object is not a real policy-engine decision.
"""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets


PROFILE = "c111-development-utc-minus60-plus600/v1"
NEGATIVE_CHECK_COUNT = 20


def _require(value):
    if not value:
        raise ValueError("PILOT_APPROVAL_NATIVE_INVALID")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False, default=str).encode("utf-8")


def _hash(value):
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _other(value):
    return "TCC-APPROVAL-OTHER" if value != "TCC-APPROVAL-OTHER" else "TCC-APPROVAL-OTHER-2"


def _negative_checks(command, *, trusted_action, authority, key, now, verify, error_type):
    """Twenty pure verifier negatives; none signs, persists or executes a command."""
    binding_codes = {"CONTRACT_INVALID", "BINDING_MISMATCH"}
    checks = []
    missing = deepcopy(command)
    missing.pop("approval")
    checks.append((missing, key, now, {"CONTRACT_INVALID"}))
    for name in ("fixture_id", "nonce"):
        changed = deepcopy(command)
        changed["approval"][name] = _other(changed["approval"][name])
        checks.append((changed, key, now, binding_codes))
    changes = {
        "scenario_id": _other(trusted_action["scenario_id"]),
        "document_sha256": ("0" if trusted_action["document_sha256"] != "0" * 64 else "1") * 64,
        "vendor_ref": _other(trusted_action["vendor_ref"]),
        "purchase_order_ref": _other(trusted_action["purchase_order_ref"]),
        "document_ref": _other(trusted_action["document_ref"]),
        "invoice_date": "2026-01-01" if trusted_action["invoice_date"] != "2026-01-01" else "2026-01-02",
        "currency": "USD" if trusted_action["currency"] != "USD" else "BRL",
        "amount": "1.00" if trusted_action["amount"] != "1.00" else "2.00",
        "recipient_bank_ref": _other(trusted_action["recipient_bank_ref"]),
        "lines": [dict(line) for line in trusted_action["lines"]],
        "target_move_id": trusted_action["target_move_id"] + 1,
        "policy_version": "policy-v9.0.0" if trusted_action["policy_version"] != "policy-v9.0.0" else "policy-v8.0.0",
    }
    old_quantity = changes["lines"][0]["quantity"]
    changes["lines"][0]["quantity"] = "1.00" if old_quantity != "1.00" else "2.00"
    for name, value in changes.items():
        changed = deepcopy(command)
        changed["action"][name] = value
        changed["policy_decision"]["proposed_action_hash"] = _hash(changed["action"])
        if name == "policy_version":
            changed["policy_decision"]["policy_version"] = value
        checks.append((changed, key, now, binding_codes))
    bad_mac = deepcopy(command)
    signature = bad_mac["approval"]["signature"]
    bad_mac["approval"]["signature"] = signature[:-1] + ("0" if signature[-1] != "0" else "1")
    checks.append((bad_mac, key, now, {"SIGNATURE_INVALID"}))
    bad_material = bytes([key.material[0] ^ 1]) + key.material[1:]
    checks.append((deepcopy(command), replace(key, material=bad_material), now, {"SIGNATURE_INVALID"}))
    checks.append((deepcopy(command), replace(key, company_id=key.company_id + 1), now,
                   {"DEPENDENCY_UNAVAILABLE"}))
    issued = datetime.fromisoformat(authority.issued_at.replace("Z", "+00:00"))
    expires = datetime.fromisoformat(authority.expires_at.replace("Z", "+00:00"))
    checks.append((deepcopy(command), key, issued - timedelta(seconds=1), {"NOT_YET_VALID"}))
    checks.append((deepcopy(command), key, expires, {"EXPIRED"}))
    _require(len(checks) == NEGATIVE_CHECK_COUNT)
    for body, selected_key, clock, expected in checks:
        try:
            verify(body, trusted_action=deepcopy(trusted_action), authority=authority, key=selected_key, now=clock)
        except error_type as error:
            _require(error.code in expected)
        else:
            _require(False)
    return len(checks)


def run(args, registry, contexts):
    _require(args.mode == "materialize" and args.with_approval_binding is True
             and type(args.fixture_ref) is str and type(contexts) is tuple and len(contexts) == 1)
    context = contexts[0]
    _require(type(context) is dict and set(context) == {"source", "row", "workflow", "document",
             "other_document", "registration", "other_registration", "result"})
    from c111_transactions import Scope, canonical
    from pilot_reset_native import _validated
    from runner_observed_fixture import load_inputs, load_scope, read_json, write_json
    from runner_pilot_a3a_origin_native import _command, _configuration, _input, _target
    from tcc_gateway.pilot_seed_contract import MAX_SEED_BYTES, PilotBusinessSeed
    from tcc_gateway.pilot_a3a_origin_contract import MAX_ORIGIN_BYTES, PilotA3aOriginInput, document_bytes
    from odoo.addons.ap_security_executor import workflow_registry
    from odoo.addons.ap_security_executor.approval import (
        APPROVAL_DOMAIN, ApprovalAuthority, ApprovalKey, ApprovalVerificationError, verify_approval,
    )
    from odoo.addons.ap_security_executor.identity import assert_executor_identity
    from odoo.addons.ap_security_executor.post_contracts import TrustedPostWorkflow
    from odoo.addons.ap_security_executor.workflow_contracts import WorkflowProvenance

    root, proof, validated_manifest, _capture_binding = _validated(args)
    _artifacts, manifest, native = load_inputs(args)
    _require(manifest == validated_manifest)
    seed = _input(root / "pilot-business-seed.json", PilotBusinessSeed, MAX_SEED_BYTES, proof["seed_sha256"])
    link = read_json(root / "pilot-reset-binding.json")
    package = _input(root / "pilot-a3a-origin.json", PilotA3aOriginInput, MAX_ORIGIN_BYTES,
                     link["origin_input_sha256"])
    seed_value, package_value = seed.to_mapping(), package.to_mapping()
    sources = [row for row in package_value["fixtures"] if row["fixture_ref"] == args.fixture_ref]
    rows = [row for row in seed_value["fixtures"] if row["fixture_ref"] == args.fixture_ref]
    _require(len(sources) == len(rows) == 1 and context["source"] == sources[0] and context["row"] == rows[0])
    source, row = sources[0], rows[0]
    _require(source["pair_sha256"] == row["pair_sha256"]
             and context["document"].raw == document_bytes(source["document"])
             and context["workflow"] == context["registration"].workflow
             and type(context["result"]) is dict and context["result"].get("status") == "CREATED"
             and context["result"].get("effect_applied") is True)
    result = read_json(root / "pilot-a3a-origin-result.json")
    _require(result["schema_version"] == "pilot-a3a-origin-single-native/v1" and result["status"] == "PASS"
             and result["fixture_ref"] == args.fixture_ref and result["fixture_count"] == 1
             and result["origin_input_sha256"] == package.sha256 and result["seed_sha256"] == seed.sha256
             and result["git_base"] == args.git_base and result["source_bundle_sha256"] == args.source_bundle_sha256)
    observer, support_scope, _registration = load_scope(registry, args, manifest, native["cases"][0])
    base = observer.base
    base.ApprovalAuthority, base.ApprovalKey = ApprovalAuthority, ApprovalKey
    base.TrustedPostWorkflow, base.approval_domain = TrustedPostWorkflow, APPROVAL_DOMAIN
    config_sha = "sha256:" + hashlib.sha256(canonical(
        _configuration(package.sha256, seed.sha256, args.fixture_ref))).hexdigest()
    provenance = WorkflowProvenance(args.git_base, "sha256:" + args.source_bundle_sha256, config_sha)
    audit = base.TrustedAuditContext(run_id="TCC-PILOT-A3A-APPROVAL-PROOF", attempt_id=secrets.token_hex(16),
        code_commit=args.git_base, code_sha256=provenance.code_sha256, configuration_sha256=config_sha)
    workflow = context["workflow"]
    arguments = dict(registration_id=context["registration"].registration_id,
        expected_company_id=base.company_id, expected_executor_user_id=base.user_id,
        expected_scenario_id=source["document"]["scenario_id"], document=context["document"], provenance=provenance)
    _require(workflow.company_id == base.company_id and workflow.executor_user_id == base.user_id
             and workflow.scenario_id == source["document"]["scenario_id"]
             and workflow.document_sha256 == source["document"]["document_sha256"])
    with registry.cursor() as cr:
        cr.execute("SET TRANSACTION READ ONLY")
        base.cursor_gate(cr)
        _require(cr.dbname == args.database)
        env = base.env(cr)
        before = observer.projection(env, support_scope)
        _require(hashlib.sha256(canonical(before)).hexdigest() == result["company_projection_sha256"])
        inventory = assert_executor_identity(env, env["res.users"].browse(base.user_id), company=env.company)
        resolved = workflow_registry.resolve_draft_workflow(env, **arguments)
        _require(resolved == context["registration"])
        origin = _target(env, resolved, audit, context["result"], row, source, context["document"])
        _require(hashlib.sha256(canonical([origin])).hexdigest() == result["origins_sha256"])
        command = _command(base, workflow, row, source)
        scope = Scope(workflow, command, context["document"], workflow.vendor_id,
                      workflow.purchase_order_id, result=deepcopy(context["result"]))
        _require(scope.result is not None and scope.result["receipt"]["move_id"] == origin["target_move_id"])
        trusted_action = dict(deepcopy(command["action"]), action="POST_VENDOR_BILL", executor_mode="POST_APPROVED",
                              target_move_id=origin["target_move_id"])
        clock_before = datetime.now(timezone.utc).replace(microsecond=0)
        base.prepare_post(scope)
        clock_after = datetime.now(timezone.utc).replace(microsecond=0)
        _require(scope.post_command["action"] == trusted_action
                 and scope.authority.company_id == base.company_id
                 and scope.authority.executor_user_id == base.user_id
                 and scope.post_workflow.target_move_id == origin["target_move_id"])
        issued = datetime.fromisoformat(scope.authority.issued_at.replace("Z", "+00:00"))
        expires = datetime.fromisoformat(scope.authority.expires_at.replace("Z", "+00:00"))
        _require(clock_before <= issued + timedelta(seconds=60) <= clock_after
                 and expires - issued == timedelta(seconds=660))
        now = datetime.now(timezone.utc)
        verified = verify_approval(scope.post_command, trusted_action=trusted_action,
            authority=scope.authority, key=scope.key, now=now)
        negative_count = _negative_checks(scope.post_command, trusted_action=trusted_action,
            authority=scope.authority, key=scope.key, now=now, verify=verify_approval,
            error_type=ApprovalVerificationError)
        _require(observer.projection(env, support_scope) == before
                 and inventory == assert_executor_identity(env, env["res.users"].browse(base.user_id), company=env.company))
    with registry.cursor() as cr:
        cr.execute("SET TRANSACTION READ ONLY")
        base.cursor_gate(cr)
        env = base.env(cr)
        _require(observer.projection(env, support_scope) == before
                 and inventory == assert_executor_identity(env, env["res.users"].browse(base.user_id), company=env.company))
        resolved = workflow_registry.resolve_draft_workflow(env, **arguments)
        _require(resolved == context["registration"]
                 and _target(env, resolved, audit, context["result"], row, source, context["document"]) == origin)
    _validated(args)
    _input(root / "pilot-business-seed.json", PilotBusinessSeed, MAX_SEED_BYTES, seed.sha256)
    _input(root / "pilot-a3a-origin.json", PilotA3aOriginInput, MAX_ORIGIN_BYTES, package.sha256)
    write_json(root / "pilot-a3a-approval-result.json", {
        "schema_version": "pilot-a3a-approval-native/v1", "status": "PASS", "fixture_ref": args.fixture_ref,
        "scenario_id": source["document"]["scenario_id"], "document_sha256": source["document"]["document_sha256"],
        "origin_input_sha256": package.sha256, "seed_sha256": seed.sha256,
        "cohort_sha256": proof["cohort_sha256"], "codebook_sha256": proof["codebook_sha256"],
        "git_base": args.git_base, "source_bundle_sha256": args.source_bundle_sha256,
        "approval_count": 1, "negative_check_count": negative_count, "action_sha256": verified.action_hash,
        "approval_sha256": verified.approval_sha256, "nonce_sha256": verified.nonce_sha256, "profile": PROFILE,
        "approval_generated": True, "approval_verified": True, "read_only_confirmed": True,
        "executor_identity_unchanged": True, "nonce_reserved": False, "post_executed": False,
        "external_provider_called": False, "scientific_run": False, "human_review_complete": False,
        "public_executor_enabled": False,
    })
    scope.key = scope.authority = scope.post_command = None
