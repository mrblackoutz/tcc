"""Serializacao deterministica para hashes de estado e manifests."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    """Produz UTF-8 JSON estavel para valores compativeis com JSON.

    A funcao recusa NaN e infinitos, que nao sao valores JSON interoperaveis.
    """

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_json_sha256(value: Any) -> str:
    """Retorna o SHA-256 hexadecimal da representacao JSON deterministica."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()

