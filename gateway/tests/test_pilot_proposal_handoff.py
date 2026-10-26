"""Persisted LLM stages, no provider calls, ERP effects or scientific runs."""

import asyncio
from copy import deepcopy
import json

import pytest

from tcc_gateway import pilot_proposal_batch as batch
from tcc_gateway.attempt_policy import AttemptRecord, DEEPSEEK_PILOT_POLICY, NANOSECONDS
from tcc_gateway.pilot_llm_runner import LLMStageResult
from tcc_gateway.runner_contract_v2 import proposal_from_llm_stage_v2
from tcc_gateway.state import canonical_json_sha256
from test_llm_client_service_v2 import v2_response
from test_pilot_proposal_batch import _batch
from test_terminal_llm_stage import terminal


def item(condition="C0"):
    value = deepcopy(_batch(1)["items"][0])
    value["condition"] = condition
    value["run_key"] = f"PAIR-1.benign.{condition}.r1"
    return value


def result(value, stage, elapsed_ns):
    return {"schema_version": batch.RESULT_VERSION,
        **{k: value[k] for k in ("run_key", "pair_id", "role", "condition", "repetition", "phase")},
        "request_sha256": canonical_json_sha256(value["request"]),
        "stage": stage.to_sanitised_mapping(), "response": stage.response, "elapsed_ns": elapsed_ns}


@pytest.mark.parametrize("condition", ["C0", "C1"])
def test_actual_persisted_batch_reaches_common_consumer_without_relabelling(tmp_path, condition, monkeypatch):
    value = item(condition)
    ticks = iter((100, 2 * NANOSECONDS + 100))
    monkeypatch.setattr(batch.time, "monotonic_ns", lambda: next(ticks))

    async def once(_request, _cap):
        return v2_response()

    asyncio.run(batch.run_batch({"schema_version": batch.BATCH_VERSION, "items": [value]},
                               tmp_path, call_once=once))
    saved = json.loads((tmp_path / (value["run_key"] + ".json")).read_bytes())
    assert saved["elapsed_ns"] == 2 * NANOSECONDS
    restored = batch.restore_batch_stage(value, saved)
    assert restored.condition == condition
    assert proposal_from_llm_stage_v2(value["request"], restored).to_mapping() == v2_response()["proposal"]
    saved["response"].clear()
    assert restored.response  # detached from the received mutable record


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("kind", ["classified", "uncertain", "budget"])
def test_terminal_failures_are_preserved_without_proposal_or_invented_disposition(condition, kind):
    value = item(condition)
    elapsed = NANOSECONDS
    stage = terminal(condition=condition)
    if kind == "uncertain":
        elapsed = 121 * NANOSECONDS
        stage = LLMStageResult(condition, "uncertain", "UNCONFIRMED_WALL_OUTCOME", (
            AttemptRecord(1, "deadline_exceeded", elapsed, canonical_json_sha256(value["request"])),))
    elif kind == "budget":
        elapsed = DEEPSEEK_PILOT_POLICY.logical_budget_ns
        stage = LLMStageResult(condition, "budget_exhausted", "BUDGET_EXHAUSTED", ())
    saved = result(value, stage, elapsed)
    restored = batch.restore_batch_stage(value, saved)
    assert restored == stage and restored.response is None
    assert not {"missing", "oracle", "disposition", "effect_move_id"} & set(saved)


@pytest.mark.parametrize("field,bad", [("run_key", "OTHER"), ("pair_id", "OTHER"),
    ("role", "adversarial"), ("condition", "C1"), ("repetition", 2), ("repetition", True),
    ("phase", "POST_REVIEW"), ("request_sha256", "0" * 64), ("schema_version", "other/v1"),
    ("elapsed_ns", -1), ("elapsed_ns", True)])
def test_foreign_slot_request_or_invalid_clock_is_rejected(field, bad):
    value = item()
    saved = result(value, terminal(), NANOSECONDS)
    saved[field] = bad
    with pytest.raises(batch.BatchError, match="invalid persisted LLM stage handoff"):
        batch.restore_batch_stage(value, saved)


@pytest.mark.parametrize("kind", ["condition", "summary-hash", "response", "attempt-request", "extra", "short-interval"])
def test_corrupted_history_cannot_replace_a_bound_terminal_result(kind):
    value = item()
    saved = result(value, terminal(), NANOSECONDS)
    if kind == "condition":
        saved["stage"]["condition"] = "C1"
    elif kind == "summary-hash":
        saved["stage"]["response_sha256"] = "0" * 64
    elif kind == "response":
        saved["response"] = v2_response()
    elif kind == "attempt-request":
        saved["stage"]["attempts"][0]["request_sha256"] = "0" * 64
    elif kind == "short-interval":
        saved["elapsed_ns"] = NANOSECONDS - 1
    else:
        saved["unexpected"] = True
    with pytest.raises(batch.BatchError):
        batch.restore_batch_stage(value, saved)


def test_legacy_result_requires_independently_observed_duration_and_is_unchanged():
    value = item()
    saved = result(value, terminal(), NANOSECONDS)
    saved["schema_version"] = batch.LEGACY_RESULT_VERSION
    del saved["elapsed_ns"]
    original = deepcopy(saved)
    with pytest.raises(batch.BatchError):
        batch.restore_batch_stage(value, saved)
    assert batch.restore_batch_stage(value, saved, elapsed_ns=NANOSECONDS) == terminal()
    assert saved == original


def test_independent_duration_cannot_silently_replace_recorded_duration():
    value = item()
    saved = result(value, terminal(), NANOSECONDS)
    with pytest.raises(batch.BatchError):
        batch.restore_batch_stage(value, saved, elapsed_ns=2 * NANOSECONDS)


@pytest.mark.parametrize("phase", ["DRAFT_INTAKE", "POST_REVIEW"])
def test_adversarial_document_with_legitimate_output_is_not_required_to_compromise_proposal(tmp_path, phase):
    value = item()
    value.update(role="adversarial", phase=phase, run_key="PAIR-1.adversarial.C0.r1")

    async def once(_request, _cap):
        return v2_response()

    asyncio.run(batch.run_batch({"schema_version": batch.BATCH_VERSION, "items": [value]},
                               tmp_path, call_once=once))
    saved = json.loads((tmp_path / (value["run_key"] + ".json")).read_bytes())
    restored = batch.restore_batch_stage(value, saved)
    proposal = proposal_from_llm_stage_v2(value["request"], restored)
    assert restored.status == "success" and proposal.action == "CREATE_DRAFT_BILL"
    assert proposal.to_mapping() == v2_response()["proposal"]
