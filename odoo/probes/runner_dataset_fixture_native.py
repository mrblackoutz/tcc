# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-066 opt-in native preparation/confirmation, never financial dispatch.

Only two existing development fixtures are read. Their independent legitimate
commands precede any provider stage. Raw artifacts remain in the ignored lab.
"""

from copy import deepcopy
import json
from pathlib import Path
import re

import odoo
from odoo.orm.registry import Registry

from c111_transactions import canonical, require
from runner_observed_fixture import (
    assert_related_reader, load_inputs, load_scope, read_json, write_json,
)


CASES = ("observed_create_benign", "observed_post_without_approval")
PROVENANCE = ("git_base", "source_bundle_sha256", "configuration_sha256")


def normalized(value):
    # The native projection includes dates. Preserve the existing canonical
    # representation, so a fresh native read compares to saved JSON exactly.
    return json.loads(canonical(value))


def top(args, manifest, schema):
    require(manifest["git_base"] == args.git_base and
            manifest["source_bundle_sha256"] == args.source_bundle_sha256,
            "dataset_fixture_source_binding")
    return {"schema_version": schema, "status": "PASS",
            **{name: manifest[name] for name in PROVENANCE}}


def selected_inputs(registry, args):
    artifacts, manifest, native = load_inputs(args)
    require(tuple(row["name"] for row in native["cases"] if row["name"] in CASES) == CASES,
            "dataset_fixture_two_independent_native_cases")
    return artifacts, manifest, native


def check_reader(observer, manifest):
    with observer.registry.cursor() as cr:
        observer.base.cursor_gate(cr)
        assert_related_reader(observer.base.env(cr), manifest["reader_user_id"], manifest["company_id"])


def prepare_currency(registry, base):
    """Opt-in BRL setup before any financial fixture, not currency conversion."""
    from odoo.addons.ap_security_executor.identity import (
        EXPLICIT_GROUPS, EFFECTIVE_GROUPS, assert_executor_identity,
    )
    with registry.cursor() as cr:
        base.cursor_gate(cr)
        env = base.env(cr)
        require(re.fullmatch(r"tcc_runner_[0-9a-f]{12}", cr.dbname) is not None,
                "dataset_fixture_disposable_database_only")
        company = env["res.company"].browse(base.company_id).exists()
        require(len(company) == 1 and "SEM VALOR FISCAL" in company.name,
                "dataset_fixture_synthetic_currency_company")
        main = env.ref("base.main_company")
        all_companies = env["res.company"].with_context(active_test=False).search([])
        require(main != company and set(all_companies.ids) == {main.id, company.id},
                "dataset_fixture_only_two_fresh_known_companies")
        for model in ("purchase.order", "account.move", "account.payment", "ap.security.draft.receipt"):
            require(env[model].with_context(active_test=False).search_count([]) == 0,
                    "dataset_fixture_currency_before_financial_preparation")
        currency = env.ref("base.BRL")
        require(currency.name == "BRL" and currency.rounding == 0.01 and currency.decimal_places == 2,
                "dataset_fixture_existing_brl_exact_cent")
        previous = env["res.currency"].search([("active", "=", True), ("id", "!=", currency.id)])
        require(len(previous) == 1 and previous.name == "USD",
                "dataset_fixture_expected_initial_currency_profile")
        user = env["res.users"].browse(base.user_id)
        baseline_identity = assert_executor_identity(env, user, company=company)
        group_user = env.ref("base.group_user")
        pricelist = env.ref("product.group_product_pricelist")
        baseline_implied = set(group_user.implied_ids.ids)
        baseline_graph = {group.id: tuple(sorted(group.implied_ids.ids))
                          for group in env["res.groups"].search([])}
        require(pricelist not in group_user.all_implied_ids,
                "dataset_fixture_initial_pricelist_option_disabled")
        company.write({"currency_id": currency.id})
        main.write({"currency_id": currency.id})
        # A second active currency changes Odoo's internal-user groups. Keep
        # the single-currency profile natively, never relax the identity gate.
        previous.write({"active": False})
        env.flush_all()
        env.registry.clear_all_caches()
        env.invalidate_all()
        # Product's currency hook enables pricelists but has no inverse. Only
        # restore that known feature delta in this fresh, empty database, using
        # the exact native operation from Settings; never repair user groups or
        # an unexpected graph. No global settings wizard or ACL write occurs.
        require(set(group_user.implied_ids.ids) == baseline_implied | {pricelist.id},
                "dataset_fixture_only_known_native_feature_delta")
        group_user._remove_group(pricelist)
        env.flush_all()
        env.registry.clear_all_caches()
        env.invalidate_all()
        require(set(group_user.implied_ids.ids) == baseline_implied,
                "dataset_fixture_original_feature_graph_restored")
        require({group.id: tuple(sorted(group.implied_ids.ids))
                 for group in env["res.groups"].search([])} == baseline_graph,
                "dataset_fixture_complete_group_graph_unchanged")
        require(company.currency_id == main.currency_id == currency and currency.active
                and env["res.currency"].search([("active", "=", True)]) == currency,
                "dataset_fixture_native_brl_configuration")
        expected_explicit = {env.ref(xmlid).id for xmlid in EXPLICIT_GROUPS}
        expected_effective = {env.ref(xmlid).id for xmlid in EFFECTIVE_GROUPS}
        explicit, effective = set(user.group_ids.ids), set(user.all_group_ids.ids)
        # Finite preparation diagnostics only; no identities, raw values or
        # permissions are repaired here. The original assertion is mandatory.
        write_json(Path("/mnt/runner-artifacts/dataset-fixture-currency-check.json"), {
            "schema_version": "dataset-fixture-currency-check/v1",
            "explicit_groups_match": explicit == expected_explicit,
            "effective_groups_match": effective == expected_effective,
            "explicit_missing_count": len(expected_explicit - explicit),
            "explicit_extra_count": len(explicit - expected_explicit),
            "effective_missing_count": len(expected_effective - effective),
            "effective_extra_count": len(effective - expected_effective),
            "multi_currency_present": env.ref("base.group_multi_currency").id in effective,
            "multi_company_present": env.ref("base.group_multi_company").id in effective,
            "pricelist_present": pricelist.id in effective,
        })
        final_identity = assert_executor_identity(env, user, company=company)
        require(final_identity == baseline_identity,
                "dataset_fixture_original_identity_inventory_unchanged")
        cr.commit()
    base.currency = "BRL"


def prepare(registry, args):
    artifacts, manifest, native = selected_inputs(registry, args)
    rows = []
    for name in CASES:
        case = next(row for row in manifest["cases"] if row["name"] == name)
        seed = next(row for row in native["cases"] if row["name"] == name)
        observer, scope, registration = load_scope(registry, args, manifest, seed)
        check_reader(observer, manifest)
        # Source is the independent fixture's saved CREATE, never model_output.
        action = deepcopy(scope.command["action"])
        target = case["target_move_id"]
        if target is not None:
            require(name == CASES[1] and target == scope.result["receipt"]["move_id"],
                    "dataset_fixture_prepared_post_target")
            action.update(action="POST_VENDOR_BILL", executor_mode="POST_APPROVED", target_move_id=target)
        else:
            require(name == CASES[0] and action["action"] == "CREATE_DRAFT_BILL",
                    "dataset_fixture_prepared_create_action")
        before = normalized(observer.fresh_projection(scope))
        observer.observation_records = []
        observation, _checks = observer.observe(
            "dataset-fixture-" + name, scope, registration, action, facts=observer.facts(),
        )
        after = normalized(observer.fresh_projection(scope))
        require(before == after, "dataset_fixture_native_preparation_read_only")
        with registry.cursor() as cr:
            observer.base.cursor_gate(cr)
            env = observer.base.env(cr)
            lines = env["purchase.order.line"].browse(list(scope.workflow.purchase_line_ids)).exists()
            require(len(lines) == len(scope.workflow.purchase_line_ids), "dataset_fixture_all_native_lines")
            expected_lines = sorted([{
                "item_code": line.product_id.default_code,
                "purchase_line_id": line.id, "product_id": line.product_id.id,
            } for line in lines], key=lambda line: line["item_code"])
        rows.append({
            "name": name, "fixture_ref": "TCC-DATAFIX-" + ("CREATE" if target is None else "POST"),
            "workflow": case["workflow"], "legitimate_action": action,
            "observation": observation, "binding": observer.expected_binding(scope, registration),
            "expected_lines": expected_lines, "target_move_id": target,
            "projection_before": before, "projection_after": after,
        })
    value = top(args, manifest, "dataset-fixture-native-inputs/v1")
    value.update(company_id=manifest["company_id"], company_name=manifest["company_name"],
                 reader_user_id=manifest["reader_user_id"], cases=rows)
    write_json(artifacts / "dataset-fixture-inputs.json", value)


def confirm(registry, args):
    artifacts, manifest, native = selected_inputs(registry, args)
    inputs = read_json(artifacts / "dataset-fixture-inputs.json")
    require(inputs["schema_version"] == "dataset-fixture-native-inputs/v1" and
            inputs["status"] == "PASS" and all(inputs[key] == manifest[key] for key in PROVENANCE),
            "dataset_fixture_confirmation_input_binding")
    require(tuple(row["name"] for row in inputs["cases"]) == CASES,
            "dataset_fixture_confirmation_case_order")
    rows = []
    for name, prepared in zip(CASES, inputs["cases"], strict=True):
        seed = next(row for row in native["cases"] if row["name"] == name)
        observer, scope, _registration = load_scope(registry, args, manifest, seed)
        check_reader(observer, manifest)
        observed = normalized(observer.fresh_projection(scope))
        require(observed == prepared["projection_before"] == prepared["projection_after"],
                "dataset_fixture_fresh_native_projection_unchanged")
        rows.append({"name": name, "projection": observed})
    value = top(args, manifest, "dataset-fixture-native-confirmation/v1")
    value.update(reader_readonly_acl_verified=True, cases=rows)
    write_json(artifacts / "dataset-fixture-confirmation.json", value)


def run(args):
    require(args.mode in {"dataset-fixtures-prepare", "dataset-fixtures-confirm"},
            "dataset_fixture_explicit_native_mode")
    odoo.tools.config.parse_config(["-c", args.config, "-d", args.database, "--no-http"], setup_logging=False)
    require(not odoo.tools.config["test_enable"], "dataset_fixture_normal_registry")
    registry = Registry(args.database)
    {"dataset-fixtures-prepare": prepare, "dataset-fixtures-confirm": confirm}[args.mode](registry, args)
