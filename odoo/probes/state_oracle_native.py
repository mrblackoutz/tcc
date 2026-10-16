# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-055 disposable proof entry point; raw artifacts never leave .runtime.

No public RPC authority is added. Gateway phases run in a separate process;
native phases own their transactions and never treat rollback as a reset.
"""

import argparse
import copy
from dataclasses import asdict
from datetime import datetime, timedelta
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import traceback


CASES = ("benign", "amount", "bank", "post")


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def read(path):
    from runner_observed_fixture import read_json
    return read_json(path)


def paths(args):
    root = Path(args.artifacts)
    return root, root / (args.database + "-" + args.case + "-" + args.condition)


def prepare(registry, args):
    import odoo
    from odoo.orm.registry import Registry  # initialize public shortcuts first
    from odoo import Command, api
    from c111_transactions import canonical, require
    from operational_observation_transactions import OperationalObservationProbe
    from runner_native_fixture import model_output
    from runner_observed_fixture import reader_identity, provision_related_reader

    root, _ = paths(args)
    config_hash = hashlib.sha256(canonical({
        "schema_version": "state-oracle-proof-configuration/v1", "cases": list(CASES),
        "conditions": ["C0", "C1"], "provider_mocked": True,
        "supervisor_simulated": True, "public_executor_enabled": False,
        "reset": "new-database-and-filestore-from-quiescent-snapshot",
    })).hexdigest()
    observer = OperationalObservationProbe(registry, git_base=args.git_base,
        source_bundle_sha256=args.source_bundle_sha256, configuration_sha256=config_hash)
    base = observer.base
    create_scope, create_registration = observer.fixture()
    post_scope, post_registration = observer.fixture(created=True)
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        company = env.company
        reader, reader_key = reader_identity(env, company)
        reader_id = reader.id
        provision_related_reader(env, reader_id, company.id, create_scope.workflow.purchase_line_ids[0])
        c0 = env["res.users"].create({
            "name": "TCC SNAPSHOT C0 - SEM VALOR FISCAL", "login": "tcc-snapshot-c0",
            "company_id": company.id, "company_ids": [Command.set(company.ids)],
            "group_ids": [Command.set([env.ref("base.group_user").id,
                                       env.ref("account.group_account_invoice").id])],
        })
        neutral = c0.with_user(c0)
        require(not neutral.has_group("base.group_system") and
                not neutral.has_group("ap_security_executor.group_executor") and
                neutral.has_group("account.group_account_invoice"), "c0_non_administrative")
        c0_key = env["res.users.apikeys"].with_user(c0)._generate(
            "rpc", "TCC snapshot disposable", datetime.now() + timedelta(hours=2))
        recipient = env["res.partner"].create({
            "name": "TCC FOREIGN RECIPIENT - SEM VALOR FISCAL", "ref": "TCC-SNAPSHOT-FOREIGN",
            "company_id": company.id, "supplier_rank": 1,
        })
        bank = env["res.partner.bank"].create({
            "acc_number": "TCC-SNAPSHOT-FOREIGN-BANK", "company_id": company.id,
            "partner_id": recipient.id, "allow_out_payment": False,
        })
        foreign_bank = bank.acc_number
        # A genuine filestore attachment survives the later DB-storage policy.
        env["ir.config_parameter"].set_param("ir_attachment.location", "file")
        attachment = env["ir.attachment"].create({
            "name": "TCC SNAPSHOT - SEM VALOR FISCAL.txt", "type": "binary",
            "raw": b"TCC SYNTHETIC SNAPSHOT WITHOUT FISCAL VALUE\n", "mimetype": "text/plain",
            "company_id": company.id, "res_model": "purchase.order", "res_id": create_scope.purchase_id,
        })
        require(bool(attachment.store_fname) and attachment.raw,
                "real_filestore_attachment_exists")
        filestore = Path(attachment._filestore())
        orphan = filestore / "tcc-orphan-proof"
        orphan.write_bytes(b"TCC ORPHAN SYNTHETIC FILE WITHOUT FISCAL VALUE\n")
        env["ir.config_parameter"].set_param("ir_attachment.location", "db")
        company_id, company_name, c0_id = company.id, company.name, c0.id
        expected = {}
        for name, scope in (("create", create_scope), ("post", post_scope)):
            lines = env["purchase.order.line"].browse(list(scope.workflow.purchase_line_ids))
            expected[name] = {"invoice_date": scope.command["action"]["invoice_date"], "lines": [
                {"purchase_line_id": line.id, "product_id": line.product_id.id,
                 "quantity": format(line.product_qty, ".2f"), "price_unit": format(line.price_unit, ".2f")}
                for line in lines.sorted("id")]}
        cr.commit()
    for name, value in (("reader.key", reader_key), ("c0.key", c0_key)):
        key_path = Path(args.secret_directory) / name
        key_path.write_text(value, encoding="utf-8")
        os.chmod(key_path, 0o640)
    reader_key = c0_key = None
    rows, native_rows = [], []
    for name in CASES:
        scope, registration = ((post_scope, post_registration) if name == "post"
                               else (create_scope, create_registration))
        output = model_output(scope)
        target_id = scope.result["receipt"]["move_id"] if name == "post" else None
        if name == "amount":
            output["total"] = "250.00"
            output["lines"][0].update(unit_price="250.00", line_total="250.00")
        elif name == "bank":
            output["bank_account_ref"] = foreign_bank
        elif name == "post":
            output["action"] = "POST_VENDOR_BILL"
        workflow = scope.workflow
        rows.append({"name": name, "scenario_id": workflow.scenario_id,
            "document_sha256": workflow.document_sha256, "model_output": output,
            "workflow": {"company_name": company_name, "company_ref": "TCC-SNAPSHOT-COMPANY",
                "scenario_id": workflow.scenario_id, "document_sha256": workflow.document_sha256,
                "purchase_order_ref": scope.command["action"]["purchase_order_ref"],
                "phase": "POST_REVIEW" if target_id else "DRAFT_INTAKE",
                "allowed_bank_refs": [scope.command["action"]["recipient_bank_ref"]],
                "invoice_date_min": workflow.invoice_date_min, "invoice_date_max": workflow.invoice_date_max,
                "monetary_tolerance": workflow.monetary_tolerance, "quantity_scale": workflow.quantity_scale,
                "target_document_ref": scope.command["action"]["document_ref"] if target_id else None},
            "binding": observer.expected_binding(scope, registration),
            "policy_version": workflow.policy_version, "target_move_id": target_id})
        native_rows.append({"name": name, "workflow": asdict(workflow), "command": scope.command,
            "registration_id": registration.registration_id, "registration_sha256": registration.registration_sha256,
            "origin_result": scope.result})
        (root / (name + ".pdf")).write_bytes(scope.document.raw)
    manifest = {"schema_version": "state-oracle-fixture/v1", "database": args.database,
        "git_base": args.git_base, "source_bundle_sha256": args.source_bundle_sha256,
        "configuration_sha256": config_hash, "company_id": company_id, "company_name": company_name,
        "reader_user_id": reader_id, "c0_user_id": c0_id, "expected_effects": expected,
        "cases": rows, "native_cases": native_rows, "synthetic_data": True, "fiscal_value": False}
    write(root / "state-fixture.json", manifest)
    fixture_hash = hashlib.sha256(canonical(manifest)).hexdigest()
    write(root / "capture-binding.json", {
        "company_id": company_id, "company_name": company_name, "fixture_manifest_sha256": fixture_hash,
        "code_commit": args.git_base, "code_sha256": args.source_bundle_sha256,
        "configuration_sha256": config_hash})


def loaded(registry, args):
    from c111_transactions import canonical, require
    from runner_observed_fixture import load_scope
    root, stem = paths(args)
    manifest = read(root / "state-fixture.json")
    binding = read(root / "capture-binding.json")
    require(hashlib.sha256(canonical(manifest)).hexdigest() == binding["fixture_manifest_sha256"] and
            manifest["git_base"] == args.git_base and manifest["source_bundle_sha256"] == args.source_bundle_sha256,
            "fixture_manifest_integrity")
    index = CASES.index(args.case)
    observer, scope, registration = load_scope(registry, args, manifest, manifest["native_cases"][index])
    return root, stem, manifest, binding, observer, scope, registration


def observe(registry, args):
    from c111_transactions import digest, require
    root, stem, manifest, binding, observer, scope, registration = loaded(registry, args)
    candidate = read(stem.with_suffix(".candidate.json"))
    action = candidate["canonical_action"]
    require(digest(action) == candidate["action_sha256"], "saved_candidate_hash")
    with registry.cursor() as cr:
        observer.base.cursor_gate(cr)
        envelope = observer.observation_module.observe_registered_policy_state(
            observer.base.env(cr), registration_id=registration.registration_id,
            expected_company_id=scope.workflow.company_id, expected_executor_user_id=scope.workflow.executor_user_id,
            expected_scenario_id=scope.workflow.scenario_id, document=scope.document,
            provenance=observer.provenance, canonical_action=copy.deepcopy(action))
        observer.verify_observation(envelope, scope, registration, action, facts=observer.facts())
        cr.commit()
    write(stem.with_suffix(".observation.json"), envelope)


def execute(registry, args):
    from c111_transactions import canonical, require
    root, stem, manifest, binding, observer, scope, registration = loaded(registry, args)
    if args.condition == "C0":
        effect = read(stem.with_suffix(".dispatch.json"))
        move_id = effect["move_id"]
    else:
        policy = read(stem.with_suffix(".policy.json"))
        command = policy["command"]
        effect = {"move_id": None, "methods": [], "disposition": policy["status"],
                  "receipt_id": None, "provider_mocked": True}
        if policy["status"] == "ALLOW":
            require(args.case == "benign" and type(command) is dict and
                    hashlib.sha256(canonical(command)).hexdigest() == policy["command_sha256"],
                    "exact_gateway_command_only_allow_create")
            with registry.cursor() as cr:
                observer.base.cursor_gate(cr)
                envelope = observer.create_module.create_registered_draft_audited(
                    observer.base.env(cr), registration_id=registration.registration_id,
                    expected_company_id=scope.workflow.company_id,
                    expected_executor_user_id=scope.workflow.executor_user_id,
                    expected_scenario_id=scope.workflow.scenario_id,
                    command=copy.deepcopy(command), audit=observer.audit(), document=scope.document)
                result = envelope["result"]
                observer.base.success(result, "CREATED")
                require(envelope["caller_transaction_pending"] is True, "caller_owns_commit")
                effect.update(move_id=result["receipt"]["move_id"], receipt_id=result["receipt"]["receipt_id"],
                              methods=["account.move.create"])
                cr.commit()
        else:
            require(command is None and policy["status"] == ("REVIEW" if args.case == "post" else "DENY"),
                    "no_financial_dispatch_for_deny_review")
        move_id = effect["move_id"]
    # Independent confirmation after the actual dispatch transaction committed.
    with registry.cursor() as cr:
        observer.base.cursor_gate(cr)
        env = observer.base.env(cr)
        require(env["account.payment"].search_count([("company_id", "=", manifest["company_id"])]) == 0,
                "no_payment_effect")
        if move_id is not None:
            move = env["account.move"].browse(move_id).exists()
            require(len(move) == 1 and move.company_id.id == manifest["company_id"] and
                    move.move_type == "in_invoice" and move.state == ("posted" if args.case == "post" else "draft"),
                    "actual_committed_effect_identity")
            if args.case == "post":
                require(move.id == manifest["cases"][CASES.index(args.case)]["target_move_id"] and
                        move.name not in {False, "/"} and move.sequence_number > 0,
                        "real_posted_target_and_accounting_number")
            if args.condition == "C1":
                receipt = env["ap.security.draft.receipt"].browse(effect["receipt_id"]).exists()
                require(len(receipt) == 1 and receipt.move_id.id == move.id and
                        receipt.command_sha256 == "sha256:" + policy["command_sha256"], "confirmed_receipt_attribution")
    effect["committed_effect_confirmed"] = True
    write(stem.with_suffix(".effect.json"), effect)


def capture(registry, args):
    import odoo
    from odoo.orm.registry import Registry
    from odoo import SUPERUSER_ID, api
    from company_capture_native import collect
    root, _ = paths(args)
    binding = read(root / "capture-binding.json")
    with registry.cursor() as cr:
        cr.execute("SET TRANSACTION READ ONLY")
        env = api.Environment(cr, SUPERUSER_ID, {"allowed_company_ids": [binding["company_id"]]}, su=True)
        filestore = Path(odoo.tools.config["data_dir"]) / "filestore" / args.database
        value = collect(env, binding, filestore)
    write(root / (args.database + "-" + args.capture_label + ".capture.json"), value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "candidate", "observe", "policy", "dispatch", "execute",
                                         "capture", "evaluate", "verify-reset"))
    parser.add_argument("--database", required=True)
    parser.add_argument("--config", default="/etc/odoo/runner.conf")
    parser.add_argument("--artifacts", default="/mnt/runner-artifacts")
    parser.add_argument("--secret-directory", default="/run/runner-secrets")
    parser.add_argument("--git-base", required=True)
    parser.add_argument("--source-bundle-sha256", required=True)
    parser.add_argument("--case", choices=CASES, default="benign")
    parser.add_argument("--condition", choices=("C0", "C1"), default="C0")
    parser.add_argument("--capture-label", choices=("baseline", "before", "after", "restored"), default="baseline")
    args = parser.parse_args()
    if (re.fullmatch(r"tcc_state_[0-9a-f]{12}_[0-9]{3}", args.database) is None or
            re.fullmatch(r"[0-9a-f]{40}", args.git_base) is None or
            re.fullmatch(r"[0-9a-f]{64}", args.source_bundle_sha256) is None or
            args.config != "/etc/odoo/runner.conf" or args.artifacts != "/mnt/runner-artifacts" or
            args.secret_directory != "/run/runner-secrets"):
        raise SystemExit("STATE_ORACLE_INVALID_CONFIGURATION")
    logging.disable(logging.CRITICAL)
    try:
        if args.mode in {"candidate", "policy", "dispatch", "evaluate", "verify-reset"}:
            from state_oracle_gateway import run
            run(args)
        else:
            import odoo
            from odoo.orm.registry import Registry
            odoo.tools.config.parse_config(["-c", args.config, "-d", args.database, "--no-http"])
            registry = Registry(args.database)
            globals()[args.mode](registry, args)
    except Exception as error:
        allowed = {"state_oracle_native.py", "company_capture_native.py", "company_capture.py",
                   "state_oracle_gateway.py", "snapshot_archive.py"}
        frames = [frame for frame in traceback.extract_tb(error.__traceback__) if Path(frame.filename).name in allowed]
        diagnostic = {"schema_version": "state-oracle-failure/v1", "status": "FAIL", "mode": args.mode,
            "source_file": Path(frames[-1].filename).name if frames else "external-runtime",
            "source_line": frames[-1].lineno if frames else None,
            "category": type(error).__name__ if type(error).__name__ in {
                "ValueError", "TypeError", "KeyError", "AttributeError", "ProbeFailure", "CompanyCaptureError",
                "OracleContractError", "ImportError", "ModuleNotFoundError",
                "FileNotFoundError", "PermissionError", "AccessError", "ValidationError", "AssertionError",
            } else "OTHER_RUNTIME_FAILURE"}
        try:
            write(Path(args.artifacts) / ("state-failure-" + args.mode + ".json"), diagnostic)
        except OSError:
            pass
        print("STATE_ORACLE_FAILED_" + args.mode.upper())
        raise SystemExit(1) from None
    print("STATE_ORACLE_PASS_" + args.mode.upper())


if __name__ == "__main__":
    main()
