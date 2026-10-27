"""Offline checks of the DEC-095 pilot state schedule and slot identities."""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "gateway/src"))

import pilot_state_harness as harness  # noqa: E402


def rows():
    result = []
    for pair, phase in (("PAIR-AAAA", "DRAFT_INTAKE"), ("PAIR-BBBB", "POST_REVIEW")):
        for role in ("benign", "adversarial"):
            result.append({"member_key": pair + "." + role, "phase": phase, "role": role})
    return result


def test_schedule_is_deterministic_complete_and_seed_dependent():
    many = [{"member_key": f"PAIR-{index:04d}.{role}", "role": role}
            for index in range(12) for role in ("benign", "adversarial")]
    first = harness.build_schedule(many, seed=7)
    assert first == harness.build_schedule(many, seed=7)
    assert len(first) == harness.SLOT_COUNT == 24 * 2 * 3
    assert len({slot["slot_key"] for slot in first}) == len(first)
    assert [slot["position"] for slot in first] == list(range(1, len(first) + 1))
    assert [slot["slot_key"] for slot in first] != [slot["slot_key"] for slot in harness.build_schedule(many, seed=8)]


def test_schedule_requires_three_repetitions_and_integer_seed():
    with pytest.raises(ValueError):
        harness.build_schedule(rows(), seed=1, repetitions=2)
    with pytest.raises(ValueError):
        harness.build_schedule(rows(), seed="1")


def test_slot_run_id_is_bound_to_proof_and_slot():
    proof = "a" * 32
    first = harness.slot_run_id(proof, "PAIR-AAAA.benign.C0.r1")
    assert len(first) == 32 and first != harness.slot_run_id(proof, "PAIR-AAAA.benign.C1.r1")
    assert first != harness.slot_run_id("b" * 32, "PAIR-AAAA.benign.C0.r1")
    with pytest.raises(ValueError):
        harness.slot_run_id("short", "PAIR-AAAA.benign.C0.r1")


def test_only_adversarial_post_documents_use_the_second_baseline():
    by_key = {row["member_key"]: harness.baseline_for(row) for row in rows()}
    assert by_key == {"PAIR-AAAA.benign": "B0", "PAIR-AAAA.adversarial": "B0",
                      "PAIR-BBBB.benign": "B0", "PAIR-BBBB.adversarial": "B1"}


def test_schedule_hash_changes_with_order():
    slots = [{"slot_key": "a"}, {"slot_key": "b"}]
    assert harness.schedule_sha256(slots) != harness.schedule_sha256(list(reversed(slots)))
