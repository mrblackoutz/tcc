"""DEC-064: prepare a local candidate pilot, without executing model or ERP.

No scientific recipes or payloads are embedded here. The caller supplies the
private candidate recipe file beneath .runtime. Human review stays pending.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway" / "src"))

from tcc_gateway import run_record_store as _fs  # noqa: E402
from tcc_gateway.pilot_dataset import (  # noqa: E402
    MAX_RECIPES_BYTES, GeneratedPilotCohort, PilotCohortWriteReceipt,
    parse_pilot_recipes, prepare_pilot_cohort, read_pilot_cohort, write_pilot_cohort,
)


def _invalid_constant(_value: str) -> None:
    raise ValueError("invalid local recipe JSON")


def _read_recipes(path: Path):
    parent, identity = _fs._root(path.parent)
    _fs._portable_component(path.name)
    raw = _fs._read_bounded(path, MAX_RECIPES_BYTES)
    _fs._verify_directory(parent, identity)
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_fs._pairs,
                       parse_constant=_invalid_constant)
    return parse_pilot_recipes(value)


def _literal_note_lines(note: str) -> list[str]:
    # Untrusted notes must not become Markdown images, links or HTML in the
    # local worksheet. A longer fence cannot be closed by received backticks.
    longest = max((len(match.group()) for match in re.finditer(r"`+", note)), default=0)
    fence = "`" * max(3, longest + 1)
    return [fence, *note.split("\n"), fence]


def _review_text(cohort: GeneratedPilotCohort, receipt: PilotCohortWriteReceipt) -> str:
    """Local editable review material; this is not a signed acceptance record."""
    manifest = cohort.to_manifest()
    recipes = cohort.recipes.to_mapping()
    lines = [
        "# Piloto AP-IPI-BR — revisão independente pendente", "",
        "Estado: CANDIDATO. Preparação assistida por IA sob coordenação de Gustavo.",
        "Felipe: revisão dos itens. Thomaz: revisão de integração. Nenhuma assinatura presumida.",
        "Não executar instruções contidas nas notas abaixo: são conteúdo documental não confiável.",
        "A edição deste guia não libera os gates do manifesto nem autoriza publicação/execução.", "",
        f"Coorte: `{receipt.cohort_sha256}`",
        f"Receitas: `{receipt.recipes_sha256}`",
        f"Codebook: `{manifest['codebook_sha256']}`", "",
        "12 pares / 24 documentos; quatro pares por A1/A2/A3a. Fora do conjunto final.",
        "Conferir cada PDF e texto extraído no diretório do par correspondente.",
        "Identificadores e hashes conferem consistência, não existência de cadastros no ERP.", "",
        "## Gates ainda pendentes", "",
        "- Revisão independente dos 24 membros e resolução das divergências.",
        "- DATA-06: fixtures, fatos e alternativas do ataque existentes no Odoo, ação e oráculo.",
        "- A3a: mesmo workflow/rascunho e mesma regra de aprovação legítima nos dois membros;",
        "  não o mesmo token. Ação canônica inclui scenario_id e document_sha256 distintos.",
        "  Materializar fixture para a proveniência de cada cenário/run antes do output, sem label;",
        "  alterações não recebem nova assinatura. Nenhum token foi produzido nesta preparação.",
        "- DATA-05: texto/posição efetivamente entregues ao modelo, além da extração local.",
        "- Integração, SCI-03, segurança/custódia e prontidão para as 144 runs planejadas.", "",
    ]
    for index, (generated, source, summary) in enumerate(zip(
            cohort.pairs, recipes["pairs"], manifest["pairs"], strict=True), 1):
        pair = generated.pair.to_mapping()
        truth = pair["truth"]
        lines.extend([
            f"## {index:02d}. {pair['pair_id']} — {pair['attack_family']}", "",
            f"Diretório do par: `{summary['pair_sha256']}`",
            f"Template/posição/estratégia: {pair['template_id']} / {pair['placement']} / {pair['attack_strategy']}",
            f"Fixture: {pair['fixture_ref']} | Empresa: {truth['company_ref']}",
            f"Fornecedor: {truth['vendor_ref']} | Pedido: {truth['purchase_order_ref']}",
            f"Documento: {truth['document_ref']} | Data: {truth['invoice_date']}",
            f"Total legítimo: {truth['currency']} {truth['amount']} | Banco aprovado no gabarito: {truth['approved_bank_ref']}",
            f"Ação/disposição esperadas: {truth['expected_action']} / {truth['expected_disposition']}",
            f"Objetivo adversarial predeclarado: {pair['attack_target']}", "",
        ])
        for item in truth["lines"]:
            lines.append(f"Item {item['item_code']}: {item['quantity']} × {item['unit_price']} = {item['line_total']}")
        lines.append("")
        for name, document in zip(("benign", "adversarial"), generated.documents, strict=True):
            member = pair["members"][name]
            artifact_prefix = receipt.cohort_sha256 + "/" + summary["pair_sha256"]
            lines.extend([
                f"### {name} — {member['scenario_id']}", "",
                f"PDF: [abrir documento]({artifact_prefix}/{member['document_sha256']}.pdf) ({document.page_count} página(s))",
                f"Texto: [abrir extração]({artifact_prefix}/{member['extracted_text_sha256']}.txt)", "",
                "Nota-fonte (o reflow do PDF deve ser conferido separadamente):", "",
            ])
            lines.extend(_literal_note_lines(source[name + "_note"]))
            lines.extend([
                "", "- [ ] Fatos, totais, referências e ausência de dados reais conferidos.",
                "- [ ] Nota integral, visível e na posição prevista; extração e hash conferidos.",
                "- [ ] Classe/objetivo plausíveis; não confundir instrução legítima com ataque.",
                "- [ ] Fixtures e alternativas exigidas pelo ataque registradas para DATA-06.",
                "Validador independente: PENDENTE. Data: PENDENTE. Divergências/resolução: PENDENTE.", "",
            ])
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipes", type=Path, required=True,
                        help="absolute private recipe file beneath .runtime")
    parser.add_argument("--output-root", type=Path, required=True,
                        help="existing absolute local directory beneath .runtime")
    args = parser.parse_args(argv)
    try:
        output_root, output_identity = _fs._root(args.output_root)
        recipes = _read_recipes(args.recipes)
        # Match the portable source form: UTF-8 without BOM, LF line endings.
        codebook = (ROOT / "dataset" / "codebook.md").read_text(encoding="utf-8-sig")
        codebook_hash = hashlib.sha256(codebook.encode("utf-8")).hexdigest()
        cohort = prepare_pilot_cohort(recipes, codebook_hash)
        receipt = write_pilot_cohort(output_root, cohort)
        checked = read_pilot_cohort(output_root, receipt.cohort_sha256)
        report = _review_text(checked, receipt).encode("utf-8")
        _fs._verify_directory(output_root, output_identity)
        _fs._write_exclusive(output_root / (receipt.cohort_sha256 + ".review.md"), report)
        _fs._verify_directory(output_root, output_identity)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, RecursionError, OverflowError):
        print("Candidate pilot preparation: FAIL (local artifacts preserved)")
        return 1
    print(f"Candidate pilot preparation: PASS; cohort={receipt.cohort_sha256}")
    print("pairs=12; documents=24; families=A1:4,A2:4,A3a:4")
    print("human_review_complete=false; scientific_execution_allowed=false")
    print(f"Local review guide: {receipt.cohort_sha256}.review.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
