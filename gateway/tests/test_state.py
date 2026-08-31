from __future__ import annotations

import math

import pytest

from tcc_gateway.state import canonical_json_bytes, canonical_json_sha256


def test_canonical_json_and_hash_are_independent_of_mapping_order() -> None:
    first = {
        "state": "draft",
        "amount_total": 125.5,
        "lines": [{"quantity": 1, "name": "Servico sintetico"}],
    }
    reordered = {
        "lines": [{"name": "Servico sintetico", "quantity": 1}],
        "amount_total": 125.5,
        "state": "draft",
    }

    assert canonical_json_bytes(first) == canonical_json_bytes(reordered)
    assert canonical_json_sha256(first) == canonical_json_sha256(reordered)
    assert len(canonical_json_sha256(first)) == 64


def test_canonical_json_preserves_utf8_and_compact_representation() -> None:
    assert canonical_json_bytes({"descricao": "ação sintética"}) == (
        b'{"descricao":"a\xc3\xa7\xc3\xa3o sint\xc3\xa9tica"}'
    )


def test_hash_changes_when_state_changes() -> None:
    assert canonical_json_sha256({"state": "draft"}) != canonical_json_sha256(
        {"state": "posted"}
    )


def test_canonical_json_rejects_non_json_numbers() -> None:
    with pytest.raises(ValueError):
        canonical_json_bytes({"amount": math.nan})

