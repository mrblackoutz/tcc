# SPDX-License-Identifier: LGPL-3.0-or-later
"""DEC-095 gateway half of one pilot state slot; never imports Odoo.

The provider stage is either the real llm-client result produced in the
isolated g3c runner or, for debugging only, a mocked transport built from the
legitimate seed command. Expected facts are read only by the assembly, after
the effect. Raw slot artifacts stay in the ignored disposable run directory.
"""

import argparse
import asyncio
from decimal import Decimal
import hashlib
import json
import logging
from pathlib import Path
import re


SLOT_FILES = ("slot.json", "fixture-entry.json", "member.pdf", "pilot-state-identities.json", "capture-binding.json")
POLICY_CHECKS = frozenset({"v2_stage_validated", "pdf_custody_validated", "independent_binding_validated",
    "native_readonly_json2_performed", "candidate_observation_bound", "actual_policy_evaluated",
    "command_only_for_allow_create", "no_approval_generated", "original_candidate_preserved",
    "observed_facts_preserved"})
CANDIDATE_KEYS = frozenset({"name", "request", "stage", "canonical_action", "request_sha256", "proposal_sha256",
    "action_sha256", "provider_mode"})
CONTEXT_FIELDS = frozenset({"schema_version", "proof_run_id", "slot_run_id", "slot_key", "database",
    "restored_database", "condition", "git_base", "source_bundle_sha256", "policy_sha256", "schedule_sha256",
    "position", "repetition", "provider_mode", "supervision", "scientific_run", "human_review_complete"})
MAX_OUTPUT_BYTES = 128 * 1024 * 1024


def require(value, code="PILOT_STATE_GATEWAY_INVALID"):
    if not value:
        raise ValueError(code)


def read(path):
    from runner_observed_gateway import read_artifact
    return read_artifact(Path(path))


def write_once(path, value):
    """Exclusive write with group read (0640), as DEC-079 handoffs to the Odoo UID.

    Gateway UID 10002 and Odoo UID 10001 share GID 10001. No chmod of existing
    paths, no world access; the descriptor created with O_EXCL is the only one adjusted.
    """
    import os
    import sys
    from tcc_gateway.state import canonical_json_bytes
    path = Path(path)
    raw = canonical_json_bytes(value)
    require(0 < len(raw) <= MAX_OUTPUT_BYTES and re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", path.name), "PILOT_STATE_WRITE")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o640)
    with os.fdopen(descriptor, "wb") as stream:
        if sys.platform == "linux":
            os.fchmod(stream.fileno(), 0o640)
        require(stream.write(raw) == len(raw), "PILOT_STATE_WRITE")
        stream.flush()
        os.fsync(stream.fileno())
    require(path.read_bytes() == raw, "PILOT_STATE_WRITE_REREAD")


def inputs(args):
    root = Path(args.artifacts)
    slot, entry = read(root / "slot.json"), read(root / "fixture-entry.json")
    identities, binding = read(root / "pilot-state-identities.json"), read(root / "capture-binding.json")
    require(slot["schema_version"] == "pilot-state-slot/v1" and slot["database"] == args.database
            and slot["run_id"] == args.slot_run_id and slot["member_key"] == entry["member_key"]
            and slot["condition"] in {"C0", "C1"} and binding["company_id"] == identities["company_id"]
            and entry["gateway_workflow"]["company_name"] == binding["company_name"]
            and slot["git_base"] == args.git_base and slot["source_bundle_sha256"] == args.source_bundle_sha256,
            "PILOT_STATE_SLOT_INPUTS")
    return root, slot, entry, identities, binding


def document(root, entry):
    from tcc_gateway.pdf_ingestion import extract_pdf_text
    value = extract_pdf_text(root / "member.pdf")
    require(value.document_sha256 == entry["document_sha256"], "PILOT_STATE_DOCUMENT")
    return value


def build_request(root, entry):
    from tcc_gateway.llm_adapters import LLMProposalRequest
    from tcc_gateway.runner_contract_v2 import build_client_request_v2
    from tcc_gateway.task_prompt import build_task_messages
    extracted = document(root, entry)
    return build_client_request_v2(LLMProposalRequest(entry["scenario_id"], extracted,
        build_task_messages(entry["phase"], extracted.text)), provider="deepseek")


def request(args):
    """Same bytes as the round-2 batch builder for this document and phase."""
    from tcc_gateway.pilot_proposal_batch import BATCH_VERSION
    from tcc_gateway.task_prompt import TASK_PROMPT_VERSION, task_prompt_sha256
    root, slot, entry, _identities, _binding = inputs(args)
    value = build_request(root, entry)
    write_once(root / "slot.request.json", value)
    write_once(root / "slot.batch.json", {"schema_version": BATCH_VERSION, "seed": slot["schedule_seed"],
        "task_prompt_version": TASK_PROMPT_VERSION,
        "task_prompt_sha256": {phase: task_prompt_sha256(phase) for phase in ("DRAFT_INTAKE", "POST_REVIEW")},
        "item_count": 1, "items": [{"run_key": slot["llm_run_key"], "pair_id": entry["pair_id"],
            "role": entry["role"], "condition": slot["condition"], "repetition": slot["repetition"],
            "phase": entry["phase"], "request": value}]})


def mocked_output(entry):
    """Debug-only provider double: the legitimate seed command, never a label."""
    action = entry["native"]["command"]["action"]
    lines = [{"item_code": line["item_code"], "description": "SERVICO SINTETICO SEM VALOR FISCAL",
              "quantity": line["quantity"], "unit_price": line["unit_price"],
              "line_total": format(Decimal(line["quantity"]) * Decimal(line["unit_price"]), ".2f")}
             for line in action["lines"]]
    return {"action": "POST_VENDOR_BILL" if entry["phase"] == "POST_REVIEW" else "CREATE_DRAFT_BILL",
            "vendor_ref": action["vendor_ref"], "purchase_order_ref": action["purchase_order_ref"],
            "document_ref": action["document_ref"], "invoice_date": action["invoice_date"],
            "currency": action["currency"], "bank_account_ref": action["recipient_bank_ref"],
            "total": action["amount"], "lines": lines}


def mocked_stage(request_value, condition, entry):
    import httpx
    from tcc_gateway.llm_client_service import LLMClientServiceConfig, process_client_request
    from tcc_gateway.llm_config import DEEPSEEK_MODEL, DeepSeekConfig
    from tcc_gateway.pilot_llm_runner import run_llm_stage
    output = mocked_output(entry)

    def provider(_request):
        return httpx.Response(200, json={"id": "synthetic-pilot-state", "model": DEEPSEEK_MODEL,
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}]})

    async def call_once(value, _cap):
        status, response = process_client_request(value, LLMClientServiceConfig(mode="deepseek-smoke",
            deepseek_config=DeepSeekConfig(api_key="synthetic-pilot-state-placeholder")),
            transport=httpx.MockTransport(provider), expected_request_version="llm-client-request/v2")
        require(status == 200, "PILOT_STATE_MOCK_PROVIDER")
        return response

    return asyncio.run(run_llm_stage(request_value, condition=condition, call_once=call_once))


def candidate(args):
    """Validate the stage, canonicalize a valid proposal; failures stay outcomes."""
    from runner_observed_gateway import stage_to_mapping
    from tcc_gateway.pilot_proposal_batch import restore_batch_stage
    from tcc_gateway.runner_contract_v2 import proposal_from_llm_stage_v2
    from tcc_gateway.state import canonical_json_sha256
    from tcc_gateway.trusted_resolution import canonicalize_proposal
    root, slot, entry, _identities, _binding = inputs(args)
    request_value = read(root / "slot.request.json")
    require(request_value == build_request(root, entry), "PILOT_STATE_REQUEST_REBUILT")
    if slot["provider_mode"] == "OBSERVED":
        batch = read(root / "slot.batch.json")
        require(batch["item_count"] == 1 and batch["items"][0]["request"] == request_value, "PILOT_STATE_BATCH")
        result = read(root / "llm" / (slot["llm_run_key"] + ".json"))
        stage = restore_batch_stage(batch["items"][0], result)
    else:
        require(slot["provider_mode"] == "MOCKED", "PILOT_STATE_PROVIDER_MODE")
        stage = mocked_stage(request_value, slot["condition"], entry)
    require(stage.condition == slot["condition"], "PILOT_STATE_STAGE_CONDITION")
    action = proposal = None
    if stage.status == "success":
        proposal = proposal_from_llm_stage_v2(request_value, stage)
        action = canonicalize_proposal(proposal, policy_version=entry["policy_version"],
            quantity_scale=entry["gateway_workflow"]["quantity_scale"], target_move_id=entry["target_move_id"])
    write_once(root / "slot.candidate.json", {"name": entry["member_key"], "request": request_value,
        "stage": stage_to_mapping(stage), "canonical_action": None if action is None else action.to_mapping(),
        "request_sha256": canonical_json_sha256(request_value),
        "proposal_sha256": None if proposal is None else canonical_json_sha256(proposal.to_mapping()),
        "action_sha256": None if action is None else action.action_hash, "provider_mode": slot["provider_mode"]})


def saved_stage(saved, condition):
    from tcc_gateway.attempt_policy import AttemptRecord
    from tcc_gateway.pilot_llm_runner import LLMStageResult
    from tcc_gateway.state import canonical_json_sha256
    require(type(saved) is dict and set(saved) == CANDIDATE_KEYS
            and canonical_json_sha256(saved["request"]) == saved["request_sha256"], "PILOT_STATE_CANDIDATE")
    value = saved["stage"]
    require(value["condition"] == condition, "PILOT_STATE_CANDIDATE_CONDITION")
    return LLMStageResult(value["condition"], value["status"], value["reason"],
        tuple(AttemptRecord(**row) for row in value["attempts"]), value["response"])


def proposal_of(saved, condition):
    from tcc_gateway.runner_contract_v2 import proposal_from_llm_stage_v2
    from tcc_gateway.state import canonical_json_sha256
    stage = saved_stage(saved, condition)
    if saved["canonical_action"] is None:
        require(stage.status != "success" and saved["proposal_sha256"] is None, "PILOT_STATE_MISSING_PROPOSAL")
        return stage, None
    proposal = proposal_from_llm_stage_v2(saved["request"], stage)
    require(canonical_json_sha256(proposal.to_mapping()) == saved["proposal_sha256"], "PILOT_STATE_PROPOSAL_HASH")
    return stage, proposal


def policy(args):
    """C1 CREATE: real read-only observation and the actual policy engine."""
    from datetime import datetime, timedelta, timezone
    from runner_observed_gateway import ReadonlyCaller, parse_workflow
    from tcc_gateway.config import OdooConfig
    from tcc_gateway.odoo_json2 import OdooJson2Client
    from tcc_gateway.operational_observation import (ObservationBinding, parse_registered_observation,
                                                     read_observed_trusted_state)
    from tcc_gateway.policy_contracts import DependencyStatus
    from tcc_gateway.runner_contract_v2 import prepare_c1_observed_draft_command_v2
    from tcc_gateway.state import canonical_json_sha256
    root, slot, entry, _identities, _binding = inputs(args)
    require(slot["condition"] == "C1" and entry["phase"] == "DRAFT_INTAKE", "PILOT_STATE_POLICY_SCOPE")
    saved = read(root / "slot.candidate.json")
    before = canonical_json_sha256(saved)
    stage, proposal = proposal_of(saved, "C1")
    require(proposal is not None, "PILOT_STATE_POLICY_NEEDS_PROPOSAL")
    workflow = parse_workflow(entry["gateway_workflow"])
    binding = ObservationBinding.from_mapping(entry["binding"])
    observation = parse_registered_observation(read(root / "slot.observation.json"), binding)
    preflight = observation.to_mapping()["preflight"]
    token = (Path(args.secret_directory) / "pilot-reader.key").read_text(encoding="utf-8").strip()
    require(bool(token), "PILOT_STATE_READER_KEY")
    with OdooJson2Client(OdooConfig(base_url="http://odoo:8069", database=args.database, api_token=token)) as client:
        counted = ReadonlyCaller(client)
        observed = read_observed_trusted_state(counted, workflow, observation, binding,
            dependencies=DependencyStatus(preflight["state"], "AVAILABLE", preflight["audit"]),
            policy_version=entry["policy_version"])
        now = datetime.now(timezone.utc)
        prepared = prepare_c1_observed_draft_command_v2(saved["request"], stage, observed=observed,
            policy_version=entry["policy_version"],
            evaluated_at=now.isoformat(timespec="microseconds").replace("+00:00", "Z"),
            expires_at=(now + timedelta(seconds=300)).isoformat(timespec="microseconds").replace("+00:00", "Z"))
    token = None
    require(canonical_json_sha256(saved) == before and len(counted.calls) > 0, "PILOT_STATE_POLICY_CUSTODY")
    command = None if prepared.command is None else prepared.command.to_mapping()
    status = prepared.decision.decision
    require(command is None or (status == "ALLOW" and command["action"]["action"] == "CREATE_DRAFT_BILL"
            and "approval" not in command), "PILOT_STATE_POLICY_COMMAND")
    facts = observation.to_mapping()["facts"]
    require(prepared.policy_input.trusted_state.duplicate_detected == facts["duplicate_detected"]
            and prepared.policy_input.trusted_state.accounting_period_open == facts["accounting_period_open"],
            "PILOT_STATE_OBSERVED_FACTS")
    write_once(root / "slot.policy.json", {"name": entry["member_key"], "status": status,
        "category": "POLICY_EVALUATED", **{name: saved[name] for name in ("request_sha256", "proposal_sha256",
                                                                          "action_sha256")},
        "observation_sha256": observation.to_mapping()["observation_sha256"],
        "policy_input": prepared.policy_input.to_mapping(), "policy_input_sha256": prepared.policy_input.input_hash,
        "decision": prepared.decision.to_mapping(), "command": command,
        "command_sha256": None if command is None else canonical_json_sha256(command),
        "native_json2_request_count": len(counted.calls), "readonly_call_trace": counted.calls,
        "checks": {name: True for name in POLICY_CHECKS}})


def dispatch(args):
    """C0: the syntactically valid proposal goes to the direct JSON-2 executor."""
    from runner_native_gateway import CountedCaller
    from tcc_gateway.c0_action_executor_v2 import TrustedC0ActionBinding
    from tcc_gateway.config import OdooConfig
    from tcc_gateway.odoo_json2 import OdooJson2Client
    from tcc_gateway.runner_contract_v2 import dispatch_c0_llm_stage_v2
    root, slot, entry, _identities, binding = inputs(args)
    require(slot["condition"] == "C0", "PILOT_STATE_DISPATCH_C0_ONLY")
    saved = read(root / "slot.candidate.json")
    stage, proposal = proposal_of(saved, "C0")
    require(proposal is not None, "PILOT_STATE_DISPATCH_NEEDS_PROPOSAL")
    token = (Path(args.secret_directory) / "pilot-c0.key").read_text(encoding="utf-8").strip()
    require(bool(token), "PILOT_STATE_C0_KEY")
    from tcc_gateway.c0_action_executor_v2 import C0ActionExecutionError
    move_id, error = None, None
    with OdooJson2Client(OdooConfig(base_url="http://odoo:8069", database=args.database, api_token=token)) as client:
        counted = CountedCaller(client)
        try:
            result = dispatch_c0_llm_stage_v2(counted, saved["request"], stage, binding=TrustedC0ActionBinding(
                binding["company_name"], entry["scenario_id"], entry["document_sha256"],
                entry["gateway_workflow"]["target_document_ref"]))
            move_id = result.move_id
        except C0ActionExecutionError as failure:
            # A refusal before any write is an outcome; the native phase still
            # observes the real state. Operation/response failures may be
            # uncertain remote effects and stop the run instead (DEC-031).
            if failure.category not in {"INVALID_BINDING", "INVALID_PROPOSAL", "TARGET_NOT_FOUND",
                                        "TARGET_AMBIGUOUS", "TARGET_NOT_CONFIGURED", "INPUT_BINDING_MISMATCH"}:
                raise
            error = failure.category
        methods = [model + "." + method for model, method in counted.calls if method in {"create", "action_post"}]
    token = None
    if error is not None:
        methods = []
        write_once(root / "slot.dispatch-error.json", {"schema_version": "pilot-state-c0-error/v1", "code": error})
    write_once(root / "slot.dispatch.json", {"move_id": move_id, "methods": methods,
        "disposition": "ALLOW_EFFECTIVE", "receipt_id": None})


def validate_context(value, args, binding):
    from tcc_gateway.run_supervision import RunSupervision
    require(type(value) is dict and set(value) == CONTEXT_FIELDS
            and value["schema_version"] == "pilot-state-record-context/v1"
            and value["scientific_run"] is False and value["human_review_complete"] is False
            and value["provider_mode"] in {"MOCKED", "OBSERVED"}, "PILOT_STATE_CONTEXT")
    for name in ("database", "git_base", "source_bundle_sha256"):
        require(value[name] == getattr(args, name), "PILOT_STATE_CONTEXT_BINDING")
    require(value["slot_run_id"] == args.slot_run_id, "PILOT_STATE_CONTEXT_RUN")
    supervision = RunSupervision.from_mapping(value["supervision"])
    supervision.validate_binding(run_id=args.slot_run_id, condition=supervision.condition,
        code_commit=args.git_base, configuration_sha256=binding.configuration_sha256)
    require(supervision.mode == "OBSERVED" and supervision.effect_quiescence == "CONFIRMED", "PILOT_STATE_SUPERVISION")
    return supervision


def assemble_create(args):
    """RunRecord v4 plus the generic CREATE envelope; expected facts from the seed only."""
    from runner_observed_gateway import parse_workflow
    from tcc_gateway import policy_engine, run_record_store as fs
    from tcc_gateway.company_capture import (CaptureBinding, ExpectedEffect, ExpectedInvoiceLine, assert_restored,
                                             parse_company_capture)
    from tcc_gateway.gateway_run_result import build_gateway_run_result, parse_gateway_run_result
    from tcc_gateway.oracle import BillFacts, OracleCase, OracleProposal, OracleTrace
    from tcc_gateway.policy_contracts import CapabilityCommand, PolicyDecision, PolicyInput
    from tcc_gateway.policy_engine import evaluate_policy
    from tcc_gateway.run_record import RunIdentity
    from tcc_gateway.run_record_v4 import build_run_record_v4
    from tcc_gateway.state import canonical_json_sha256
    root, slot, entry, _identities, binding_value = inputs(args)
    require(entry["phase"] == "DRAFT_INTAKE", "PILOT_STATE_ASSEMBLE_CREATE_ONLY")
    binding = CaptureBinding.from_mapping(binding_value)
    context = read(root / "slot.record-context.json")
    supervision = validate_context(context, args, binding)
    require(supervision.condition == slot["condition"] and context["provider_mode"] == slot["provider_mode"],
            "PILOT_STATE_CONTEXT_SLOT")
    require(hashlib.sha256(Path(policy_engine.__file__).read_bytes()).hexdigest() == context["policy_sha256"],
            "PILOT_STATE_POLICY_ARTIFACT")
    baseline = parse_company_capture(read(root / "baseline.capture.json"), binding)
    before = parse_company_capture(read(root / "before.capture.json"), binding)
    after = parse_company_capture(read(root / "after.capture.json"), binding)
    restored = parse_company_capture(read(root / "restored.capture.json"), binding)
    assert_restored(baseline, before)
    assert_restored(baseline, restored)
    saved = read(root / "slot.candidate.json")
    stage, proposal = proposal_of(saved, slot["condition"])
    effect = read(root / "slot.effect.json")
    require(set(effect) == {"move_id", "methods", "disposition", "receipt_id", "committed_effect_confirmed"}
            and effect["committed_effect_confirmed"] is True, "PILOT_STATE_EFFECT")
    policy_input = decision = None
    deny_class = None
    disposition = None if effect["disposition"] == "NO_PROPOSAL" else effect["disposition"]
    if proposal is None:
        require(effect["move_id"] is None and effect["methods"] == [], "PILOT_STATE_NO_PROPOSAL_EFFECT")
    elif slot["condition"] == "C1":
        value = read(root / "slot.policy.json")
        policy_input, decision = PolicyInput.from_mapping(value["policy_input"]), PolicyDecision.from_mapping(value["decision"])
        decision.validate_binding(policy_input)
        require(evaluate_policy(policy_input) == decision and policy_input.input_hash == value["policy_input_sha256"]
                and policy_input.action.to_mapping() == saved["canonical_action"]
                and decision.decision == value["status"] == effect["disposition"]
                and all(value[name] == saved[name] for name in ("request_sha256", "proposal_sha256", "action_sha256")),
                "PILOT_STATE_POLICY_EVIDENCE")
        if decision.decision == "ALLOW":
            command = CapabilityCommand.from_mapping(value["command"])
            command.validate_binding(policy_input)
            require(canonical_json_sha256(command.to_mapping()) == value["command_sha256"], "PILOT_STATE_COMMAND_HASH")
        else:
            require(value["command"] is None and effect["move_id"] is None, "PILOT_STATE_DENY_NO_EFFECT")
        deny_class = decision.deny_class
    else:
        dispatch_value = read(root / "slot.dispatch.json")
        require(all(effect[name] == dispatch_value[name] for name in dispatch_value)
                and effect["disposition"] == "ALLOW_EFFECTIVE", "PILOT_STATE_DISPATCH_EVIDENCE")
    expected = entry["expected"]
    bill = expected["bill"]
    facts = BillFacts(bill["vendor_ref"], bill["purchase_order_ref"], bill["document_ref"], bill["amount"],
                      bill["currency"], bill["recipient_bank_ref"], "draft")
    adversarial = entry["role"] == "adversarial"
    case = OracleCase(entry["scenario_id"], binding.company_name, "adversarial" if adversarial else "benign",
        "CREATE_DRAFT_BILL", facts, slot["attack_family"] if adversarial else None,
        slot["attack_target"] if adversarial else None)
    trace = OracleTrace(slot["condition"], True, True, True, True,
        None if proposal is None else OracleProposal.from_action_proposal_v2(proposal),
        disposition, False, tuple(effect["methods"]), before.oracle_state, after.oracle_state,
        effect_move_id=effect["move_id"])
    expected_effect = ExpectedEffect(expected["effect"]["invoice_date"],
        tuple(ExpectedInvoiceLine(**line) for line in expected["effect"]["lines"]))
    identity = RunIdentity(args.slot_run_id, entry["scenario_id"], entry["pair_id"], slot["condition"],
        slot["repetition"], context["position"], context["schedule_sha256"], slot["provider_mode"])
    raw = (root / "member.pdf").read_bytes()
    record = build_run_record_v4(identity=identity, document_bytes=raw, request_value=saved["request"], stage=stage,
        policy_sha256=context["policy_sha256"], supervision=supervision, case=case, trace=trace,
        expected_effect=expected_effect, baseline=baseline, before=before, after=after, restored=restored,
        deny_class=deny_class)
    from tcc_gateway.pilot_post_run_result import build_pilot_no_proposal_result, parse_pilot_no_proposal_result
    if proposal is None:
        result = build_pilot_no_proposal_result(record, workflow=parse_workflow(entry["gateway_workflow"]))
        reparse = parse_pilot_no_proposal_result
    else:
        result = build_gateway_run_result(record, workflow=parse_workflow(entry["gateway_workflow"]),
                                          policy_input=policy_input, policy_decision=decision)
        reparse = parse_gateway_run_result
    value = result.to_mapping()
    write_once(root / "slot.gateway-run.json", value)
    persisted = fs._json(fs._read_bounded(root / "slot.gateway-run.json", MAX_OUTPUT_BYTES))
    require(reparse(persisted).to_mapping() == value, "PILOT_STATE_ENVELOPE_REPARSE")
    write_once(root / "slot.gateway-result.json", {"schema_version": "pilot-state-gateway-result/v1", "status": "PASS",
        "slot_key": slot["slot_key"], "run_id": args.slot_run_id, "database": args.database,
        "record_sha256": canonical_json_sha256(value["record"]), "wrapper_sha256": canonical_json_sha256(value),
        "record_version": "run-record/v4", "batch_gate": value["record"]["derived"]["batch_gate"],
        "provider_mode": slot["provider_mode"], "scientific_run": False, "human_review_complete": False})


# ---- POST (A3a) slots ------------------------------------------------------------------------
PRODUCER_CLOCK_FIELDS = frozenset({"schema_version", "run_id", "database", "condition", "producer",
                                   "clock_scope_sha256", "physical_domain"})


def clock_check(root):
    from tcc_gateway.linux_clock_domain import measure_clock_domain
    from tcc_gateway.linux_clock_scope import parse_clock_scope, require_clock_in_scope
    scope = parse_clock_scope(read(root / "slot.clock-scope.json"))
    observed = measure_clock_domain()
    require_clock_in_scope(observed, scope)
    return observed, scope


def write_producer_clock(root, slot, producer, before, after):
    from tcc_gateway.linux_clock_domain import require_same_domain
    from tcc_gateway.state import canonical_json_sha256
    require_same_domain(before[0], after[0])
    write_once(root / ("slot." + producer + "-clock.json"), {"schema_version": "pilot-state-producer-clock/v1",
        "run_id": slot["run_id"], "database": slot["database"], "condition": slot["condition"], "producer": producer,
        "clock_scope_sha256": canonical_json_sha256(before[1]), "physical_domain": before[0]})


def read_producer_clock(root, slot, producer, scope):
    from tcc_gateway.linux_clock_domain import parse_clock_domain
    from tcc_gateway.linux_clock_scope import require_clock_in_scope
    from tcc_gateway.state import canonical_json_sha256
    value = read(root / ("slot." + producer + "-clock.json"))
    require(type(value) is dict and set(value) == PRODUCER_CLOCK_FIELDS and value["producer"] == producer
            and value["run_id"] == slot["run_id"] and value["database"] == slot["database"]
            and value["condition"] == slot["condition"]
            and value["clock_scope_sha256"] == canonical_json_sha256(scope), "PILOT_STATE_PRODUCER_CLOCK")
    domain = parse_clock_domain(value["physical_domain"])
    require_clock_in_scope(domain, scope)
    return domain


def candidate_post(args):
    root, slot, entry, _identities, _binding = inputs(args)
    require(entry["phase"] == "POST_REVIEW", "PILOT_STATE_POST_ONLY")
    before = clock_check(root)
    candidate(args)
    write_producer_clock(root, slot, "candidate", before, clock_check(root))


def policy_post(args):
    """C1 POST: actual observed policy; REVIEW yields an unsigned template only."""
    from datetime import datetime, timedelta, timezone
    from runner_observed_gateway import ReadonlyCaller, parse_workflow
    from tcc_gateway.config import OdooConfig
    from tcc_gateway.idempotency import idempotency_key_for_resolved
    from tcc_gateway.odoo_json2 import OdooJson2Client
    from tcc_gateway.operational_observation import (ObservationBinding, parse_registered_observation,
                                                     read_observed_trusted_state)
    from tcc_gateway.policy_contracts import DependencyStatus
    from tcc_gateway.runner_contract_v2 import prepare_c1_observed_draft_command_v2
    from tcc_gateway.state import canonical_json_sha256
    root, slot, entry, _identities, _binding = inputs(args)
    require(slot["condition"] == "C1" and entry["phase"] == "POST_REVIEW", "PILOT_STATE_POST_POLICY_SCOPE")
    clock_before = clock_check(root)
    saved = read(root / "slot.candidate.json")
    before = canonical_json_sha256(saved)
    stage, proposal = proposal_of(saved, "C1")
    require(proposal is not None, "PILOT_STATE_POLICY_NEEDS_PROPOSAL")
    binding = ObservationBinding.from_mapping(entry["binding"])
    observation = parse_registered_observation(read(root / "slot.observation.json"), binding)
    preflight = observation.to_mapping()["preflight"]
    token = (Path(args.secret_directory) / "pilot-reader.key").read_text(encoding="utf-8").strip()
    require(bool(token), "PILOT_STATE_READER_KEY")
    with OdooJson2Client(OdooConfig(base_url="http://odoo:8069", database=args.database, api_token=token)) as client:
        counted = ReadonlyCaller(client)
        observed = read_observed_trusted_state(counted, parse_workflow(entry["gateway_workflow"]), observation, binding,
            dependencies=DependencyStatus(preflight["state"], "AVAILABLE", preflight["audit"]),
            policy_version=entry["policy_version"])
        now = datetime.now(timezone.utc)
        prepared = prepare_c1_observed_draft_command_v2(saved["request"], stage, observed=observed,
            policy_version=entry["policy_version"], evaluated_at=now.isoformat().replace("+00:00", "Z"),
            expires_at=(now + timedelta(seconds=300)).isoformat().replace("+00:00", "Z"))
    token = None
    require(prepared.command is None and prepared.decision.decision in {"REVIEW", "DENY"}, "PILOT_STATE_POST_DECISION")
    unsigned = None
    if prepared.decision.decision == "REVIEW":
        unsigned = {"schema_version": "capability-command/v1", "action": prepared.policy_input.action.to_mapping(),
                    "policy_decision": prepared.decision.to_mapping(),
                    "idempotency_key": idempotency_key_for_resolved(observed.resolved)}
    require(canonical_json_sha256(saved) == before and len(counted.calls) > 0, "PILOT_STATE_POLICY_CUSTODY")
    write_once(root / "slot.post-policy.json", {"name": entry["member_key"], "status": prepared.decision.decision,
        "category": "POLICY_EVALUATED", **{name: saved[name] for name in ("request_sha256", "proposal_sha256",
                                                                          "action_sha256")},
        "observation_sha256": observation.to_mapping()["observation_sha256"],
        "policy_input": prepared.policy_input.to_mapping(), "policy_input_sha256": prepared.policy_input.input_hash,
        "decision": prepared.decision.to_mapping(), "unsigned_command": unsigned,
        "unsigned_command_sha256": None if unsigned is None else canonical_json_sha256(unsigned),
        "native_json2_request_count": len(counted.calls), "readonly_call_trace": counted.calls})
    write_producer_clock(root, slot, "policy", clock_before, clock_check(root))


def assemble_post(args):
    from runner_observed_gateway import parse_workflow
    from tcc_gateway import policy_engine, run_record_store as fs
    from tcc_gateway.company_capture import (CaptureBinding, ExpectedEffect, ExpectedInvoiceLine, assert_restored,
                                             parse_company_capture)
    from tcc_gateway.linux_clock_domain import parse_clock_domain, require_same_domain
    from tcc_gateway.linux_clock_scope import parse_clock_scope, require_same_scope
    from tcc_gateway.oracle import BillFacts, OracleCase, OracleProposal, OracleTrace
    from tcc_gateway.pilot_post_run_result import build_pilot_post_run_result, parse_pilot_post_run_result
    from tcc_gateway.policy_contracts import PolicyDecision, PolicyInput
    from tcc_gateway.run_record import RunIdentity
    from tcc_gateway.run_record_v4 import build_run_record_v4
    from tcc_gateway.state import canonical_json_sha256
    root, slot, entry, _identities, binding_value = inputs(args)
    require(entry["phase"] == "POST_REVIEW", "PILOT_STATE_ASSEMBLE_POST_ONLY")
    binding = CaptureBinding.from_mapping(binding_value)
    context = read(root / "slot.record-context.json")
    supervision = validate_context(context, args, binding)
    scope = parse_clock_scope(read(root / "slot.clock-scope.json"))
    domain = parse_clock_domain(read(root / "slot.clock-domain.json"))
    assembly_before = clock_check(root)
    require(hashlib.sha256(Path(policy_engine.__file__).read_bytes()).hexdigest() == context["policy_sha256"]
            and supervision.condition == slot["condition"] and supervision.host_id == scope["host_id"]
            and supervision.clock_id == scope["clock_id"], "PILOT_STATE_POST_CONTEXT")
    baseline = parse_company_capture(read(root / "baseline.capture.json"), binding)
    before = parse_company_capture(read(root / "before.capture.json"), binding)
    after = parse_company_capture(read(root / "after.capture.json"), binding)
    confirmed = parse_company_capture(read(root / "slot.confirmed.capture.json"), binding)
    restored = parse_company_capture(read(root / "restored.capture.json"), binding)
    require(after.to_mapping() == confirmed.to_mapping(), "PILOT_STATE_POST_CONFIRMED")
    assert_restored(baseline, before)
    assert_restored(baseline, restored)
    saved = read(root / "slot.candidate.json")
    stage, proposal = proposal_of(saved, slot["condition"])
    native = read(root / "slot.post-native.json")
    require(native["preissued"] == read(root / "slot.preissued.json"), "PILOT_STATE_PREISSUED")
    policy_input = decision = unsigned = None
    if proposal is not None and slot["condition"] == "C1":
        value = read(root / "slot.post-policy.json")
        policy_input, decision = PolicyInput.from_mapping(value["policy_input"]), PolicyDecision.from_mapping(value["decision"])
        unsigned = value["unsigned_command"]
    elif proposal is not None:
        dispatch_value = read(root / "slot.dispatch.json")
        require(dispatch_value["move_id"] == native["effect_move_id"]
                and dispatch_value["methods"] == native["executed_methods"], "PILOT_STATE_POST_DISPATCH")
    expected = entry["expected"]
    bill = expected["bill"]
    facts = BillFacts(bill["vendor_ref"], bill["purchase_order_ref"], bill["document_ref"], bill["amount"],
                      bill["currency"], bill["recipient_bank_ref"], "posted")
    adversarial = entry["role"] == "adversarial"
    case = OracleCase(entry["scenario_id"], binding.company_name, "adversarial" if adversarial else "benign",
        "POST_VENDOR_BILL", facts, slot["attack_family"] if adversarial else None,
        slot["attack_target"] if adversarial else None, entry["target_move_id"])
    trace = OracleTrace(slot["condition"], True, True, True, True,
        None if proposal is None else OracleProposal.from_action_proposal_v2(proposal, target_move_id=entry["target_move_id"]),
        native["disposition"], False, tuple(native["executed_methods"]), before.oracle_state, after.oracle_state,
        effect_move_id=native["effect_move_id"])
    expected_effect = ExpectedEffect(expected["effect"]["invoice_date"],
        tuple(ExpectedInvoiceLine(**line) for line in expected["effect"]["lines"]))
    identity = RunIdentity(args.slot_run_id, entry["scenario_id"], entry["pair_id"], slot["condition"],
        slot["repetition"], context["position"], context["schedule_sha256"], slot["provider_mode"])
    record = build_run_record_v4(identity=identity, document_bytes=(root / "member.pdf").read_bytes(),
        request_value=saved["request"], stage=stage, policy_sha256=context["policy_sha256"], supervision=supervision,
        case=case, trace=trace, expected_effect=expected_effect, baseline=baseline, before=before, after=after,
        restored=restored, deny_class=native["deny_class"], approval_observation=native["observation"])
    require_same_domain(assembly_before[0], clock_check(root)[0])
    producers = {"sampler": domain, "native": native["clock_domain"],
                 "candidate": read_producer_clock(root, slot, "candidate", scope),
                 "policy": read_producer_clock(root, slot, "policy", scope) if (root / "slot.policy-clock.json").exists() else None,
                 "assembly": assembly_before[0]}
    result = build_pilot_post_run_result(record, workflow=parse_workflow(entry["gateway_workflow"]), clock_domain=domain,
        clock_scope=scope, clock_producers=producers, native_evidence=native, policy_input=policy_input,
        policy_decision=decision, unsigned_command=unsigned)
    value = result.to_mapping()
    write_once(root / "slot.gateway-run.json", value)
    persisted = fs._json(fs._read_bounded(root / "slot.gateway-run.json", MAX_OUTPUT_BYTES))
    require(parse_pilot_post_run_result(persisted).to_mapping() == value, "PILOT_STATE_POST_REPARSE")
    write_once(root / "slot.gateway-result.json", {"schema_version": "pilot-state-gateway-result/v1", "status": "PASS",
        "slot_key": slot["slot_key"], "run_id": args.slot_run_id, "database": args.database,
        "record_sha256": canonical_json_sha256(value["record"]), "wrapper_sha256": canonical_json_sha256(value),
        "record_version": "run-record/v4", "batch_gate": value["record"]["derived"]["batch_gate"],
        "provider_mode": slot["provider_mode"], "scientific_run": False, "human_review_complete": False})


MODES = {"request": request, "candidate": candidate, "policy": policy, "dispatch": dispatch,
         "assemble-create": assemble_create, "candidate-post": candidate_post, "policy-post": policy_post,
         "assemble-post": assemble_post}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=tuple(MODES))
    for name in ("database", "git-base", "source-bundle-sha256", "slot-run-id"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--artifacts", default="/mnt/runner-artifacts")
    parser.add_argument("--secret-directory", default="/run/runner-secrets")
    args = parser.parse_args(argv)
    if (not re.fullmatch(r"tcc_runner_[0-9a-f]{12}", args.database) or not re.fullmatch(r"[0-9a-f]{40}", args.git_base)
            or not re.fullmatch(r"[0-9a-f]{64}", args.source_bundle_sha256)
            or not re.fullmatch(r"[0-9a-f]{32}", args.slot_run_id)
            or args.artifacts != "/mnt/runner-artifacts" or args.secret_directory != "/run/runner-secrets"):
        print("PILOT_STATE_GATEWAY_INVALID_CONFIGURATION")
        return 2
    logging.disable(logging.CRITICAL)
    try:
        MODES[args.mode](args)
    except Exception as error:
        code = str(error) if type(error) is ValueError and str(error).startswith("PILOT_STATE_") else type(error).__name__
        try:
            Path(args.artifacts, "failure-gateway-" + args.mode + ".json").write_text(
                json.dumps({"status": "FAIL", "mode": args.mode, "code": code}), encoding="utf-8")
        except OSError:
            pass
        print("PILOT_STATE_GATEWAY_FAILED_" + args.mode.upper())
        return 1
    print("PILOT_STATE_GATEWAY_PASS_" + args.mode.upper())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
