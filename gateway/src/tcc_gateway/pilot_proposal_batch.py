"""Lote de propostas LLM do piloto: gerador (host) e executor (contêiner g3c-runner).

A proposta depende só de (documento, fase, prompt, modelo); não depende do estado
do Odoo nem da condição. Cada run C0/C1 faz a sua própria chamada, com a mesma
política de tentativas. Este módulo não executa efeitos, não classifica sucesso
de ataque e não decide `missing`. Uma chamada com resultado incerto nunca é
refeita automaticamente.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import sys
import time
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from .llm_adapters import LLMProposalRequest
from .pdf_ingestion import extract_pdf_bytes
from .pilot_llm_runner import LLMStageResult, call_llm_client_once, run_llm_stage
from .runner_contract_v2 import build_client_request_v2
from .state import canonical_json_bytes, canonical_json_sha256
from .task_prompt import TASK_PROMPT_VERSION, build_task_messages, task_prompt_sha256

BATCH_VERSION = "pilot-proposal-batch/v1"
LEGACY_RESULT_VERSION = "pilot-proposal-result/v1"
RESULT_VERSION = "pilot-proposal-result/v2"
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
CONDITIONS = ("C0", "C1")
ROLES = ("benign", "adversarial")
CallOnce = Callable[[Mapping[str, Any], int], Awaitable[Mapping[str, Any]]]


class BatchError(ValueError):
    """Erro finito, sem eco de documento, resposta ou credencial."""


def _phase(truth: Mapping[str, Any]) -> str:
    action = truth["expected_action"]
    if action == "CREATE_DRAFT_BILL":
        return "DRAFT_INTAKE"
    if action == "POST_VENDOR_BILL":
        return "POST_REVIEW"
    raise BatchError("unsupported expected action")


def build_batch(
    cohort: Any, *, repetitions: int = 3, seed: int,
    roles: tuple[str, ...] = ROLES, conditions: tuple[str, ...] = CONDITIONS,
) -> dict[str, Any]:
    """Requisições v2 de todos os runs. Ordem embaralhada de forma reprodutível.

    A fase vem do gabarito do par (modelo do estado confiável do fluxo), igual
    para os dois membros; nunca do texto do documento.
    """
    if not (isinstance(repetitions, int) and 1 <= repetitions <= 5) or not isinstance(seed, int):
        raise BatchError("invalid repetitions or seed")
    if not roles or not set(roles) <= set(ROLES) or not conditions or not set(conditions) <= set(CONDITIONS):
        raise BatchError("invalid roles or conditions")
    items: list[dict[str, Any]] = []
    for generated in cohort.pairs:
        pair = generated.pair.to_mapping()
        phase = _phase(pair["truth"])
        by_sha = {doc_member["document_sha256"]: role for role, doc_member in pair["members"].items()}
        for document in generated.documents:
            extracted = extract_pdf_bytes(document.pdf_bytes)
            role = by_sha.get(extracted.document_sha256)
            if role is None:
                raise BatchError("document is not a member of its pair")
            if role not in roles:
                continue
            scenario_id = pair["members"][role]["scenario_id"]
            request = build_client_request_v2(
                LLMProposalRequest(scenario_id, extracted, build_task_messages(phase, extracted.text)),
                provider="deepseek",
            )
            for condition in conditions:
                for repetition in range(1, repetitions + 1):
                    key = f"{pair['pair_id']}.{role}.{condition}.r{repetition}"
                    if _KEY.fullmatch(key) is None:
                        raise BatchError("unsafe run key")
                    items.append({
                        "run_key": key, "pair_id": pair["pair_id"], "role": role,
                        "condition": condition, "repetition": repetition, "phase": phase,
                        "request": request,
                    })
    random.Random(seed).shuffle(items)
    if len({item["run_key"] for item in items}) != len(items):
        raise BatchError("duplicate run key")
    return {
        "schema_version": BATCH_VERSION, "seed": seed,
        "task_prompt_version": TASK_PROMPT_VERSION,
        "task_prompt_sha256": {p: task_prompt_sha256(p) for p in ("DRAFT_INTAKE", "POST_REVIEW")},
        "item_count": len(items), "items": items,
    }


def batch_sha256(batch: Mapping[str, Any]) -> str:
    return canonical_json_sha256(batch)


def restore_batch_stage(
    item: Mapping[str, Any], result: Mapping[str, Any], *, elapsed_ns: int | None = None,
) -> LLMStageResult:
    """Restore the original terminal stage for the common C0/C1 consumers.

    Duration validates only this stage's history, never a cross-process clock,
    Odoo effect or scientific disposition. Legacy v1 needs an independently
    observed duration; attempt sums are not an observation of that interval.
    Hashes bind the artifacts but do not authenticate their administrator.
    """
    from .run_record_v2 import _stage
    from .terminal_llm_stage import validate_terminal_llm_stage

    try:
        item = json.loads(canonical_json_bytes(item))
        result = json.loads(canonical_json_bytes(result))
        fields = {"schema_version", "run_key", "pair_id", "role", "condition", "repetition",
                  "phase", "request_sha256", "stage", "response"}
        version = result["schema_version"]
        if version == RESULT_VERSION:
            fields.add("elapsed_ns")
            measured = result["elapsed_ns"]
            if elapsed_ns is not None and (type(elapsed_ns) is not int or elapsed_ns != measured):
                raise ValueError
            elapsed_ns = measured
        elif version != LEGACY_RESULT_VERSION:
            raise ValueError
        if set(result) != fields or type(elapsed_ns) is not int or elapsed_ns < 0:
            raise ValueError
        if (item["condition"] not in CONDITIONS or item["role"] not in ROLES
                or type(item["repetition"]) is not int or not 1 <= item["repetition"] <= 5
                or item["phase"] not in {"DRAFT_INTAKE", "POST_REVIEW"}
                or item["run_key"] != f"{item['pair_id']}.{item['role']}.{item['condition']}.r{item['repetition']}"):
            raise ValueError
        for key in ("run_key", "pair_id", "role", "condition", "repetition", "phase"):
            if type(result[key]) is not type(item[key]) or result[key] != item[key]:
                raise ValueError
        if result["request_sha256"] != canonical_json_sha256(item["request"]):
            raise ValueError
        summary = result["stage"]
        if type(summary) is not dict or set(summary) != {"condition", "status", "reason", "attempts", "response_sha256"}:
            raise ValueError
        stage = _stage({key: summary[key] for key in ("condition", "status", "reason", "attempts")}
                       | {"response": result["response"]})
        if stage.condition != item["condition"] or stage.to_sanitised_mapping() != summary:
            raise ValueError
        validate_terminal_llm_stage(item["request"], stage, elapsed_ns=elapsed_ns)
        return stage
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        raise BatchError("invalid persisted LLM stage handoff") from None


def _exclusive_write(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        raise


async def run_batch(
    batch: Mapping[str, Any], out_dir: Path, *, call_once: CallOnce = call_llm_client_once,
    limit: int | None = None,
) -> dict[str, Any]:
    if batch.get("schema_version") != BATCH_VERSION or not isinstance(batch.get("items"), list):
        raise BatchError("invalid batch")
    if not out_dir.is_dir():
        raise BatchError("output directory is missing")
    summary: dict[str, Any] = {"executed": 0, "skipped_done": 0, "orphan_started": [], "by_reason": {}}
    for item in batch["items"]:
        key = item["run_key"]
        if _KEY.fullmatch(key) is None:
            raise BatchError("unsafe run key")
        result_path, marker = out_dir / f"{key}.json", out_dir / f"{key}.started"
        if result_path.exists():
            summary["skipped_done"] += 1
            continue
        if marker.exists():
            summary["orphan_started"].append(key)  # resultado desconhecido: não repetir
            continue
        if limit is not None and summary["executed"] >= limit:
            break
        _exclusive_write(marker, b"started\n")
        started_ns = time.monotonic_ns()
        stage = await run_llm_stage(item["request"], condition=item["condition"], call_once=call_once)
        elapsed_ns = time.monotonic_ns() - started_ns
        if elapsed_ns < 0:
            raise BatchError("invalid LLM stage clock interval")
        record = {
            "schema_version": RESULT_VERSION, "run_key": key, "pair_id": item["pair_id"],
            "role": item["role"], "condition": item["condition"],
            "repetition": item["repetition"], "phase": item["phase"],
            "request_sha256": canonical_json_sha256(item["request"]),
            "elapsed_ns": elapsed_ns,
            "stage": stage.to_sanitised_mapping(),
            "response": None if stage.response is None else dict(stage.response),
        }
        _exclusive_write(result_path, canonical_json_bytes(record) + b"\n")
        summary["executed"] += 1
        summary["by_reason"][stage.reason] = summary["by_reason"].get(stage.reason, 0) + 1
    return summary


def main() -> int:  # pragma: no cover - executado só no contêiner
    batch_path, out_dir = Path(os.environ["TCC_BATCH_FILE"]), Path(os.environ["TCC_BATCH_OUT"])
    limit = int(os.environ["TCC_BATCH_LIMIT"]) if os.environ.get("TCC_BATCH_LIMIT") else None
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    try:
        summary = asyncio.run(run_batch(batch, out_dir, limit=limit))
    except BatchError as error:
        print(json.dumps({"status": "error", "category": "batch_invalid"}))
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps({"status": "done", **summary}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
