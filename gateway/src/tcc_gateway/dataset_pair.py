"""DEC-061 candidate pair contract, not model input or execution authority.

Only shared synthetic fixture truth and evaluator labels belong here. Parsing
one pair does not certify a cohort, authorship review, approval, or freeze.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
from decimal import Context, Decimal, DecimalException, localcontext
from functools import lru_cache
from importlib.resources import files
import json
import unicodedata
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .state import canonical_json_bytes


PAIR_VERSION = "ap-ipi-pair/v1"
CODEBOOK_VERSION = "ap-ipi-codebook/v0.1"
MAX_PAIR_BYTES = 128 * 1024
MAX_PAIR_DEPTH = 12
MAX_PAIR_NODES = 5000


class DatasetPairError(ValueError):
    """Finite diagnostic without values, labels, or document contents."""


def _fail() -> None:
    raise DatasetPairError("invalid candidate dataset pair")


@lru_cache(maxsize=1)
def _schema_and_validator() -> tuple[dict[str, Any], Draft202012Validator]:
    schema = json.loads(files("tcc_gateway.schemas").joinpath(
        "dataset_pair_v1.schema.json",
    ).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema, Draft202012Validator(schema, format_checker=FormatChecker())


def dataset_pair_schema() -> dict[str, Any]:
    """Detached candidate schema; never hand this evaluator contract to a LLM."""
    return deepcopy(_schema_and_validator()[0])


def _structure(value: Any) -> None:
    nodes = 0
    characters = 0
    ancestors: set[int] = set()

    def text(item: str) -> None:
        nonlocal characters
        characters += len(item)
        if (characters > MAX_PAIR_BYTES or item.strip() != item
                or unicodedata.normalize("NFC", item) != item
                or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in item)):
            _fail()

    def walk(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_PAIR_NODES or depth > MAX_PAIR_DEPTH:
            _fail()
        kind = type(item)
        if kind is dict or kind is list:
            identity = id(item)
            if identity in ancestors or len(item) > MAX_PAIR_NODES:
                _fail()
            ancestors.add(identity)
            if kind is dict:
                for key, child in item.items():
                    if type(key) is not str:
                        _fail()
                    text(key)
                    walk(child, depth + 1)
            else:
                for child in item:
                    walk(child, depth + 1)
            ancestors.remove(identity)
        elif kind is str:
            text(item)
        elif kind not in {int, bool, type(None)}:
            _fail()

    if type(value) is not dict:
        _fail()
    walk(value, 0)


def _validate(value: Any) -> bytes:
    _structure(value)
    if type(value.get("synthetic_data")) is not bool or type(value.get("fiscal_value")) is not bool:
        _fail()
    _, validator = _schema_and_validator()
    if not validator.is_valid(value):
        _fail()
    truth = value["truth"]
    if type(truth["quantity_scale"]) is not int:
        _fail()
    if date.fromisoformat(truth["invoice_date"]).isoformat() != truth["invoice_date"]:
        _fail()
    members = value["members"]
    for name in ("scenario_id", "document_sha256", "extracted_text_sha256"):
        if members["benign"][name] == members["adversarial"][name]:
            _fail()
    item_codes = [line["item_code"] for line in truth["lines"]]
    if len(item_codes) != len(set(item_codes)):
        _fail()
    # All operands have bounded lengths. This local precision therefore makes
    # every product and sum exact, independent of the process decimal context.
    # Do not quantize/round a sub-cent result into valid independent truth.
    with localcontext(Context(prec=64)):
        amount = Decimal(truth["amount"])
        total = Decimal(0)
        for line in truth["lines"]:
            if len(line["quantity"].partition(".")[2]) != truth["quantity_scale"]:
                _fail()
            quantity = Decimal(line["quantity"])
            price = Decimal(line["unit_price"])
            subtotal = Decimal(line["line_total"])
            if quantity * price != subtotal:
                _fail()
            total += subtotal
        if total != amount:
            _fail()
    encoded = canonical_json_bytes(value)
    if len(encoded) > MAX_PAIR_BYTES:
        _fail()
    return encoded


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            _fail()
        result[key] = value
    return result


def _constant(_value: str) -> None:
    _fail()


def _decode(encoded: bytes) -> dict[str, Any]:
    if type(encoded) is not bytes or not 0 < len(encoded) <= MAX_PAIR_BYTES:
        _fail()
    value = json.loads(encoded.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    if _validate(value) != encoded:
        _fail()
    return value


@dataclass(frozen=True, slots=True)
class DatasetPair:
    """Canonical, detached candidate data with no sensitive default repr."""

    _encoded: bytes = field(repr=False)

    def __post_init__(self) -> None:
        try:
            _decode(self._encoded)
        except (AttributeError, TypeError, ValueError, OverflowError, RecursionError, DecimalException):
            raise DatasetPairError("invalid candidate dataset pair") from None

    @property
    def pair_id(self) -> str:
        return self.to_mapping()["pair_id"]

    def to_mapping(self) -> dict[str, Any]:
        """Revalidate even a forged frozen record, returning detached JSON."""
        try:
            return _decode(self._encoded)
        except (AttributeError, TypeError, ValueError, OverflowError, RecursionError, DecimalException):
            raise DatasetPairError("invalid candidate dataset pair") from None


def parse_dataset_pair(value: dict[str, Any]) -> DatasetPair:
    """Validate one candidate pair; never generate approval or model actions."""
    try:
        return DatasetPair(_validate(value))
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError, DecimalException):
        raise DatasetPairError("invalid candidate dataset pair") from None
