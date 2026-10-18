"""Pure candidate dataset -> evaluator bridge (DEC-061).

The manifest describes expected facts, not authority. Native identities are
resolved separately by a trusted fixture producer and bound to the complete
canonical pair hash. This module neither resolves those identities nor issues
proposals, policy decisions, approvals or financial calls. Its typed return is
not evidence of a successful task or of scientific dataset review.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from .company_capture import ExpectedEffect, ExpectedInvoiceLine
from .dataset_pair import DatasetPair, parse_dataset_pair
from .oracle import BillFacts, OracleCase
from .state import canonical_json_sha256


class DatasetOracleError(ValueError):
    """Finite contract failure without reproducing manifest or fixture data."""


def _fail() -> None:
    raise DatasetOracleError("invalid dataset oracle binding") from None


def _reference(value: object) -> None:
    if (type(value) is not str or value.strip() != value
            or re.fullmatch(r"[A-Z0-9][A-Z0-9._ /-]{0,95}", value) is None):
        _fail()


def _identity(value: object) -> None:
    if type(value) is not int or value <= 0:
        _fail()


def _company_name(value: object) -> None:
    if (type(value) is not str or not 1 <= len(value) <= 256
            or value.strip() != value or unicodedata.normalize("NFC", value) != value
            or any(unicodedata.category(character).startswith("C") for character in value)):
        _fail()


@dataclass(frozen=True, slots=True, repr=False)
class ResolvedOracleLine:
    """Native identities supplied by the independent fixture resolver."""

    item_code: str
    purchase_line_id: int
    product_id: int

    def __post_init__(self) -> None:
        _reference(self.item_code)
        _identity(self.purchase_line_id)
        _identity(self.product_id)

    def __repr__(self) -> str:
        return "ResolvedOracleLine(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class OracleFixtureBinding:
    """A trusted fixture mapping; construction does not attest its provenance.

    Producers must derive this from their independent fixture configuration,
    never from model output, a PDF or a benign/adversarial label. Every use
    rechecks the binding, including objects altered through frozen bypasses.
    """

    pair_sha256: str
    fixture_ref: str
    company_ref: str
    company_name: str
    vendor_ref: str
    purchase_order_ref: str
    document_ref: str
    lines: tuple[ResolvedOracleLine, ...]
    target_move_id: int | None

    def __post_init__(self) -> None:
        if type(self.pair_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", self.pair_sha256) is None:
            _fail()
        for value in (self.fixture_ref, self.company_ref, self.vendor_ref,
                      self.purchase_order_ref, self.document_ref):
            _reference(value)
        _company_name(self.company_name)
        if type(self.lines) is not tuple or not self.lines or len(self.lines) > 50:
            _fail()
        for line in self.lines:
            if type(line) is not ResolvedOracleLine:
                _fail()
            ResolvedOracleLine.__post_init__(line)
        for field in ("item_code", "purchase_line_id", "product_id"):
            values = [getattr(line, field) for line in self.lines]
            if len(values) != len(set(values)):
                _fail()
        if self.target_move_id is not None:
            _identity(self.target_move_id)

    def __repr__(self) -> str:
        return "OracleFixtureBinding(<redacted>)"


def build_oracle_inputs(
    pair: DatasetPair, scenario_id: str, fixture: OracleFixtureBinding,
) -> tuple[OracleCase, ExpectedEffect]:
    """Build independent expectations after validating the complete join.

    Financial truth is joined by item code, preserving the trusted resolver's
    line order required by the current capture evaluator. Both pair members
    receive the same fixture/target and expected facts. Selecting a member
    changes only evaluator identity and attack labels, never authorization.
    """

    try:
        if (type(pair) is not DatasetPair or type(scenario_id) is not str
                or type(fixture) is not OracleFixtureBinding):
            _fail()
        OracleFixtureBinding.__post_init__(fixture)
        value = parse_dataset_pair(pair.to_mapping()).to_mapping()
        if canonical_json_sha256(value) != fixture.pair_sha256:
            _fail()
        truth = value["truth"]
        if (value["fixture_ref"] != fixture.fixture_ref
                or any(truth[name] != getattr(fixture, name) for name in (
                    "company_ref", "vendor_ref", "purchase_order_ref", "document_ref",
                ))):
            _fail()
        selected = [name for name, member in value["members"].items()
                    if member["scenario_id"] == scenario_id]
        if len(selected) != 1:
            _fail()
        scenario_class = selected[0]
        is_post = truth["expected_action"] == "POST_VENDOR_BILL"
        if is_post != (fixture.target_move_id is not None):
            _fail()
        by_item = {line["item_code"]: line for line in truth["lines"]}
        if set(by_item) != {line.item_code for line in fixture.lines}:
            _fail()
        expected_effect = ExpectedEffect(
            truth["invoice_date"],
            tuple(ExpectedInvoiceLine(
                line.purchase_line_id, line.product_id,
                by_item[line.item_code]["quantity"],
                by_item[line.item_code]["unit_price"],
            ) for line in fixture.lines),
        )
        expected_bill = BillFacts(
            truth["vendor_ref"], truth["purchase_order_ref"], truth["document_ref"],
            truth["amount"], truth["currency"], truth["approved_bank_ref"],
            "posted" if is_post else "draft",
        )
        case = OracleCase(
            scenario_id, fixture.company_name, scenario_class,
            truth["expected_action"], expected_bill,
            value["attack_family"] if scenario_class == "adversarial" else None,
            value["attack_target"] if scenario_class == "adversarial" else None,
            fixture.target_move_id,
        )
        return case, expected_effect
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError, OverflowError):
        _fail()
