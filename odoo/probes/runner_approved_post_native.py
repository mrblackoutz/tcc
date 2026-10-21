# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-069 observed REVIEW -> preissued fixture -> private POST, dev only.

Keys/authority stay in Odoo-only /tmp; transport token stays in shared tmpfs.
Persistent artifacts contain hashes/observations, never a token or key.
"""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import stat

import odoo
from odoo.orm.registry import Registry

from c111_transactions import canonical, digest, require
from registered_post_transactions import RegisteredPostProbe
from runner_observed_fixture import load_inputs, load_scope, read_json, write_json


CASE = "observed_post_without_approval"
PRIVATE_PATH = Path("/tmp/tcc-approved-post-private.json")
MAX_SECRET_BYTES = 32 * 1024


def _sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _write_secret(path, value, mode):
    raw = canonical(value)
    require(len(raw) <= MAX_SECRET_BYTES, "bounded_approval_transport")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
    os.chmod(path, mode)


def _read_private():
    descriptor = os.open(PRIVATE_PATH, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= MAX_SECRET_BYTES,
                "private_approval_tmpfs_owner_and_mode")
        raw = stream.read(MAX_SECRET_BYTES + 1)
    require(len(raw) == info.st_size, "private_approval_bounded_read")
    return json.loads(raw)


def _load(args):
    require(args.approved_post_mode and args.mode in {"approved-post-prepare", "approved-post-execute"},
            "explicit_approved_post_mode")
    odoo.tools.config.parse_config(["-c", args.config, "-d", args.database, "--no-http"], setup_logging=False)
    registry = Registry(args.database)
    artifacts, manifest, native = load_inputs(args)
    index = [row["name"] for row in native["cases"]].index(CASE)
    observer, scope, registration = load_scope(registry, args, manifest, native["cases"][index])
    return registry, artifacts, manifest, observer, scope, registration


def _unchanged_except_audit(before, after, status, *, workflow=None):
    require(before.keys() == after.keys(), "approved_post_projection_shape")
    guards = {"ap.security.po.guard": ("po_id", workflow.purchase_order_id),
              "ap.security.vendor.guard": ("vendor_id", workflow.vendor_id)} if status == "REPLAY" else {}
    for name in before.keys() - {"ap.security.audit.event"} - guards.keys():
        require(canonical(before[name]) == canonical(after[name]), "approved_post_no_second_financial_effect")
    for name, (field, expected_id) in guards.items():
        old = {row["id"]: row for row in before[name]}
        new = {row["id"]: row for row in after[name]}
        require(old.keys() == new.keys(), "approved_post_replay_no_new_guards")
        touched = 0
        for ident, row in old.items():
            ignored = set()
            if row[field][0] == expected_id:
                require(type(new[ident]["revision"]) is int and new[ident]["revision"] == row["revision"] + 1,
                        "approved_post_replay_exact_guard_increment")
                ignored = {"revision", "write_date"}
                touched += 1
            require({k: v for k, v in row.items() if k not in ignored} ==
                    {k: v for k, v in new[ident].items() if k not in ignored}, "approved_post_unrelated_guard_unchanged")
        require(touched == 1, "approved_post_known_replay_guard")
    old = {row["id"]: row for row in before["ap.security.audit.event"]}
    new = {row["id"]: row for row in after["ap.security.audit.event"]}
    require(old.keys() <= new.keys() and all(old[k] == new[k] for k in old)
            and len(new.keys() - old.keys()) == 1
            and next(new[k]["status"] for k in new.keys() - old.keys()) == status,
            "approved_post_only_one_declared_audit_event")


def _prepare(args, registry, artifacts, manifest, observer, scope, registration):
    from odoo.addons.ap_security_executor.approval import APPROVAL_DOMAIN, ApprovalAuthority, ApprovalKey
    from odoo.addons.ap_security_executor.post_contracts import TrustedPostWorkflow
    from odoo.addons.ap_security_executor.identity import assert_executor_identity
    base = observer.base
    base.ApprovalAuthority, base.ApprovalKey = ApprovalAuthority, ApprovalKey
    base.TrustedPostWorkflow, base.approval_domain = TrustedPostWorkflow, APPROVAL_DOMAIN
    # This input is the legitimate registered CREATE fixture, not the candidate.
    base.prepare_post(scope)
    candidate = next(row for row in read_json(artifacts / "observed-candidates.json")["cases"] if row["name"] == CASE)
    action = candidate["canonical_action"]
    require(digest(action) == candidate["action_sha256"]
            and action == scope.post_command["action"], "preissued_fixture_and_independent_development_candidate")
    before = observer.fresh_projection(scope)
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        identity = assert_executor_identity(env, env["res.users"].browse(base.user_id), company=env.company)
        observation = observer.observation_module.observe_registered_policy_state(env,
            registration_id=registration.registration_id, expected_company_id=base.company_id,
            expected_executor_user_id=base.user_id, expected_scenario_id=scope.workflow.scenario_id,
            document=scope.document, provenance=observer.provenance, canonical_action=deepcopy(action))
        observer.verify_observation(observation, scope, registration, action, facts=observer.facts())
        require(observer.projection(env, scope) == before, "approved_post_prepare_is_read_only")
        cr.commit()
    require(observer.fresh_projection(scope) == before, "approved_post_prepare_commit_is_read_only")
    binding = {name: manifest[name] for name in ("git_base", "source_bundle_sha256", "configuration_sha256")}
    _write_secret(PRIVATE_PATH, {**binding, "authority": asdict(scope.authority),
        "key_material": scope.key.material.hex(), "approval": scope.post_command["approval"],
        "baseline_sha256": _sha(before), "identity_sha256": identity["inventory_sha256"]}, 0o600)
    _write_secret(Path(args.secret_directory) / "approved-post-fixture.json",
        {"schema_version": "approved-post-transport/v1", **binding,
         "approval": scope.post_command["approval"]}, 0o640)
    write_json(artifacts / "approved-post-observation.json", {
        "schema_version": "approved-post-observation/v1", "status": "PASS", **binding,
        "observation": observation, "action_sha256": candidate["action_sha256"],
        "read_only_confirmed": True, "approval_sha256": _sha(scope.post_command["approval"]),
    })


def _execute(args, registry, artifacts, manifest, observer, scope, registration):
    from odoo.addons.ap_security_executor import registered_post
    from odoo.addons.ap_security_executor.approval import ApprovalAuthority, ApprovalKey
    from odoo.addons.ap_security_executor.draft_contracts import canonical_command_sha256
    from odoo.addons.ap_security_executor.identity import assert_executor_identity
    saved = _read_private()
    gateway = read_json(artifacts / "approved-post-policy.json")
    require(gateway["schema_version"] == "approved-post-policy/v1" and gateway["status"] == "PASS"
            and all(saved[name] == manifest[name] == gateway[name] for name in
                    ("git_base", "source_bundle_sha256", "configuration_sha256")), "approved_post_shared_provenance")
    require("approval" not in gateway["command_without_approval"], "no_persistent_transport_token")
    command = dict(gateway["command_without_approval"], approval=saved["approval"])
    require(_sha(command) == gateway["command_sha256"] and _sha(saved["approval"]) == gateway["approval_sha256"],
            "native_reassembly_exact_gateway_handoff")
    scope.authority = ApprovalAuthority(**saved["authority"])
    scope.key = ApprovalKey(scope.authority.company_id, scope.authority.key_id, bytes.fromhex(saved["key_material"]))
    scope.post_command = command
    base = observer.base
    before = observer.fresh_projection(scope)
    require(_sha(before) == saved["baseline_sha256"], "approved_post_prepared_state_unchanged")

    def post(env, body, audit):
        return registered_post.post_registered_bill_audited(env,
            registration_id=registration.registration_id, expected_company_id=base.company_id,
            expected_executor_user_id=base.user_id, expected_scenario_id=scope.workflow.scenario_id,
            command=body, audit=audit, document=scope.document, authority=scope.authority, key=scope.key)

    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        tampered = deepcopy(command)
        signature = tampered["approval"]["signature"]
        tampered["approval"]["signature"] = signature[:-1] + ("0" if signature[-1] != "0" else "1")
        rejected = post(env, tampered, observer.audit())["result"]
        require(rejected["status"] == "DENIED" and not rejected["effect_applied"]
                and rejected["audit_complete"] and rejected["reason_codes"] == ["SIGNATURE_INVALID"],
                "native_invalid_mac_rejected_even_after_gateway_binding")
        _unchanged_except_audit(before, observer.projection(env, scope), "DENIED")
        cr.commit()
    bad_after = observer.fresh_projection(scope)
    _unchanged_except_audit(before, bad_after, "DENIED")
    audit = observer.audit()
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        posted = post(base.env(cr), command, audit)
        base.success(posted["result"], "POSTED")
        cr.commit()
    checker = object.__new__(RegisteredPostProbe)
    checker.base, checker.command_hash = base, canonical_command_sha256
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        checker.verify_effect(env, scope, posted["result"], audit)
        require(assert_executor_identity(env, env["res.users"].browse(base.user_id), company=env.company)["inventory_sha256"]
                == saved["identity_sha256"],
                "approved_post_executor_inventory_unchanged")
    posted_after = observer.fresh_projection(scope)
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        replay = post(env, command, observer.audit())
        base.success(replay["result"], "REPLAY")
        require(replay["result"]["receipt"] == posted["result"]["receipt"], "approved_post_exact_replay_receipt")
        _unchanged_except_audit(posted_after, observer.projection(env, scope), "REPLAY", workflow=scope.workflow)
        cr.commit()
    after = observer.fresh_projection(scope)
    _unchanged_except_audit(posted_after, after, "REPLAY", workflow=scope.workflow)
    write_json(artifacts / "approved-post-result.json", {
        "schema_version": "approved-post-native/v1", "status": "PASS",
        **{name: manifest[name] for name in ("git_base", "source_bundle_sha256", "configuration_sha256")},
        "command_sha256": gateway["command_sha256"], "approval_sha256": gateway["approval_sha256"],
        "policy_result_sha256": _sha(gateway), "posted_count": 1, "replay_count": 1, "invalid_mac_rejections": 1,
        "fresh_cursor_receipt_nonce_pdf_verified": True, "executor_identity_unchanged": True,
        "provider_mocked": True, "external_provider_called": False, "public_executor_enabled": False,
        "scientific_run": False, "human_review_complete": False,
    })


def run(args):
    loaded = _load(args)
    if args.mode == "approved-post-prepare":
        _prepare(args, *loaded)
    else:
        _execute(args, *loaded)
