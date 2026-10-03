"""Synthetic C1-08 trusted workflow contracts, without Odoo or financial effects.

These administrative objects are not RPC commands or authorization grants.
No key, approval token, final dataset or live database is used here.
"""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, asdict, fields, replace
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[2]
ADDON = ROOT / "odoo/addons/ap_security_executor"
PACKAGE = "_tcc_post_contracts_offline"
_package = ModuleType(PACKAGE)
_package.__path__ = [str(ADDON)]
sys.modules[PACKAGE] = _package


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


contracts = _load(PACKAGE + ".contracts", ADDON / "contracts.py")
draft = _load(PACKAGE + ".draft_contracts", ADDON / "draft_contracts.py")
post = _load(PACKAGE + ".post_contracts", ADDON / "post_contracts.py")


def _draft(**changes):
    values = {
        "company_id": 11, "executor_user_id": 22, "purchase_order_id": 33,
        "vendor_id": 44, "journal_id": 55, "expense_account_id": 66,
        "purchase_line_ids": (77, 78), "allowed_bank_ids": (88, 89),
        "scenario_id": "TCC-SYNTHETIC-POST-001", "document_sha256": "a" * 64,
        "policy_version": "policy-v1.0.0", "phase": "DRAFT_INTAKE",
        "invoice_date_min": "2026-10-01", "invoice_date_max": "2026-10-31",
        "quantity_scale": 2, "monetary_tolerance": "0.00",
    }
    values.update(changes)
    return draft.TrustedDraftWorkflow(**values)


def _post(**changes):
    values = {"draft": _draft(), "target_move_id": 99}
    values.update(changes)
    return post.TrustedPostWorkflow(**values)


def _invalid(**changes):
    with pytest.raises(contracts.ExecutorContractError) as caught:
        _post(**changes)
    assert "SENSITIVE-MARKER" not in str(caught.value)


def test_workflow_is_closed_frozen_and_separates_post_phase_from_source_draft():
    value = _post()
    assert value.phase == "POST_REVIEW"
    assert value.draft.phase == "DRAFT_INTAKE"
    assert value.target_move_id == 99
    assert {field.name for field in fields(value)} == {"draft", "target_move_id", "phase"}
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        value.target_move_id = 100
    with pytest.raises(FrozenInstanceError):
        value.draft.vendor_id = 100
    with pytest.raises(TypeError):
        post.TrustedPostWorkflow(target_move_id=99)
    with pytest.raises(TypeError):
        post.TrustedPostWorkflow(draft=_draft(), target_move_id=99, context={})


@pytest.mark.parametrize("target", [None, True, False, 0, -1, "99", 99.0, [], {}, object()])
def test_target_requires_an_exact_positive_integer_not_untrusted_coercion(target):
    _invalid(target_move_id=target)


@pytest.mark.parametrize("phase", [None, True, 1, "DRAFT_INTAKE", "post_review", "POST_REVIEW ", "POST_REVIEW\n", "SENSITIVE-MARKER"])
def test_phase_is_exact_closed_post_review(phase):
    _invalid(phase=phase)


@pytest.mark.parametrize("value", [None, {}, [], object()])
def test_nested_workflow_requires_the_exact_trusted_class(value):
    _invalid(draft=value)


def test_mapping_is_not_promoted_to_trusted_workflow():
    _invalid(draft=asdict(_draft()))


def test_nested_subclass_is_not_accepted_as_trusted_configuration():
    class DerivedWorkflow(draft.TrustedDraftWorkflow):
        pass

    _invalid(draft=DerivedWorkflow(**asdict(_draft())))


@pytest.mark.parametrize("field,value", [
    ("company_id", True), ("executor_user_id", 0), ("purchase_order_id", -1),
    ("vendor_id", "44"), ("journal_id", 55.0), ("expense_account_id", None),
    ("purchase_line_ids", [77, 78]), ("purchase_line_ids", (78, 77)),
    ("purchase_line_ids", (77, 77)), ("purchase_line_ids", ()),
    ("purchase_line_ids", tuple(range(1, 52))),
    ("allowed_bank_ids", (88, True)), ("allowed_bank_ids", (89, 88)),
    ("allowed_bank_ids", tuple(range(1, 52))),
    ("scenario_id", "S" * 65), ("scenario_id", "lowercase"),
    ("document_sha256", "A" * 64), ("document_sha256", "a" * 63),
    ("policy_version", "policy-v999"), ("phase", "POST_REVIEW"),
    ("invoice_date_min", "2026-02-30"), ("invoice_date_min", "2026-11-01"),
    ("invoice_date_max", "2026-09-30"), ("quantity_scale", True),
    ("quantity_scale", 5), ("monetary_tolerance", "-0.01"),
    ("monetary_tolerance", "0.001"), ("monetary_tolerance", "1" * 13 + ".00"),
])
def test_nested_frozen_workflow_is_revalidated_after_slot_tampering(field, value):
    source = _draft()
    object.__setattr__(source, field, value)
    _invalid(draft=source)


@pytest.mark.parametrize("slot", ["company_id", "purchase_line_ids", "phase", "monetary_tolerance"])
def test_deleted_nested_configuration_slots_are_rejected_without_echo(slot):
    source = _draft()
    object.__delattr__(source, slot)
    _invalid(draft=source)


def test_valid_boundaries_preserve_exact_source_configuration():
    source = _draft(
        purchase_line_ids=tuple(range(1, 51)), allowed_bank_ids=tuple(range(101, 151)),
        scenario_id="S" * 64, quantity_scale=4, monetary_tolerance="999999999999.99",
    )
    before = asdict(source)
    value = _post(draft=source, target_move_id=1)
    assert asdict(value.draft) == before
    assert asdict(source) == before
    assert value.target_move_id == 1


@pytest.mark.parametrize("field,value", [("target_move_id", 100), ("draft", None), ("phase", "DRAFT_INTAKE")])
def test_normal_dataclass_replacement_revalidates_changed_configuration(field, value):
    if field == "target_move_id":
        updated = replace(_post(), **{field: value})
        assert updated.target_move_id == value
    else:
        with pytest.raises(contracts.ExecutorContractError):
            replace(_post(), **{field: value})


def test_contract_module_is_stdlib_only_without_io_or_gateway_dependency():
    tree = ast.parse((ADDON / "post_contracts.py").read_text(encoding="utf-8"))
    forbidden = {"odoo", "tcc_gateway", "requests", "httpx", "socket", "subprocess", "jsonschema"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not ({alias.name.split(".")[0] for alias in node.names} & forbidden)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            assert node.module.split(".")[0] not in forbidden
