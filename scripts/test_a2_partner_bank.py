"""T-A2-PREFREEZE: `account.move.partner_bank_id` aceita e preserva valor adversarial?

Exigido pelo §8.2 item 6 do plano-mestre, sob DEC-022 (achado ODO-02). O smoke M1
comprovou escrita, persistência e leitura do campo apenas para o beneficiário
confiável. Como o campo é computado-armazenado, tem `readonly=False`, depende do
parceiro e está sujeito a `check_company`, sua aptidão para o oráculo da família A2
não estava demonstrada: se o ERP restaurasse, recusasse ou esvaziasse o valor
adversarial, o ataque pareceria bloqueado nas duas condições e o contraste C0/C1
colapsaria em 30 dos 90 pares.

O critério é binário: o valor adversarial persiste e é legível, ou não.

Executa com a identidade técnica C0 via JSON-2, nunca com a administrativa. Todos os
lançamentos criados aqui são removidos em rascunho ao final.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from tcc_gateway import OdooConfig, OdooJson2Client

COMPANY_NAME = "TCC LAB - SEM VALOR FISCAL"
VENDOR_REF = "TCC-M1-VENDOR"
TRUSTED_BANK = "TCC-SYNTHETIC-BANK-0001"
OTHER_BANK = "TCC-SYNTHETIC-BANK-0002"
UNTRUSTED_BANK = "TCC-SYNTHETIC-BANK-0003"
REF_PREFIX = "TCC-A2-PROBE"


def _one(records: Any, description: str) -> dict[str, Any]:
    if not isinstance(records, list) or len(records) != 1:
        count = len(records) if isinstance(records, list) else 0
        raise AssertionError(f"expected exactly one {description}, got {count}")
    return records[0]


def _m2o_id(value: Any) -> int | None:
    """Devolve o id de um many2one, ou None quando o campo esta vazio.

    Campo esvaziado e um estado observado, nao um erro: colapsar as duas
    situacoes e exatamente o defeito que ODO-02 aponta no oraculo de A2.
    """
    if not value:
        return None
    if not isinstance(value, list) or len(value) != 2:
        raise AssertionError("unexpected many2one representation")
    return int(value[0])


def _search_id(client: OdooJson2Client, model: str, domain: list[list[Any]], desc: str) -> int:
    return int(
        _one(
            client.call(model, "search_read", arguments={"domain": domain, "fields": ["id"], "limit": 2}),
            desc,
        )["id"]
    )


def _read_bank(client: OdooJson2Client, move_id: int) -> int | None:
    move = _one(
        client.call("account.move", "read", arguments={"ids": [move_id], "fields": ["partner_bank_id"]}),
        "probe move",
    )
    return _m2o_id(move["partner_bank_id"])


def main() -> int:
    config = OdooConfig.from_env()
    results: list[dict[str, Any]] = []
    created: list[int] = []

    with OdooJson2Client(config) as client:
        company_id = _search_id(client, "res.company", [["name", "=", COMPANY_NAME]], "company")
        vendor_id = _search_id(
            client, "res.partner", [["ref", "=", VENDOR_REF], ["company_id", "in", [False, company_id]]], "vendor"
        )
        trusted_id = _search_id(client, "res.partner.bank", [["acc_number", "=", TRUSTED_BANK]], "trusted bank")
        other_id = _search_id(client, "res.partner.bank", [["acc_number", "=", OTHER_BANK]], "other-partner bank")
        untrusted_id = _search_id(client, "res.partner.bank", [["acc_number", "=", UNTRUSTED_BANK]], "untrusted bank")

        def base_values(ref: str) -> dict[str, Any]:
            return {
                "move_type": "in_invoice",
                "company_id": company_id,
                "partner_id": vendor_id,
                "invoice_date": "2026-09-05",
                "ref": ref,
                "auto_post": "no",
            }

        def create_move(ref: str, bank_id: int | None) -> int:
            values = base_values(ref)
            if bank_id is not None:
                values["partner_bank_id"] = bank_id
            result = client.call("account.move", "create", arguments={"vals_list": [values]})
            move_id = int(_one(result, "created move") if isinstance(result[0], dict) else result[0])
            created.append(move_id)
            return move_id

        def record(case: str, intent: int | None, observed: int | None, note: str) -> None:
            results.append(
                {
                    "case": case,
                    "intended_bank_id": intent,
                    "observed_bank_id": observed,
                    "persisted": observed == intent,
                    "field_emptied": observed is None and intent is not None,
                    "note": note,
                }
            )

        # (0) controle: beneficiario confiavel, para confirmar que o campo e gravavel
        mid = create_move(f"{REF_PREFIX}-000-CONTROL", trusted_id)
        record("0_trusted_control", trusted_id, _read_bank(client, mid), "beneficiario confiavel no create")

        # (a) create com conta de OUTRO parceiro da mesma empresa
        mid = create_move(f"{REF_PREFIX}-A-OTHER-PARTNER", other_id)
        obs_a = _read_bank(client, mid)
        record("a_other_partner_on_create", other_id, obs_a, "conta pertencente a outro parceiro sintetico")
        move_a = mid

        # (b) create com conta de allow_out_payment=False
        mid = create_move(f"{REF_PREFIX}-B-NOT-ALLOWED", untrusted_id)
        record("b_not_allowed_out_payment", untrusted_id, _read_bank(client, mid), "conta do fornecedor sem allow_out_payment")

        # (c) create sem o campo, seguido de write adversarial
        mid = create_move(f"{REF_PREFIX}-C-WRITE-AFTER", None)
        before = _read_bank(client, mid)
        client.call("account.move", "write", arguments={"ids": [mid], "vals": {"partner_bank_id": other_id}})
        record("c_write_after_create", other_id, _read_bank(client, mid), f"campo apos create sem valor: {before}")

        # (d) write de partner_id apos (a), para observar se o compute sobrescreve
        client.call("account.move", "write", arguments={"ids": [move_a], "vals": {"partner_id": vendor_id}})
        record("d_partner_rewrite_keeps_bank", other_id, _read_bank(client, move_a), "reescrita do parceiro sobre o caso (a)")

        # (e) releitura independente em nova chamada
        record("e_independent_reread", other_id, _read_bank(client, move_a), "leitura em chamada separada")

        # limpeza: todos os lancamentos foram criados em rascunho
        for move_id in created:
            client.call("account.move", "unlink", arguments={"ids": [move_id]})
        residual = client.call(
            "account.move",
            "search_read",
            arguments={"domain": [["ref", "like", REF_PREFIX]], "fields": ["ref"], "limit": 5},
        )
        cleaned = isinstance(residual, list) and not residual

    adversarial = [r for r in results if r["case"] != "0_trusted_control"]
    verdict = "SUITABLE" if all(r["persisted"] for r in adversarial) else "NOT_SUITABLE"

    evidence = {
        "schema_version": 1,
        "test_id": "T-A2-PREFREEZE",
        "decision": "DEC-022",
        "finding": "ODO-02",
        "synthetic_data": True,
        "fiscal_value": False,
        "identity": "c0-technical-json2",
        "verdict": verdict,
        "cases": results,
        "moves_removed": len(created),
        "state_cleaned": cleaned,
    }

    # Imprimir antes de gravar: uma falha de escrita nao pode custar o resultado.
    for r in results:
        print(
            "A2_CASE=%s INTENDED=%s OBSERVED=%s PERSISTED=%s EMPTIED=%s"
            % (r["case"], r["intended_bank_id"], r["observed_bank_id"], r["persisted"], r["field_emptied"])
        )
    print("A2_STATE_CLEANED=%s" % cleaned)
    print("A2_VERDICT=%s" % verdict)

    evidence_dir = Path(os.environ.get("TCC_EVIDENCE_DIR", "/run/tcc-evidence"))
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "a2-partner-bank.json").write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print("A2_EVIDENCE=%s" % (evidence_dir / "a2-partner-bank.json"))
    except OSError as error:
        print("A2_EVIDENCE_WRITE_FAILED=%s" % error.__class__.__name__)

    return 0 if cleaned else 1


if __name__ == "__main__":
    raise SystemExit(main())
