from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from tcc_gateway import pilot_dataset as pilot
from tcc_gateway.llm_adapters import LLMAdapterError
from tcc_gateway.pilot_proposal_batch import (
    BATCH_VERSION, BatchError, build_batch, run_batch,
)

from test_llm_client_service_v2 import v2_request, v2_response
from test_pilot_dataset import sample_recipes


@pytest.fixture(scope="module")
def cohort():
    return pilot.prepare_pilot_cohort(pilot.parse_pilot_recipes(sample_recipes()), "f" * 64)


def test_full_pilot_batch_has_144_runs_with_unique_keys(cohort) -> None:
    batch = build_batch(cohort, seed=7)
    assert batch["schema_version"] == BATCH_VERSION and batch["item_count"] == 144
    assert len({item["run_key"] for item in batch["items"]}) == 144
    cells = {(i["role"], i["condition"]) for i in batch["items"]}
    assert cells == {(r, c) for r in ("benign", "adversarial") for c in ("C0", "C1")}


def test_order_is_reproducible_by_seed_and_differs_across_seeds(cohort) -> None:
    keys = lambda seed: [i["run_key"] for i in build_batch(cohort, seed=seed)["items"]]
    assert keys(7) == keys(7) and keys(7) != keys(8)


def test_c0_and_c1_receive_byte_identical_requests(cohort) -> None:
    batch = build_batch(cohort, seed=1)
    by_cell: dict[tuple, list] = {}
    for item in batch["items"]:
        by_cell.setdefault((item["pair_id"], item["role"]), []).append(item["request"])
    assert all(all(r == requests[0] for r in requests) for requests in by_cell.values())


def test_phase_is_trusted_and_document_text_is_only_in_user_message(cohort) -> None:
    for item in build_batch(cohort, seed=1, repetitions=1, conditions=("C0",))["items"]:
        system, user = item["request"]["messages"]
        document = item["request"]["document"]["text"]
        assert system["role"] == "system" and user["role"] == "user"
        assert document in user["content"] and document not in system["content"]
        action = "CREATE_DRAFT_BILL" if item["phase"] == "DRAFT_INTAKE" else "POST_VENDOR_BILL"
        assert f"action = {action}" in system["content"]


def test_benign_only_and_invalid_options(cohort) -> None:
    batch = build_batch(cohort, seed=1, roles=("benign",), repetitions=1)
    assert batch["item_count"] == 24 and {i["role"] for i in batch["items"]} == {"benign"}
    for kwargs in ({"repetitions": 0}, {"roles": ("x",)}, {"conditions": ()}, {"seed": "1"}):
        with pytest.raises(BatchError):
            build_batch(cohort, **{"seed": 1, **kwargs})


def _batch(n: int) -> dict:
    return {"schema_version": BATCH_VERSION, "items": [
        {"run_key": f"PAIR-1.benign.C0.r{i}", "pair_id": "PAIR-1", "role": "benign",
         "condition": "C0", "repetition": i, "phase": "DRAFT_INTAKE", "request": v2_request()}
        for i in range(1, n + 1)]}


def test_success_is_recorded_privately_and_never_repeated(tmp_path: Path) -> None:
    calls = []

    async def once(request, _cap):
        calls.append(1)
        return v2_response()

    batch = _batch(2)
    first = asyncio.run(run_batch(batch, tmp_path, call_once=once))
    assert first["executed"] == 2 and first["by_reason"] == {"SUCCESS": 2}
    record = json.loads((tmp_path / "PAIR-1.benign.C0.r1.json").read_text(encoding="utf-8"))
    assert record["stage"]["status"] == "success" and record["response"]["status"] == "ok"
    again = asyncio.run(run_batch(batch, tmp_path, call_once=once))
    assert again["executed"] == 0 and again["skipped_done"] == 2 and len(calls) == 2


def test_orphan_start_marker_blocks_repeat_because_outcome_is_unknown(tmp_path: Path) -> None:
    calls = []

    async def once(request, _cap):
        calls.append(1)
        return v2_response()

    (tmp_path / "PAIR-1.benign.C0.r1.started").write_bytes(b"started\n")
    summary = asyncio.run(run_batch(_batch(2), tmp_path, call_once=once))
    assert summary["orphan_started"] == ["PAIR-1.benign.C0.r1"]
    assert summary["executed"] == 1 and len(calls) == 1


def test_classified_error_is_recorded_without_response_and_limit_is_honoured(tmp_path: Path) -> None:
    async def once(request, _cap):
        raise LLMAdapterError("deepseek", "invalid_schema")

    summary = asyncio.run(run_batch(_batch(3), tmp_path, call_once=once, limit=2))
    assert summary["executed"] == 2
    record = json.loads((tmp_path / "PAIR-1.benign.C0.r1.json").read_text(encoding="utf-8"))
    assert record["stage"]["status"] == "classified_error" and record["response"] is None


def test_unsafe_key_or_missing_directory_is_rejected(tmp_path: Path) -> None:
    bad = _batch(1)
    bad["items"][0]["run_key"] = "../escape"
    with pytest.raises(BatchError):
        asyncio.run(run_batch(bad, tmp_path))
    with pytest.raises(BatchError):
        asyncio.run(run_batch(_batch(1), tmp_path / "missing"))
