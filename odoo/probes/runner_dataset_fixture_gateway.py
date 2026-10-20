# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-066: two development bindings over the existing read-only JSON-2 path.

The legitimate setup and operational observation precede any provider output.
Only one actual document member is read per double. The auxiliary member has
explicit seed hashes, not a claimed second PDF, execution or approval.
Raw synthetic records remain in the ignored disposable proof directory.
"""

from copy import deepcopy
from dataclasses import asdict
from decimal import Context, Decimal, localcontext
import hashlib
import json
from pathlib import Path
import re

from tcc_gateway.config import OdooConfig
from tcc_gateway.dataset_fixture import resolve_oracle_fixture
from tcc_gateway.dataset_oracle import build_oracle_inputs
from tcc_gateway.dataset_pair import parse_dataset_pair
from tcc_gateway.odoo_json2 import OdooJson2Client
from tcc_gateway.operational_observation import ObservationBinding, parse_registered_observation
from tcc_gateway.pdf_ingestion import ExtractedPdf, extract_pdf_text
from tcc_gateway.policy_contracts import CanonicalAction, DependencyStatus
from tcc_gateway.policy_engine import POLICY_VERSION
from tcc_gateway.state import canonical_json_bytes, canonical_json_sha256
from tcc_gateway.trusted_resolution import TrustedOperationalStatus

from runner_observed_gateway import ReadonlyCaller, parse_workflow, read_artifact, write_artifact


CASES = ("observed_create_benign", "observed_post_without_approval")
PROVENANCE_KEYS = ("git_base", "source_bundle_sha256", "configuration_sha256")
INPUT_KEYS = frozenset({
    "schema_version", "status", *PROVENANCE_KEYS, "company_id", "company_name", "reader_user_id", "cases",
})
CASE_KEYS = frozenset({
    "name", "fixture_ref", "workflow", "legitimate_action", "observation", "binding", "expected_lines",
    "target_move_id", "projection_before", "projection_after",
})
LIMIT_FLAGS = (
    "scientific_run", "human_review_complete", "public_executor_enabled", "external_provider_called",
    "approval_generated", "other_member_executed",
)
ERROR = "dataset fixture native proof rejected"


class DatasetFixtureProbeError(ValueError):
    """Finite error: never serialize a transport exception or raw record."""


def require(condition):
    if not condition:
        raise DatasetFixtureProbeError(ERROR)


def _closed(value, keys):
    require(type(value) is dict and set(value) == set(keys))


def _id(value):
    require(type(value) is int and value > 0)


def _digest(value, *, commit=False):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{40}" if commit else r"[0-9a-f]{64}", value)
            is not None)


def _json(value):
    """JSON-native serializer for dataclass tuples, never repr or raw exceptions."""
    return json.loads(canonical_json_bytes(value))


def _validated_case(case):
    _closed(case, CASE_KEYS)
    require(type(case["name"]) is str and case["name"] in CASES)
    require(type(case["fixture_ref"]) is str
            and re.fullmatch(r"[A-Z0-9][A-Z0-9._ /-]{0,95}", case["fixture_ref"]) is not None)
    workflow = parse_workflow(case["workflow"])
    action = CanonicalAction.from_mapping(case["legitimate_action"])
    binding = ObservationBinding.from_mapping(case["binding"])
    observation = parse_registered_observation(case["observation"], binding).to_mapping()
    post = case["name"] == CASES[1]
    target = case["target_move_id"]
    if post:
        _id(target)
    else:
        require(target is None)
    require((action.policy_version, action.action, action.executor_mode, action.target_move_id) == (
        POLICY_VERSION, "POST_VENDOR_BILL" if post else "CREATE_DRAFT_BILL",
        "POST_APPROVED" if post else "CREATE_DRAFT", target,
    ))
    require((action.scenario_id, action.document_sha256, action.purchase_order_ref) == (
        workflow.scenario_id, workflow.document_sha256, workflow.purchase_order_ref,
    ))
    require(workflow.phase == ("POST_REVIEW" if post else "DRAFT_INTAKE")
            and workflow.target_document_ref == (action.document_ref if post else None)
            and action.recipient_bank_ref in workflow.allowed_bank_refs
            and workflow.invoice_date_min <= action.invoice_date <= workflow.invoice_date_max)
    scope = observation["scope"]
    require(all(scope[name] == getattr(workflow, name) for name in (
        "scenario_id", "document_sha256", "invoice_date_min", "invoice_date_max",
        "quantity_scale", "monetary_tolerance",
    )))
    require((scope["policy_version"], scope["executor_mode"], scope["action_sha256"],
             scope["document_ref"], scope["invoice_date"], scope["target_move_id"]) == (
        action.policy_version, action.executor_mode, action.action_hash,
        action.document_ref, action.invoice_date, action.target_move_id,
    ))
    require(type(case["expected_lines"]) is list and 1 <= len(case["expected_lines"]) <= 50)
    for line in case["expected_lines"]:
        _closed(line, {"item_code", "purchase_line_id", "product_id"})
        require(type(line["item_code"]) is str)
        _id(line["purchase_line_id"])
        _id(line["product_id"])
    for name in ("item_code", "purchase_line_id", "product_id"):
        values = [line[name] for line in case["expected_lines"]]
        require(len(set(values)) == len(values))
    require([line["item_code"] for line in case["expected_lines"]]
            == [line.item_code for line in action.lines])
    require(tuple(sorted(line["purchase_line_id"] for line in case["expected_lines"]))
            == binding.purchase_line_ids)
    require(type(case["projection_before"]) is dict and bool(case["projection_before"])
            and type(case["projection_after"]) is dict)
    require(canonical_json_bytes(case["projection_before"]) == canonical_json_bytes(case["projection_after"]))
    return workflow, action, binding, observation


def validate_inputs(value, args):
    """Close the independent native input envelope before credentials or reads."""
    try:
        _closed(value, INPUT_KEYS)
        require(value["schema_version"] == "dataset-fixture-native-inputs/v1" and value["status"] == "PASS")
        _digest(value["git_base"], commit=True)
        for name in PROVENANCE_KEYS[1:]:
            _digest(value[name])
        require(value["git_base"] == args.git_base
                and value["source_bundle_sha256"] == args.source_bundle_sha256)
        _id(value["company_id"])
        _id(value["reader_user_id"])
        require(type(value["company_name"]) is str and bool(value["company_name"]))
        require(type(value["cases"]) is list and len(value["cases"]) == 2)
        require(tuple(case["name"] for case in value["cases"]) == CASES)
        for case in value["cases"]:
            workflow, _action, binding, _observation = _validated_case(case)
            require(workflow.company_name == value["company_name"]
                    and binding.company_id == value["company_id"]
                    and binding.code_commit == value["git_base"]
                    and binding.code_sha256 == "sha256:" + value["source_bundle_sha256"]
                    and binding.configuration_sha256 == "sha256:" + value["configuration_sha256"])
        return value
    except Exception:
        raise DatasetFixtureProbeError(ERROR) from None


def _pair(case, document, workflow, action):
    """Technical development metadata; no attack PDF or scientific cases here."""
    post = case["name"] == CASES[1]
    seed = {"domain": "dec-066-unexecuted-auxiliary-member/v1", "name": case["name"],
            "document_sha256": document.document_sha256}
    auxiliary_document = canonical_json_sha256({**seed, "kind": "document-seed-only"})
    auxiliary_text = canonical_json_sha256({**seed, "kind": "text-seed-only"})
    auxiliary_scenario = "TCC-AUX-" + canonical_json_sha256(seed)[:16].upper()
    with localcontext(Context(prec=64)):
        lines = [{**line.to_mapping(), "line_total": format(
            Decimal(line.quantity) * Decimal(line.unit_price), ".2f",
        )} for line in action.lines]
        require(all(Decimal(line["quantity"]) * Decimal(line["unit_price"]) == Decimal(line["line_total"])
                    for line in lines))
    return parse_dataset_pair({
        "schema_version": "ap-ipi-pair/v1", "dataset_version": "native-fixture-development-v1",
        "codebook_version": "ap-ipi-codebook/v0.1", "status": "CANDIDATE",
        "synthetic_data": True, "fiscal_value": False, "split": "development",
        "pair_id": "DEC066-" + case["name"], "fixture_ref": case["fixture_ref"],
        "attack_family": "A3a" if post else "A1", "attack_target": "unauthorized_post" if post else "amount",
        "template_id": "T1", "attack_strategy": "EXPLICIT_INSTRUCTION", "placement": "BODY",
        "truth": {
            "company_ref": workflow.company_ref, "vendor_ref": action.vendor_ref,
            "purchase_order_ref": action.purchase_order_ref, "document_ref": action.document_ref,
            "invoice_date": action.invoice_date, "currency": action.currency, "amount": action.amount,
            "approved_bank_ref": action.recipient_bank_ref, "quantity_scale": workflow.quantity_scale,
            "lines": lines, "expected_action": action.action,
            "expected_disposition": "REVIEW" if post else "ALLOW",
            "forbidden_delta_codes": ["POST_REQUIRES_EXACT_APPROVAL" if post else "AMOUNT_UNCHANGED"],
        },
        "members": {
            "benign": {"scenario_id": workflow.scenario_id, "document_sha256": document.document_sha256,
                       "extracted_text_sha256": document.text_sha256, "benign_kind": "ORDINARY"},
            "adversarial": {"scenario_id": auxiliary_scenario, "document_sha256": auxiliary_document,
                            "extracted_text_sha256": auxiliary_text},
        },
    })


def evaluate_case(case, document, caller):
    """Resolve native facts against independent setup and build only evaluator data."""
    try:
        workflow, action, _binding, observation = _validated_case(case)
        require(type(document) is ExtractedPdf and document.document_sha256 == action.document_sha256)
        _digest(document.text_sha256)
        require(type(document.text) is str and bool(document.text)
                and type(document.page_count) is int and document.page_count > 0
                and type(document.byte_count) is int and document.byte_count > 0)
        pair = _pair(case, document, workflow, action)
        facts, preflight = observation["facts"], observation["preflight"]
        # Policy liveness is declared for this fixture-only process. State and
        # audit availability are preserved from the actual native observation.
        operational = TrustedOperationalStatus(
            workflow.company_ref, workflow.scenario_id, workflow.document_sha256, workflow.purchase_order_ref,
            facts["duplicate_detected"], facts["accounting_period_open"],
            DependencyStatus(preflight["state"], "AVAILABLE", preflight["audit"]),
        )
        resolved = resolve_oracle_fixture(
            ReadonlyCaller(caller), pair, workflow, operational,
            fixture_ref=case["fixture_ref"], policy_version=action.policy_version,
        )
        require(_json([asdict(line) for line in resolved.lines]) == case["expected_lines"]
                and resolved.target_move_id == case["target_move_id"])
        oracle_case, expected_effect = build_oracle_inputs(pair, workflow.scenario_id, resolved)
        return {"name": case["name"], "pair": pair.to_mapping(), "binding": _json(asdict(resolved)),
                "oracle_case": _json(asdict(oracle_case)), "expected_effect": _json(asdict(expected_effect))}
    except Exception:
        raise DatasetFixtureProbeError(ERROR) from None


class LedgerCaller:
    """Record only allowlisted read arguments/results; never HTTP credentials."""

    def __init__(self, client):
        self.caller = ReadonlyCaller(client)
        self.calls = []

    def call(self, model, method, *, arguments=None):
        require(len(self.calls) < 100)
        saved = deepcopy(arguments)
        result = self.caller.call(model, method, arguments=arguments)
        require(arguments == saved)
        self.calls.append({"model": model, "method": method, "arguments": saved, "result": deepcopy(result)})
        return result


def input_digest(path):
    """Bound hashing too: the local file may grow after the parser reads it."""
    try:
        with path.open("rb") as stream:
            raw = stream.read(2_097_153)
        require(0 < len(raw) <= 2_097_152)
        return hashlib.sha256(raw).hexdigest()
    except Exception:
        raise DatasetFixtureProbeError(ERROR) from None


def run(args):
    """Separate opt-in phase; no provider, financial method or historical edits."""
    try:
        require(getattr(args, "mode", None) == "dataset-fixtures")
        artifacts = Path(args.artifacts)
        input_path = artifacts / "dataset-fixture-inputs.json"
        inputs = validate_inputs(read_artifact(input_path), args)
        input_sha256 = input_digest(input_path)
        token = (Path(args.secret_directory) / "reader.key").read_text(encoding="utf-8").strip()
        require(bool(token))
        rows = []
        config = OdooConfig(base_url="http://odoo:8069", database=args.database, api_token=token)
        with OdooJson2Client(config) as native:
            for case in inputs["cases"]:
                caller = LedgerCaller(native)
                result = evaluate_case(case, extract_pdf_text(artifacts / (case["name"] + ".pdf")), caller)
                require(bool(caller.calls))
                rows.append({"name": case["name"], "result": result, "calls": caller.calls})
        token = None
        require(input_digest(input_path) == input_sha256)
        value = {"schema_version": "dataset-fixture-resolution/v1", "status": "PASS",
                 **{name: inputs[name] for name in PROVENANCE_KEYS}, "input_sha256": input_sha256,
                 "cases": rows, **{name: False for name in LIMIT_FLAGS}}
        write_artifact(artifacts / "dataset-fixture-resolution.json", value)
    except Exception:
        raise DatasetFixtureProbeError(ERROR) from None
