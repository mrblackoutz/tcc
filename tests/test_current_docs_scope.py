"""Editorial regression guards for DEC-058, not evidence of scientific readiness.

Load only the pure helpers through the AST: importing the CLI would parse pytest
arguments and run unrelated repository/PDF checks. The full CLI is also run by
the release workflow; this suite exercises negative scope mutations in isolation.
"""

import ast
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/validate_current_docs.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8-sig"), filename=str(SOURCE))
HELPERS = ast.Module(
    body=[node for node in TREE.body if isinstance(node, ast.FunctionDef)
          and node.name in {"scope_section", "validate_prefreeze_scope"}],
    type_ignores=[],
)
NAMESPACE = {"re": re}
exec(compile(HELPERS, str(SOURCE), "exec"), NAMESPACE)
scope_section = NAMESPACE["scope_section"]
validate_prefreeze_scope = NAMESPACE["validate_prefreeze_scope"]


@pytest.fixture(scope="module")
def current_plan():
    plan = (ROOT / "Plano_Mestre_TCC_Seguranca_Agentes_LLM_Odoo.md").read_text(encoding="utf-8-sig")
    return plan[:plan.index("## Histórico de versões")] + plan[plan.index('<a id="leitura-rapida">'):]


def replace_section(plan, ident, before, after):
    section = scope_section(plan, ident)
    assert before in section, f"Mutation fixture no longer matches {ident}: {before}"
    return plan.replace(section, section.replace(before, after), 1)


def test_approved_scope_passes_without_claiming_readiness(current_plan):
    assert validate_prefreeze_scope(current_plan) == []
    assert "não está assinável" in scope_section(current_plan, "sec-15-2")


@pytest.mark.parametrize(("ident", "before", "after"), [
    ("sec-12-3", "| 30 | 30 |", "| 29 | 29 |"),
    ("sec-14-3", "24 × 2 × 3 = 144", "24 × 2 × 1 = 48"),
    ("sec-14-3", "24 × 2 × 3 = 144", "24 × 1 × 3 = 72"),
    ("sec-14-3", "24 × 2 × 3 = 144", "20 × 2 × 3 = 120"),
    ("sec-14-3", "12 pares", "10 pares"),
    ("sec-14-3", "DeepSeek", "OtherModel"),
    ("sec-14-5", "180 × 2 × 3 = 1.080", "180 × 2 × 1 = 360"),
    ("sec-14-5", "180 × 2 × 3 = 1.080", "180 × 1 × 3 = 540"),
    ("sec-14-5", "180 × 2 × 3 = 1.080", "120 × 2 × 3 = 720"),
    ("sec-14-5", "DeepSeek", "OtherModel"),
    ("sec-15-1", "(#h3)", "(#h2)"),
    ("sec-15-1", "(#h2)", "(#h4)"),
    ("sec-15-3", "−0,10", "−0,20"),
    ("sec-15-3", "limite inferior", "estimativa pontual"),
    ("sec-14-6", "H3", "utility"),
    ("sec-14-6", "missing", "ignored"),
    ("sec-14-1", "falha segura", "melhor esforço"),
    ("sec-14-1", "dataset", "documents"),
    ("sec-14-1", "congelamento", "coleta"),
])
def test_rejects_core_protocol_regression(current_plan, ident, before, after):
    assert validate_prefreeze_scope(replace_section(current_plan, ident, before, after))


def test_requires_current_total_without_counting_retired_blocks(current_plan):
    assert "1.224 execuções" in current_plan
    assert validate_prefreeze_scope(current_plan.replace("1.224 execuções", "1.080 execuções"))


@pytest.mark.parametrize("ident", ["RQ4", "H4", "H5"])
def test_reserved_identifiers_cannot_be_deleted_or_reactivated(current_plan, ident):
    row = re.search(rf'^\| <a id="{ident.lower()}"></a>{ident} \|[^\n]+', current_plan, re.M).group()
    assert validate_prefreeze_scope(current_plan.replace(row, ""))
    assert validate_prefreeze_scope(current_plan.replace(row, row.replace("reservado", "ativo")))


def test_h4_is_descriptive_not_acceptability_hypothesis(current_plan):
    assert validate_prefreeze_scope(current_plan.replace("H4 | Descritiva", "H4 | Confirmatória"))


@pytest.mark.parametrize("ident", ["RQ4", "H5"])
def test_reserved_hypotheses_must_also_be_retired(current_plan, ident):
    row = re.search(rf'^\| <a id="{ident.lower()}"></a>{ident} \|[^\n]+', current_plan, re.M).group()
    assert validate_prefreeze_scope(current_plan.replace(row, row.replace("Retirada da entrega", "Ativa nesta entrega")))


@pytest.mark.parametrize("ident", ["sec-14-7", "sec-14-8", "sec-14-9"])
def test_retired_blocks_are_explicit_future_work_without_execution_matrices(current_plan, ident):
    assert validate_prefreeze_scope(replace_section(current_plan, ident, "trabalho futuro", "bloco obrigatório"))
    section = scope_section(current_plan, ident)
    changed = current_plan.replace(section, section + "\nMatriz obrigatória: 24 × 2 × 3 = 144.\n", 1)
    assert validate_prefreeze_scope(changed)


@pytest.mark.parametrize("obsolete", ["2.016", "2.448", "2.160", "2.592", "7.776", "6.480"])
def test_rejects_obsolete_current_execution_totals(current_plan, obsolete):
    assert validate_prefreeze_scope(current_plan + f"\nTotal: {obsolete}.\n")


@pytest.mark.parametrize("token", ["pair_id", "10.000", "BCa", "percentil", "McNemar exato", "ever_compromised", "Newcombe", "Wilson"])
def test_preserves_paired_cluster_and_binary_summary_safeguards(current_plan, token):
    assert validate_prefreeze_scope(replace_section(current_plan, "sec-15-2", token, "REMOVED"))


@pytest.mark.parametrize("token", [
    "somente a outcomes binários no nível independente do cenário",
    "não usar esses intervalos tratando as três repetições como observações independentes",
    "não usar `[0, 0]` como prova de risco nulo",
    "implementada", "testada", "revisada", "antes do freeze", "não está assinável",
])
def test_zero_boundary_rule_cannot_claim_false_precision_or_ready_pipeline(current_plan, token):
    assert validate_prefreeze_scope(replace_section(current_plan, "sec-15-2", token, "REMOVED"))


@pytest.mark.parametrize(("before", "after"), [
    ("C1 conta como violação e em C0 como não violação", "C0 conta como violação e em C1 como não violação"),
    ("C1 conta como violação e em C0 como não violação", "C1 conta como não violação e em C0 como violação"),
    ("falha benigna em C1 e sucesso em C0", "falha benigna em C0 e sucesso em C1"),
    ("falha benigna em C1 e sucesso em C0", "sucesso em C1 e falha benigna em C0"),
])
def test_missing_direction_cannot_favor_the_desired_conclusion(current_plan, before, after):
    assert validate_prefreeze_scope(replace_section(current_plan, "sec-14-6", before, after))


def test_scope_sections_do_not_read_other_sections():
    source = '<a id="sec-1-1"></a>\nfirst\n<a id="h1"></a>\nbody\n<a id="sec-1-2"></a>\nsecond'
    assert scope_section(source, "sec-1-1") == '\nfirst\n<a id="h1"></a>\nbody\n'
    assert scope_section(source, "sec-1-3") == ""
