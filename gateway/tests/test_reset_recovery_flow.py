"""DEC-059: actual stage producer through private records and reset recovery.

Provider, financial effects and captures are explicit doubles; this suite does
not use paid API, Odoo, a final dataset or a real process supervisor.
"""

import asyncio
from dataclasses import replace

import pytest

from tcc_gateway.attempt_policy import NANOSECONDS
from tcc_gateway.company_capture import parse_company_capture
from tcc_gateway.llm_adapters import LLMAdapterError
from tcc_gateway.pilot_llm_runner import run_llm_stage
from tcc_gateway.run_record_store import read_run_record, write_run_record
from tcc_gateway.run_record_v2 import build_run_record_v2
from tcc_gateway.run_reset_checkpoint import build_run_reset_checkpoint
from tcc_gateway.run_reset_journal import (
    RunResetJournalError, append_reset_checkpoint, read_reset_journal,
    read_stored_next_slot_gate,
)
from tcc_gateway.run_supervision import StageInterval
from tcc_gateway.state import canonical_json_bytes
from test_company_capture import BINDING, sign
from test_run_record import valid_inputs


class StageClock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        self.now += 1
        return self.now

    async def sleep(self, seconds):
        self.now += int(seconds * NANOSECONDS)


def produced_inputs(condition, *, attack=False, post=False, timeout_first=False):
    inputs = valid_inputs(condition, attack=attack, post=post)
    response = inputs["stage"].response
    calls = []
    clock = StageClock()

    async def call_once(request, wall_cap_ns):
        calls.append((request, wall_cap_ns))
        if timeout_first and len(calls) == 1:
            raise LLMAdapterError("deepseek", "timeout", retryable=True)
        return response

    stage = asyncio.run(run_llm_stage(inputs["request_value"], condition=condition,
        call_once=call_once, clock_ns=clock, sleep=clock.sleep))
    inputs["stage"] = stage
    inputs["supervision"] = replace(inputs["supervision"],
        intervals=(StageInterval("llm", 0, clock.now),))
    return inputs, calls, clock


def roots(tmp_path):
    runtime = tmp_path / ".runtime"
    runtime.mkdir()
    records, journal = runtime / "records", runtime / "reset-journal"
    records.mkdir()
    journal.mkdir()
    return {"record_root": records, "journal_root": journal}


def later_supervision(original, *, previous=None):
    interval = (previous.to_mapping()["supervision"]["intervals"][-1]
                if previous is not None else original.to_mapping()["intervals"][-1])
    start = interval["ended_ns"] + 1
    return replace(original, intervals=(StageInterval("capture", start, start + 1),))


def diverged_capture(baseline):
    value = baseline.to_mapping()
    value["records"]["postgres.sequence"][0]["last_value"] += 1
    return parse_company_capture(sign(value), BINDING)


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("post", [False, True])
@pytest.mark.parametrize("timeout_first", [False, True])
@pytest.mark.parametrize("reset_absent", [False, True])
def test_real_stage_to_store_and_same_slot_reset_recovery(
    tmp_path, condition, post, timeout_first, reset_absent,
):
    inputs, calls, _clock = produced_inputs(condition, attack=True,
        post=post, timeout_first=timeout_first)
    inputs["restored"] = None if reset_absent else diverged_capture(inputs["baseline"])
    record = build_run_record_v2(**inputs)
    original = record.to_mapping()
    assert original["derived"]["batch_gate"] == "HALT_RESET"
    assert original["derived"]["oracle"]["state_violation"] is (condition == "C0")
    if post:
        assert original["derived"]["oracle"]["unauthorized_critical_action"] is (condition == "C0")
    paths = roots(tmp_path)
    write_run_record(paths["record_root"], record)
    record_dir = paths["record_root"] / record.run_id
    original_files = {path.name: path.read_bytes() for path in record_dir.iterdir()}
    assert read_stored_next_slot_gate(**paths, run_id=record.run_id) == "HALT_RESET"
    assert not (paths["journal_root"] / record.run_id).exists()

    checkpoint = build_run_reset_checkpoint(record=record, previous=None,
        restored=inputs["baseline"], supervision=later_supervision(inputs["supervision"]))
    receipt = append_reset_checkpoint(**paths, run_id=record.run_id,
        checkpoint=checkpoint, expected_head_sha256=None)
    history = read_reset_journal(**paths, run_id=record.run_id)
    assert len(history) == 1
    assert history[0].to_mapping() == checkpoint.to_mapping()
    expected = "HALT_LLM_UNCERTAIN" if timeout_first else "CONTINUE"
    assert read_stored_next_slot_gate(**paths, run_id=record.run_id) == expected
    assert checkpoint.to_mapping()["derived"]["reset_status"] == "VERIFIED"
    assert len(calls) == (2 if timeout_first else 1)
    assert canonical_json_bytes(read_run_record(paths["record_root"], record.run_id).to_mapping()) == canonical_json_bytes(original)
    assert {path.name: path.read_bytes() for path in record_dir.iterdir()} == original_files
    assert receipt.sequence == 1
    assert checkpoint.to_mapping()["scientific_run"] is False
    assert checkpoint.to_mapping()["human_review_complete"] is False


@pytest.mark.parametrize("condition", ["C0", "C1"])
@pytest.mark.parametrize("problem", ["after_absent", "effect_unknown", "oracle_rejected"])
def test_restoration_never_fills_a_missing_result_or_clears_classification(
    tmp_path, condition, problem,
):
    inputs, calls, _clock = produced_inputs(condition)
    if problem == "after_absent":
        inputs["after"] = None
        inputs["trace"] = replace(inputs["trace"], after=None)
    elif problem == "effect_unknown":
        inputs["supervision"] = replace(inputs["supervision"], effect_quiescence="UNKNOWN")
    else:
        value = inputs["after"].to_mapping()
        value["records"]["res.partner.bank"][0]["allow_out_payment"] = False
        inputs["after"] = parse_company_capture(sign(value), BINDING)
        inputs["trace"] = replace(inputs["trace"], after=inputs["after"].oracle_state)
    record = build_run_record_v2(**inputs)
    original = record.to_mapping()
    assert original["derived"]["oracle"] is None
    paths = roots(tmp_path)
    write_run_record(paths["record_root"], record)
    checkpoint = build_run_reset_checkpoint(record=record, previous=None,
        restored=inputs["baseline"], supervision=later_supervision(inputs["supervision"]))
    append_reset_checkpoint(**paths, run_id=record.run_id, checkpoint=checkpoint,
        expected_head_sha256=None)
    assert read_stored_next_slot_gate(**paths, run_id=record.run_id) == "HALT_CLASSIFICATION"
    stored = read_run_record(paths["record_root"], record.run_id).to_mapping()
    assert stored == original
    assert stored["derived"]["technical_disposition"]["counts_as_missing"] is False
    assert stored["derived"]["oracle"] is None
    assert len(calls) == 1


def test_latest_reset_checkpoint_can_halt_again_and_stale_append_never_retries(tmp_path):
    inputs, calls, _clock = produced_inputs("C0", attack=True)
    inputs["restored"] = None
    record = build_run_record_v2(**inputs)
    paths = roots(tmp_path)
    write_run_record(paths["record_root"], record)
    first = build_run_reset_checkpoint(record=record, previous=None,
        restored=inputs["baseline"], supervision=later_supervision(inputs["supervision"]))
    receipt = append_reset_checkpoint(**paths, run_id=record.run_id,
        checkpoint=first, expected_head_sha256=None)
    assert read_stored_next_slot_gate(**paths, run_id=record.run_id) == "CONTINUE"
    second = build_run_reset_checkpoint(record=record, previous=first,
        restored=diverged_capture(inputs["baseline"]),
        supervision=later_supervision(inputs["supervision"], previous=first))
    with pytest.raises(RunResetJournalError):
        append_reset_checkpoint(**paths, run_id=record.run_id,
            checkpoint=second, expected_head_sha256=None)
    assert len(read_reset_journal(**paths, run_id=record.run_id)) == 1
    append_reset_checkpoint(**paths, run_id=record.run_id,
        checkpoint=second, expected_head_sha256=receipt.checkpoint_sha256)
    assert read_stored_next_slot_gate(**paths, run_id=record.run_id) == "HALT_RESET"
    assert len(calls) == 1
    assert read_run_record(paths["record_root"], record.run_id).to_mapping()["derived"]["oracle"]["state_violation"] is True
