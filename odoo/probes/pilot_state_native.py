# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-095 native half of the pilot state run, inside disposable databases only.

Baseline phases register the trusted workflows of every pilot document before
any provider output exists. Slot phases observe, execute and capture one slot.
Expected facts come from the business seed, never from the model or a label.
No credential, token or nonce is written outside the secret volume.
"""

import argparse
import copy
from dataclasses import asdict, replace
from datetime import datetime, timedelta
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import traceback
from types import SimpleNamespace


_DB = re.compile(r"tcc_runner_[0-9a-f]{12}\Z")
_MEMBER = re.compile(r"PAIR-[A-Z0-9]{4}\.(?:benign|adversarial)\Z")
MEMBERS_FILE = "pilot-state-members.json"
CREATE_FILE = "pilot-state-create.json"
IDENTITY_FILE = "pilot-state-identities.json"
KEY_HOURS = 12


def require(value, code="PILOT_STATE_NATIVE_INVALID"):
    if not value:
        raise ValueError(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(value):
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def read(path):
    from runner_observed_fixture import read_json
    return read_json(path)


def write(path, value):
    path = Path(path)
    with path.open("xb") as output:  # never replace slot or baseline evidence
        output.write(canonical(value) + b"\n")


def month_window(day):
    from calendar import monthrange
    from datetime import date
    value = date.fromisoformat(day)
    return value.replace(day=1).isoformat(), value.replace(day=monthrange(value.year, value.month)[1]).isoformat()


def registration_provenance(args, seed_sha256, cohort_sha256):
    from odoo.addons.ap_security_executor.workflow_contracts import WorkflowProvenance
    configuration = {"schema_version": "pilot-state-registration/v1", "seed_sha256": seed_sha256,
                     "cohort_sha256": cohort_sha256}
    return WorkflowProvenance(args.git_base, "sha256:" + args.source_bundle_sha256, digest(configuration))


def members(root, seed_value):
    value = read(root / MEMBERS_FILE)
    require(value.get("schema_version") == "pilot-state-members/v1" and value["seed_sha256"] == seed_value["sha256"]
            and value["cohort_sha256"] == seed_value["cohort_sha256"], "PILOT_STATE_MEMBERS_BINDING")
    rows = value["members"]
    require(type(rows) is list and len(rows) == 24 and len({row["member_key"] for row in rows}) == 24,
            "PILOT_STATE_MEMBERS_SHAPE")
    for row in rows:
        require(_MEMBER.fullmatch(row["member_key"]) and row["phase"] in {"DRAFT_INTAKE", "POST_REVIEW"},
                "PILOT_STATE_MEMBER_ROW")
    return rows


def member_document(root, row):
    from odoo.addons.ap_security_executor.document_contracts import SourceDocument
    raw = (root / (row["member_key"] + ".pdf")).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == row["document_sha256"], "PILOT_STATE_MEMBER_PDF")
    return SourceDocument(raw=raw, mimetype="application/pdf")


def expected_lines(env, purchase_line_ids):
    lines = env["purchase.order.line"].browse(list(purchase_line_ids)).sorted("id")
    require(len(lines) == len(purchase_line_ids), "PILOT_STATE_PURCHASE_LINES")
    return [{"purchase_line_id": line.id, "product_id": line.product_id.id,
             "quantity": format(line.product_qty, ".2f"), "price_unit": format(line.price_unit, ".2f")}
            for line in lines]


def entry(*, row, seed_row, workflow, registration, provenance, binding_expected, command, lines, company_name,
          target_move_id=None, origin_result=None):
    """Closed per-document fixture; facts are the legitimate seed command only."""
    action = command["action"]
    post = row["phase"] == "POST_REVIEW"
    require(post == (target_move_id is not None) == (origin_result is not None), "PILOT_STATE_ENTRY_PHASE")
    return {
        "member_key": row["member_key"], "pair_id": row["pair_id"], "fixture_ref": row["fixture_ref"],
        "role": row["role"], "scenario_id": workflow.scenario_id, "document_sha256": workflow.document_sha256,
        "phase": row["phase"], "policy_version": workflow.policy_version, "target_move_id": target_move_id,
        "gateway_workflow": {
            "company_name": company_name, "company_ref": seed_row["company_ref"],
            "scenario_id": workflow.scenario_id, "document_sha256": workflow.document_sha256,
            "purchase_order_ref": action["purchase_order_ref"], "phase": row["phase"],
            "allowed_bank_refs": [action["recipient_bank_ref"]],
            "invoice_date_min": workflow.invoice_date_min, "invoice_date_max": workflow.invoice_date_max,
            "monetary_tolerance": workflow.monetary_tolerance, "quantity_scale": workflow.quantity_scale,
            "target_document_ref": action["document_ref"] if post else None},
        "binding": binding_expected,
        "native": {"workflow": json.loads(canonical(asdict(workflow))), "command": command,
                   "registration_id": registration.registration_id,
                   "registration_sha256": registration.registration_sha256,
                   "provenance": asdict(provenance), "origin_result": origin_result},
        "expected": {"bill": {name: action[name] for name in (
                         "vendor_ref", "purchase_order_ref", "document_ref", "amount", "currency", "recipient_bank_ref")},
                     "state": "posted" if post else "draft",
                     "effect": {"invoice_date": action["invoice_date"], "lines": lines}},
    }


def expected_binding(workflow, registration, provenance):
    return {"registration_id": registration.registration_id, "registration_sha256": registration.registration_sha256,
            "company_id": workflow.company_id, "executor_user_id": workflow.executor_user_id,
            "vendor_id": workflow.vendor_id, "purchase_order_id": workflow.purchase_order_id,
            "journal_id": workflow.journal_id, "purchase_line_ids": list(workflow.purchase_line_ids),
            "allowed_bank_ids": list(workflow.allowed_bank_ids), "code_commit": provenance.code_commit,
            "code_sha256": provenance.code_sha256, "configuration_sha256": provenance.configuration_sha256}


def seed_inputs(root):
    from tcc_gateway.pilot_seed_contract import MAX_SEED_BYTES, PilotBusinessSeed
    with (root / "pilot-business-seed.json").open("rb") as stream:
        seed = PilotBusinessSeed(stream.read(MAX_SEED_BYTES + 1))
    seeded = read(root / "pilot-business-seed-result.json")
    value = seed.to_mapping()
    require(seeded["status"] == "PASS" and seeded["seed_sha256"] == seed.sha256 and seeded["fixture_count"] == 12,
            "PILOT_STATE_SEED_RESULT")
    rows = {row["fixture_ref"]: row for row in value["fixtures"]}
    bindings = {row["fixture_ref"]: row for row in seeded["bindings"]}
    return seed, dict(value, sha256=seed.sha256), rows, bindings


def _key(env, user_id, label):
    from odoo import api
    user_env = api.Environment(env.cr, user_id, {"allowed_company_ids": [env.company.id]}, su=False)
    return user_env["res.users.apikeys"]._generate("rpc", label, datetime.now() + timedelta(hours=KEY_HOURS))


def write_secret(args, name, value):
    path = Path(args.secret_directory) / name
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(value)
    os.chmod(path, 0o640)


def extend(registry, args):
    """Gen-0 baseline: C0 identity, long-lived reader key, 16 CREATE registrations."""
    from odoo import Command
    from odoo.addons.ap_security_executor import workflow_registry
    from runner_observed_fixture import assert_reader, load_inputs, load_scope
    from runner_pilot_a3a_origin_native import _command
    from runner_pilot_seed_native import _verify as verify_seed
    root, manifest, native = load_inputs(args)
    observer, scope, _registration = load_scope(registry, args, manifest, native["cases"][0])
    base = observer.base
    seed, seed_value, rows, bindings = seed_inputs(root)
    member_rows = members(root, seed_value)
    provenance = registration_provenance(args, seed.sha256, seed_value["cohort_sha256"])
    created = []
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        require(_DB.fullmatch(cr.dbname), "PILOT_STATE_DISPOSABLE_DATABASE")
        env = base.env(cr)
        verify_seed(env, seed_value["fixtures"], list(bindings.values()))
        company = env.company
        require(company.id == manifest["company_id"] and "SEM VALOR FISCAL" in company.name, "PILOT_STATE_COMPANY")
        c0 = env["res.users"].create({
            "name": "TCC PILOT C0 - SEM VALOR FISCAL", "login": "tcc-pilot-state-c0",
            "company_id": company.id, "company_ids": [Command.set(company.ids)],
            "group_ids": [Command.set([env.ref("base.group_user").id, env.ref("account.group_account_invoice").id])]})
        neutral = c0.with_user(c0)
        require(not neutral.has_group("base.group_system")
                and not neutral.has_group("ap_security_executor.group_executor")
                and neutral.has_group("account.group_account_invoice"), "PILOT_STATE_C0_NON_ADMINISTRATIVE")
        assert_reader(env, manifest["reader_user_id"], company.id)
        c0_key = _key(env, c0.id, "TCC pilot state C0")
        reader_key = _key(env, manifest["reader_user_id"], "TCC pilot state reader")
        for row in member_rows:
            if row["phase"] != "DRAFT_INTAKE":
                continue
            seed_row, binding = rows[row["fixture_ref"]], bindings[row["fixture_ref"]]
            minimum, maximum = month_window(seed_row["invoice_date"])
            workflow = replace(scope.workflow, purchase_order_id=binding["purchase_order_id"],
                vendor_id=binding["vendor_id"], purchase_line_ids=tuple(binding["purchase_line_ids"]),
                allowed_bank_ids=(binding["bank_id"],), scenario_id=row["scenario_id"],
                document_sha256=row["document_sha256"], invoice_date_min=minimum, invoice_date_max=maximum,
                quantity_scale=seed_row["quantity_scale"])
            registration = workflow_registry.register_draft_workflow(
                env, workflow=workflow, document=member_document(root, row), provenance=provenance)
            command = _command(base, workflow, seed_row, {"document_ref": row["document_ref"]})
            created.append(entry(row=row, seed_row=seed_row, workflow=workflow, registration=registration,
                provenance=provenance, binding_expected=expected_binding(workflow, registration, provenance),
                command=command, lines=expected_lines(env, workflow.purchase_line_ids), company_name=company.name))
        env.flush_all()
        identities = {"c0_user_id": c0.id, "reader_user_id": manifest["reader_user_id"],
                      "company_id": company.id, "company_name": company.name}
        cr.commit()
    require(len(created) == 16, "PILOT_STATE_CREATE_COUNT")
    with registry.cursor() as cr:  # fresh cursor: every registration resolves exactly
        base.cursor_gate(cr)
        env = base.env(cr)
        for item in created:
            row = next(value for value in member_rows if value["member_key"] == item["member_key"])
            resolved = workflow_registry.resolve_draft_workflow(env, registration_id=item["native"]["registration_id"],
                expected_company_id=identities["company_id"],
                expected_executor_user_id=item["native"]["workflow"]["executor_user_id"],
                expected_scenario_id=item["scenario_id"], document=member_document(root, row), provenance=provenance)
            require(resolved.registration_sha256 == item["native"]["registration_sha256"]
                    and json.loads(canonical(asdict(resolved.workflow))) == item["native"]["workflow"],
                    "PILOT_STATE_REGISTRATION_FRESH")
    write_secret(args, "pilot-c0.key", c0_key)
    write_secret(args, "pilot-reader.key", reader_key)
    c0_key = reader_key = None
    write(root / IDENTITY_FILE, {"schema_version": "pilot-state-identities/v1", **identities,
                                 "key_validity_hours": KEY_HOURS})
    write(root / CREATE_FILE, {"schema_version": "pilot-state-create/v1", "seed_sha256": seed.sha256,
                               "cohort_sha256": seed_value["cohort_sha256"], "entries": created})


def origins(registry, args):
    """B0/B1: reuse the DEC-068 package CREATE for four A3a origin drafts."""
    from c111_transactions import Probe
    from runner_pilot_a3a_origin_native import _command, _configuration, run as materialize
    from odoo.addons.ap_security_executor.workflow_contracts import WorkflowProvenance
    from tcc_gateway.pilot_a3a_origin_contract import MAX_ORIGIN_BYTES, PilotA3aOriginInput
    root = Path(args.artifacts)
    seed, seed_value, rows, bindings = seed_inputs(root)
    member_rows = {row["scenario_id"]: row for row in members(root, seed_value)}
    with (root / "pilot-a3a-origin.json").open("rb") as stream:
        package = PilotA3aOriginInput(stream.read(MAX_ORIGIN_BYTES + 1))
    native = SimpleNamespace(**{**vars(args), "dataset_fixture_mode": True, "mode": "pilot-a3a-origins",
                                "pilot_seed_sha256": seed.sha256, "pilot_a3a_origin_sha256": package.sha256})
    contexts = materialize(native, fixture_ref=None)
    require(len(contexts) == 4, "PILOT_STATE_ORIGIN_COUNT")
    provenance = WorkflowProvenance(args.git_base, "sha256:" + args.source_bundle_sha256,
                                    digest(_configuration(package.sha256, seed.sha256, None)))
    identities = read(root / IDENTITY_FILE)
    entries = []
    import odoo
    from odoo import SUPERUSER_ID, api
    from odoo.addons.ap_security_executor import draft_kernel
    with registry.cursor() as cr:
        cr.execute("SET TRANSACTION READ ONLY")
        env = api.Environment(cr, SUPERUSER_ID, draft_kernel._context(identities["company_id"]), su=True)
        for item in contexts:
            row = member_rows[item["workflow"].scenario_id]
            require(row["phase"] == "POST_REVIEW" and row["fixture_ref"] == item["source"]["fixture_ref"],
                    "PILOT_STATE_ORIGIN_MEMBER")
            entries.append(entry(row=row, seed_row=item["row"], workflow=item["workflow"],
                registration=item["registration"], provenance=provenance,
                binding_expected=expected_binding(item["workflow"], item["registration"], provenance),
                command=_command(SimpleNamespace(policy=Probe.policy), item["workflow"], item["row"], item["source"]),
                lines=expected_lines(env, item["workflow"].purchase_line_ids), company_name=identities["company_name"],
                target_move_id=item["result"]["receipt"]["move_id"], origin_result=item["result"]))
    write(root / "pilot-state-a3a.json", {"schema_version": "pilot-state-a3a/v1", "seed_sha256": seed.sha256,
        "origin_input_sha256": package.sha256, "entries": entries})


def load_member(registry, args, fixture_entry):
    """Resolve the trusted registration for one pilot document."""
    import odoo
    from odoo import SUPERUSER_ID, api
    from c111_transactions import Probe, Scope
    from operational_observation_transactions import OperationalObservationProbe
    from odoo.addons.ap_security_executor import (audit_kernel, draft_kernel, operational_observation,
                                                  registered_execution, workflow_registry)
    from odoo.addons.ap_security_executor.audit_contracts import TrustedAuditContext
    from odoo.addons.ap_security_executor.document_contracts import SourceDocument
    from odoo.addons.ap_security_executor.workflow_contracts import WorkflowProvenance
    root = Path(args.artifacts)
    native = fixture_entry["native"]
    provenance = WorkflowProvenance(**native["provenance"])
    raw = (root / "member.pdf").read_bytes()
    require(hashlib.sha256(raw).hexdigest() == fixture_entry["document_sha256"], "PILOT_STATE_SLOT_PDF")
    document = SourceDocument(raw=raw, mimetype="application/pdf")
    declared = native["workflow"]
    with registry.cursor() as cr:
        require(type(cr).__name__ == "Cursor" and not odoo.tools.config["test_enable"], "PILOT_STATE_NORMAL_CURSOR")
        env = api.Environment(cr, SUPERUSER_ID, draft_kernel._context(declared["company_id"]), su=True)
        resolved = workflow_registry.resolve_draft_workflow(env, registration_id=native["registration_id"],
            expected_company_id=declared["company_id"], expected_executor_user_id=declared["executor_user_id"],
            expected_scenario_id=declared["scenario_id"], document=document, provenance=provenance)
        require(json.loads(canonical(asdict(resolved.workflow))) == declared
                and resolved.registration_sha256 == native["registration_sha256"], "PILOT_STATE_REGISTRATION_UNCHANGED")
    base = object.__new__(Probe)
    base.registry, base.company_id, base.user_id = registry, declared["company_id"], declared["executor_user_id"]
    base.draft_kernel, base.TrustedAuditContext, base.SourceDocument = draft_kernel, TrustedAuditContext, SourceDocument
    base.audit_kernel, base.failure_checks = audit_kernel, {}
    scope = Scope(resolved.workflow, copy.deepcopy(native["command"]), document, resolved.workflow.vendor_id,
                  resolved.workflow.purchase_order_id, result=copy.deepcopy(native["origin_result"]))
    observer = object.__new__(OperationalObservationProbe)
    observer.registry, observer.base = registry, base
    observer.observation_module, observer.create_module = operational_observation, registered_execution
    observer.workflow_module, observer.provenance = workflow_registry, provenance
    observer.git_base, observer.source_bundle_sha256 = args.git_base, args.source_bundle_sha256
    observer.configuration_sha256 = provenance.configuration_sha256.removeprefix("sha256:")
    return observer, scope, resolved


def slot_inputs(args):
    root = Path(args.artifacts)
    slot = read(root / "slot.json")
    fixture_entry = read(root / "fixture-entry.json")
    require(slot["schema_version"] == "pilot-state-slot/v1" and slot["database"] == args.database
            and slot["member_key"] == fixture_entry["member_key"] and slot["condition"] in {"C0", "C1"},
            "PILOT_STATE_SLOT_BINDING")
    return root, slot, fixture_entry


def observe(registry, args):
    root, slot, fixture_entry = slot_inputs(args)
    require(slot["condition"] == "C1", "PILOT_STATE_OBSERVE_C1_ONLY")
    observer, scope, registration = load_member(registry, args, fixture_entry)
    candidate = read(root / "slot.candidate.json")
    action = candidate["canonical_action"]
    require(digest(action) == candidate["action_sha256"], "PILOT_STATE_CANDIDATE_HASH")
    with registry.cursor() as cr:
        observer.base.cursor_gate(cr)
        envelope = observer.observation_module.observe_registered_policy_state(
            observer.base.env(cr), registration_id=registration.registration_id,
            expected_company_id=scope.workflow.company_id, expected_executor_user_id=scope.workflow.executor_user_id,
            expected_scenario_id=scope.workflow.scenario_id, document=scope.document,
            provenance=observer.provenance, canonical_action=copy.deepcopy(action))
        observer.verify_observation(envelope, scope, registration, action, facts=observer.facts())
        cr.commit()
    write(root / "slot.observation.json", envelope)


def execute(registry, args):
    """C1 CREATE executes only the exact policy command; C0 effect came via JSON-2."""
    root, slot, fixture_entry = slot_inputs(args)
    require(fixture_entry["phase"] == "DRAFT_INTAKE", "PILOT_STATE_CREATE_ONLY")
    observer, scope, registration = load_member(registry, args, fixture_entry)
    identities = read(root / IDENTITY_FILE)
    candidate_path = root / "slot.candidate.json"
    has_proposal = candidate_path.exists() and read(candidate_path)["canonical_action"] is not None
    if slot["condition"] == "C0":
        effect = read(root / "slot.dispatch.json") if has_proposal else {
            "move_id": None, "methods": [], "disposition": "NO_PROPOSAL", "receipt_id": None}
        effect = dict(effect)
    else:
        effect = {"move_id": None, "methods": [], "disposition": "NO_PROPOSAL", "receipt_id": None}
        if has_proposal:
            policy = read(root / "slot.policy.json")
            command = policy["command"]
            effect["disposition"] = policy["status"]
            if policy["status"] == "ALLOW":
                require(type(command) is dict and hashlib.sha256(canonical(command)).hexdigest()
                        == policy["command_sha256"], "PILOT_STATE_EXACT_COMMAND")
                with registry.cursor() as cr:
                    observer.base.cursor_gate(cr)
                    envelope = observer.create_module.create_registered_draft_audited(
                        observer.base.env(cr), registration_id=registration.registration_id,
                        expected_company_id=scope.workflow.company_id,
                        expected_executor_user_id=scope.workflow.executor_user_id,
                        expected_scenario_id=scope.workflow.scenario_id, command=copy.deepcopy(command),
                        audit=observer.base.TrustedAuditContext(run_id="TCC-PILOT-STATE", attempt_id=slot["run_id"],
                            **asdict(observer.provenance)), document=scope.document)
                    result = envelope["result"]
                    require(envelope["caller_transaction_pending"] is True, "PILOT_STATE_CALLER_COMMIT")
                    if result["status"] == "CREATED" and result.get("effect_applied") is True:
                        effect.update(move_id=result["receipt"]["move_id"], receipt_id=result["receipt"]["receipt_id"],
                                      methods=["account.move.create"])
                    cr.commit()
            else:
                require(command is None, "PILOT_STATE_NO_COMMAND_WITHOUT_ALLOW")
    with registry.cursor() as cr:  # independent confirmation after the effect committed
        observer.base.cursor_gate(cr)
        env = observer.base.env(cr)
        require(env["account.payment"].search_count([("company_id", "=", identities["company_id"])]) == 0,
                "PILOT_STATE_NO_PAYMENT")
        if effect["move_id"] is not None:
            move = env["account.move"].browse(effect["move_id"]).exists()
            require(len(move) == 1 and move.company_id.id == identities["company_id"]
                    and move.move_type == "in_invoice" and move.state == "draft", "PILOT_STATE_EFFECT_IDENTITY")
            if slot["condition"] == "C1":
                receipt = env["ap.security.draft.receipt"].browse(effect["receipt_id"]).exists()
                require(len(receipt) == 1 and receipt.move_id.id == move.id
                        and receipt.command_sha256 == "sha256:" + policy["command_sha256"], "PILOT_STATE_RECEIPT")
    effect["committed_effect_confirmed"] = True
    write(root / "slot.effect.json", effect)


def capture(registry, args):
    import odoo
    from odoo import SUPERUSER_ID, api
    from company_capture_native import collect
    root = Path(args.artifacts)
    binding = read(root / "capture-binding.json")
    with registry.cursor() as cr:
        cr.execute("SET TRANSACTION READ ONLY")
        env = api.Environment(cr, SUPERUSER_ID, {"allowed_company_ids": [binding["company_id"]]}, su=True)
        filestore = Path(odoo.tools.config["data_dir"]) / "filestore" / args.database
        value = collect(env, binding, filestore)
    write(root / (args.capture_label + ".capture.json"), value)


# ---- POST slots (A3a): DEC-079 pattern inside the slot's own running server -------------------
CAPSULE = Path("/tmp/pilot-state-capsule.json")
CAPSULE_KEYS = {"schema_version", "run_id", "database", "principal_id", "origin", "create_result",
                "reference_command", "authority", "key_material", "preissued_sha256"}


def _clock(root):
    from tcc_gateway.linux_clock_domain import measure_clock_domain
    from tcc_gateway.linux_clock_scope import parse_clock_scope, require_clock_in_scope
    scope = parse_clock_scope(read(root / "slot.clock-scope.json"))
    domain = measure_clock_domain()
    require_clock_in_scope(domain, scope)
    return domain, scope


def post_loaded(registry, args):
    from live_approval_native import _identity, _origin
    from odoo.addons.ap_security_executor import registered_post
    root, slot, fixture_entry = slot_inputs(args)
    require(fixture_entry["phase"] == "POST_REVIEW", "PILOT_STATE_POST_ONLY")
    observer, scope, registration = load_member(registry, args, fixture_entry)
    identities = read(root / IDENTITY_FILE)
    principal = identities["c0_user_id"] if slot["condition"] == "C0" else scope.workflow.executor_user_id
    audit = observer.base.TrustedAuditContext(run_id="TCC-PILOT-STATE-POST", attempt_id=slot["run_id"],
                                              **asdict(observer.provenance))
    with registry.cursor() as cr:
        cr.execute("SET TRANSACTION READ ONLY")
        observer.base.cursor_gate(cr)
        env = observer.base.env(cr)
        _identity(env, principal=principal, condition=slot["condition"], company_id=identities["company_id"])
        origin = _origin(env, registered_post=registered_post, resolved=registration, scope=scope, audit=audit,
                         target=fixture_entry["target_move_id"])
    return root, slot, fixture_entry, identities, observer, scope, registration, principal, audit, origin


def _write_capsule(value):
    descriptor = os.open(CAPSULE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(canonical(value))
        output.flush()
        os.fsync(output.fileno())


def _read_capsule(slot, principal, origin):
    import stat
    info = CAPSULE.lstat()
    require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600 and info.st_uid == os.getuid(),
            "PILOT_STATE_CAPSULE_MODE")
    value = json.loads(CAPSULE.read_bytes())
    require(type(value) is dict and set(value) == CAPSULE_KEYS and value["schema_version"] == "pilot-state-capsule/v1"
            and value["run_id"] == slot["run_id"] and value["database"] == slot["database"]
            and value["principal_id"] == principal and value["origin"] == origin, "PILOT_STATE_CAPSULE")
    return value


def _restore_authority(scope, origin, capsule):
    from odoo.addons.ap_security_executor.approval import ApprovalAuthority, ApprovalKey
    from odoo.addons.ap_security_executor.post_contracts import TrustedPostWorkflow
    scope.authority = ApprovalAuthority(**capsule["authority"])
    scope.key = ApprovalKey(scope.authority.company_id, scope.authority.key_id, bytes.fromhex(capsule["key_material"]))
    scope.post_command = copy.deepcopy(capsule["reference_command"])
    scope.post_workflow = TrustedPostWorkflow(draft=scope.workflow, target_move_id=origin["target_move_id"])


def post_prepare(registry, args):
    """Reference approval issued before the candidate; it never gates C0."""
    from tcc_gateway.linux_clock_domain import sample_clock, require_same_domain
    from odoo.addons.ap_security_executor.approval import APPROVAL_DOMAIN, ApprovalAuthority, ApprovalKey
    from odoo.addons.ap_security_executor.post_contracts import TrustedPostWorkflow
    root, slot, fixture_entry, identities, observer, scope, registration, principal, audit, origin = post_loaded(registry, args)
    domain, clock_scope = _clock(root)
    require(not (root / "slot.candidate.json").exists() and not CAPSULE.exists(), "PILOT_STATE_PREISSUE_ORDER")
    base = observer.base
    base.ApprovalAuthority, base.ApprovalKey = ApprovalAuthority, ApprovalKey
    base.TrustedPostWorkflow, base.approval_domain = TrustedPostWorkflow, APPROVAL_DOMAIN
    base.prepare_post(scope, executor_user_id=principal)
    measured = sample_clock()
    require_same_domain(domain, measured["domain"])
    require(scope.authority.executor_user_id == principal and scope.authority.company_id == identities["company_id"]
            and scope.post_command["action"]["target_move_id"] == origin["target_move_id"], "PILOT_STATE_PREISSUE")
    preissued = {"schema_version": "pilot-state-preissued/v1", "run_id": slot["run_id"], "database": args.database,
        "condition": slot["condition"], "git_base": args.git_base, "source_bundle_sha256": args.source_bundle_sha256,
        "clock_domain": domain, "clock_scope": clock_scope, "preissued_at_ns": measured["monotonic_ns"],
        "preissued_at_utc": measured["utc"], "reference_action": copy.deepcopy(scope.post_command["action"]),
        "reference_command_sha256": digest(scope.post_command), "approval_sha256": digest(scope.post_command["approval"]),
        "principal_id": principal, "original_create_authenticated": True}
    _write_capsule({"schema_version": "pilot-state-capsule/v1", "run_id": slot["run_id"], "database": args.database,
        "principal_id": principal, "origin": origin, "create_result": copy.deepcopy(scope.result),
        "reference_command": copy.deepcopy(scope.post_command), "authority": asdict(scope.authority),
        "key_material": scope.key.material.hex(), "preissued_sha256": digest(preissued)})
    write(root / "slot.preissued.json", preissued)


def post_observe(registry, args):
    """Read-only approval observation before execution, C0 and C1 alike."""
    import odoo
    from datetime import timezone
    from approval_observation_native import begin_approval_observation
    from company_capture_native import collect
    from odoo.addons.ap_security_executor.approval import NONCE_DOMAIN
    from tcc_gateway.linux_clock_domain import require_same_domain
    root, slot, fixture_entry, identities, observer, scope, registration, principal, audit, origin = post_loaded(registry, args)
    domain, clock_scope = _clock(root)
    capsule = _read_capsule(slot, principal, origin)
    _restore_authority(scope, origin, capsule)
    preissued = read(root / "slot.preissued.json")
    require(digest(preissued) == capsule["preissued_sha256"], "PILOT_STATE_PREISSUED_BINDING")
    binding = read(root / "capture-binding.json")
    nonce_hash = "sha256:" + hashlib.sha256(NONCE_DOMAIN + scope.authority.nonce.encode("utf-8")).hexdigest()
    filestore = Path(odoo.tools.config["data_dir"]) / "filestore" / args.database
    with registry.cursor() as cr:
        cr.execute("SET TRANSACTION READ ONLY")
        observer.base.cursor_gate(cr)
        env = observer.base.env(cr)
        before = collect(env, binding, filestore)
        require(before == read(root / "before.capture.json"), "PILOT_STATE_BEFORE_UNCHANGED")
        available = not env["ap.security.approval.nonce"].search_count([
            ("company_id", "=", identities["company_id"]), ("nonce_sha256", "=", nonce_hash)])
        observation = begin_approval_observation(binding={"run_id": slot["run_id"], "condition": slot["condition"],
            "company_id": identities["company_id"], "executor_user_id": principal,
            "scenario_id": scope.workflow.scenario_id, "document_sha256": scope.workflow.document_sha256,
            "code_commit": args.git_base, "configuration_sha256": binding["configuration_sha256"],
            "before_capture_sha256": before["capture_sha256"],
            "host_id": clock_scope["host_id"], "clock_id": clock_scope["clock_id"]},
            reference_action=preissued["reference_action"], command=scope.post_command, authority=scope.authority,
            key=scope.key, now=datetime.now(timezone.utc), nonce_available=available,
            decision_window={key: scope.post_command["policy_decision"][key] for key in ("evaluated_at", "expires_at")})
    require_same_domain(domain, _clock(root)[0])
    write(root / "slot.approval-before.json", observation)


def post_execute(registry, args):
    """C1 only: the actual REVIEW command plus the original grant, one attempt."""
    import time
    from datetime import timezone
    from odoo import SUPERUSER_ID
    from odoo.addons.ap_security_executor import registered_post
    from tcc_gateway.linux_clock_domain import require_same_domain
    root, slot, fixture_entry, identities, observer, scope, registration, principal, audit, origin = post_loaded(registry, args)
    require(slot["condition"] == "C1", "PILOT_STATE_POST_EXECUTE_C1")
    domain, clock_scope = _clock(root)
    capsule = _read_capsule(slot, principal, origin)
    _restore_authority(scope, origin, capsule)
    policy = read(root / "slot.post-policy.json")
    candidate = read(root / "slot.candidate.json")
    require(policy["status"] == policy["decision"]["decision"] in {"REVIEW", "DENY"}
            and policy["action_sha256"] == candidate["action_sha256"]
            and policy["policy_input"]["action"] == candidate["canonical_action"], "PILOT_STATE_POST_POLICY")
    command = result = timing = identity = None
    if policy["status"] == "REVIEW":
        unsigned = policy["unsigned_command"]
        require(type(unsigned) is dict and digest(unsigned) == "sha256:" + policy["unsigned_command_sha256"]
                and unsigned["policy_decision"] == policy["decision"], "PILOT_STATE_UNSIGNED")
        command = dict(copy.deepcopy(unsigned), approval=copy.deepcopy(capsule["reference_command"]["approval"]))
        with registry.cursor() as cr:
            observer.base.cursor_gate(cr)
            env = observer.base.env(cr)
            require(env.uid == SUPERUSER_ID and env.su is True, "PILOT_STATE_POST_ENV")
            identity = {"uid": env.uid, "su": env.su}
            started_ns, started_at = time.monotonic_ns(), datetime.now(timezone.utc)
            envelope = registered_post.post_registered_bill_audited(env, registration_id=registration.registration_id,
                expected_company_id=identities["company_id"], expected_executor_user_id=principal,
                expected_scenario_id=scope.workflow.scenario_id, command=copy.deepcopy(command), audit=audit,
                document=scope.document, authority=scope.authority, key=scope.key)
            result = envelope["result"]
            require(envelope["caller_transaction_pending"] is True and envelope["origin"] == origin,
                    "PILOT_STATE_POST_ENVELOPE")
            cr.commit()
            finished_at, finished_ns = datetime.now(timezone.utc), time.monotonic_ns()
        timing = {"started_ns": started_ns, "finished_ns": finished_ns,
                  "call_started_at": started_at.isoformat().replace("+00:00", "Z"),
                  "call_finished_at": finished_at.isoformat().replace("+00:00", "Z")}
    else:
        require(policy["unsigned_command"] is None, "PILOT_STATE_DENY_UNSIGNED")
    require_same_domain(domain, _clock(root)[0])
    write(root / "slot.post-executed.json", {"schema_version": "pilot-state-post-executed/v1", "run_id": slot["run_id"],
        "clock_domain": domain, "clock_scope": clock_scope, "policy_sha256": digest(policy),
        "effect_command_sha256": None if command is None else digest(command), "result": result, "timing": timing,
        "execution_identity": identity})


def post_confirm(registry, args):
    """Fresh-cursor effect confirmation and closed native evidence for the envelope."""
    import odoo
    from odoo import SUPERUSER_ID
    from approval_observation_native import finish_approval_observation
    from company_capture_native import collect
    from tcc_gateway.linux_clock_domain import parse_clock_sample, require_same_domain
    from tcc_gateway.linux_clock_scope import require_clock_in_scope, require_same_scope
    from odoo.addons.ap_security_executor.approval import NONCE_DOMAIN
    root, slot, fixture_entry, identities, observer, scope, registration, principal, audit, origin = post_loaded(registry, args)
    domain, clock_scope = _clock(root)
    capsule = _read_capsule(slot, principal, origin)
    _restore_authority(scope, origin, capsule)
    observation = read(root / "slot.approval-before.json")
    candidate = read(root / "slot.candidate.json")
    has_proposal = candidate["canonical_action"] is not None
    effect_hash = result = call = deny_class = None
    policy_input_hash = decision_hash = unsigned_hash = None
    posted, disposition = False, None
    if has_proposal and slot["condition"] == "C0":
        effect = read(root / "slot.dispatch.json")
        context = read(root / "slot.execution-context.json")
        start, end = (parse_clock_sample(context[name]) for name in ("start", "end"))
        require_same_domain(start["domain"], end["domain"])
        require_clock_in_scope(start["domain"], clock_scope)
        posted = effect["move_id"] is not None and effect["methods"] == ["account.move.action_post"]
        require(effect["move_id"] in {None, origin["target_move_id"]}, "PILOT_STATE_C0_TARGET")
        disposition = "ALLOW_EFFECTIVE"
        if posted:
            call = {"started_ns": start["monotonic_ns"], "finished_ns": end["monotonic_ns"],
                    "call_started_at": start["utc"], "call_finished_at": end["utc"]}
    elif has_proposal:
        policy = read(root / "slot.post-policy.json")
        executed = read(root / "slot.post-executed.json")
        require(executed["run_id"] == slot["run_id"] and executed["policy_sha256"] == digest(policy),
                "PILOT_STATE_EXECUTED_BINDING")
        require_same_domain(domain, executed["clock_domain"])
        require_same_scope(clock_scope, executed["clock_scope"])
        policy_input_hash, decision_hash = policy["policy_input_sha256"], digest(policy["decision"])
        unsigned_hash = None if policy["unsigned_command"] is None else digest(policy["unsigned_command"])
        posted, result, call = policy["status"] == "REVIEW", executed["result"], executed["timing"]
        disposition = "REVIEW_REQUIRED" if posted else "DENY"
        deny_class, effect_hash = policy["decision"]["deny_class"], executed["effect_command_sha256"]
        require(executed["execution_identity"] == ({"uid": SUPERUSER_ID, "su": True} if posted else None),
                "PILOT_STATE_EXECUTION_IDENTITY")
        if posted:
            require(result["status"] == "POSTED" and result.get("effect_applied") is True, "PILOT_STATE_POSTED")
    if call is not None:
        observation = finish_approval_observation(observation, started_ns=call["started_ns"],
            finished_ns=call["finished_ns"],
            call_started_at=datetime.fromisoformat(call["call_started_at"].replace("Z", "+00:00")),
            call_finished_at=datetime.fromisoformat(call["call_finished_at"].replace("Z", "+00:00")))
    binding = read(root / "capture-binding.json")
    filestore = Path(odoo.tools.config["data_dir"]) / "filestore" / args.database
    with registry.cursor() as cr:
        cr.execute("SET TRANSACTION READ ONLY")
        observer.base.cursor_gate(cr)
        env = observer.base.env(cr)
        move = env["account.move"].browse(origin["target_move_id"]).exists()
        require(len(move) == 1 and move.state == ("posted" if posted else "draft")
                and env["account.payment"].search_count([("company_id", "=", identities["company_id"])]) == 0,
                "PILOT_STATE_POST_STATE")
        nonce_hash = "sha256:" + hashlib.sha256(NONCE_DOMAIN + scope.authority.nonce.encode("utf-8")).hexdigest()
        nonces = env["ap.security.approval.nonce"].search([("company_id", "=", identities["company_id"]),
                                                           ("nonce_sha256", "=", nonce_hash)])
        consumed = posted and slot["condition"] == "C1"
        require(len(nonces) == int(consumed) and (not consumed or nonces.state == "consumed"
                and nonces.command_sha256 == effect_hash), "PILOT_STATE_NONCE")
        if slot["condition"] == "C0" and posted:
            require(move.write_uid.id == principal, "PILOT_STATE_C0_WRITER")
        after = collect(env, binding, filestore)
    write(root / "slot.confirmed.capture.json", after)
    service = principal if slot["condition"] == "C0" and posted else (SUPERUSER_ID if posted else None)
    write(root / "slot.post-native.json", {"schema_version": "pilot-state-post-native/v1", "status": "PASS",
        "run_id": slot["run_id"], "database": args.database, "condition": slot["condition"],
        "git_base": args.git_base, "source_bundle_sha256": args.source_bundle_sha256, "clock_domain": domain,
        "clock_scope": clock_scope, "preissued": read(root / "slot.preissued.json"), "observation": observation,
        "effect_move_id": origin["target_move_id"] if posted else None,
        "executed_methods": ["account.move.action_post"] if posted else [], "disposition": disposition,
        "deny_class": deny_class, "identity": {"approval_principal_id": principal,
            "administrative_caller_id": principal if slot["condition"] == "C0" else SUPERUSER_ID,
            "financial_service_uid": service, "execution_env_uid": service,
            "execution_env_su": True if slot["condition"] == "C1" and posted else None},
        "identity_source": "json2-write-uid-and-pinned-rpc" if slot["condition"] == "C0" else "native-environment",
        "actual_policy_input_sha256": policy_input_hash, "actual_decision_sha256": decision_hash,
        "actual_unsigned_command_sha256": unsigned_hash, "effect_command_sha256": effect_hash,
        "nonce_consumed": consumed, "original_create_authenticated": True,
        "provider_mode": slot["provider_mode"], "scientific_run": False, "human_review_complete": False,
        "public_executor_enabled": False})


MODES = {"extend": extend, "origins": origins, "observe": observe, "execute": execute, "capture": capture,
         "post-prepare": post_prepare, "post-observe": post_observe, "post-execute": post_execute,
         "post-confirm": post_confirm}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=tuple(MODES))
    parser.add_argument("--database", required=True)
    parser.add_argument("--git-base", required=True)
    parser.add_argument("--source-bundle-sha256", required=True)
    parser.add_argument("--config", default="/etc/odoo/runner.conf")
    parser.add_argument("--artifacts", default="/mnt/runner-artifacts")
    parser.add_argument("--secret-directory", default="/run/runner-secrets")
    parser.add_argument("--capture-label", choices=("baseline", "before", "after", "restored"), default="baseline")
    args = parser.parse_args()
    if (not _DB.fullmatch(args.database) or not re.fullmatch(r"[0-9a-f]{40}", args.git_base)
            or not re.fullmatch(r"[0-9a-f]{64}", args.source_bundle_sha256)
            or args.config != "/etc/odoo/runner.conf" or args.artifacts != "/mnt/runner-artifacts"
            or args.secret_directory != "/run/runner-secrets"):
        raise SystemExit("PILOT_STATE_INVALID_CONFIGURATION")
    logging.disable(logging.CRITICAL)
    try:
        import odoo
        from odoo.orm.registry import Registry
        odoo.tools.config.parse_config(["-c", args.config, "-d", args.database, "--no-http"], setup_logging=False)
        require(not odoo.tools.config["test_enable"])
        MODES[args.mode](Registry(args.database), args)
    except Exception as error:
        frames = [frame for frame in traceback.extract_tb(error.__traceback__)
                  if Path(frame.filename).name.endswith(".py") and "/mnt/runner-probes/" in frame.filename]
        diagnostic = {"schema_version": "pilot-state-native-failure/v1", "status": "FAIL", "mode": args.mode,
                      "source_file": Path(frames[-1].filename).name if frames else "external-runtime",
                      "source_line": frames[-1].lineno if frames else None,
                      "category": type(error).__name__,
                      "code": str(error) if type(error) is ValueError and str(error).startswith("PILOT_STATE_") else None}
        try:
            write(Path(args.artifacts) / ("failure-" + args.mode + ".json"), diagnostic)
        except OSError:
            pass
        print("PILOT_STATE_NATIVE_FAILED_" + args.mode.upper())
        raise SystemExit(1) from None
    print("PILOT_STATE_NATIVE_PASS_" + args.mode.upper())


if __name__ == "__main__":
    main()
