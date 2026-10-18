"""Only the fixed operational development demo, not a dataset generator."""

from pathlib import Path
import runpy

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_development_pdfs.py"


@pytest.fixture
def demo():
    return runpy.run_path(str(SCRIPT))


def test_fixed_recipes_remain_development_only_and_do_not_claim_bound_hashes(demo):
    for template in ("T1", "T2", "T3"):
        recipe = demo["development_example"](template).to_mapping()
        assert recipe["template_id"] == template
        assert recipe["split"] == "development"
        assert recipe["status"] == "CANDIDATE"
        assert recipe["truth"]["amount"] == "20.00"
        assert recipe["members"]["benign"]["document_sha256"] == "0" * 64


@pytest.mark.parametrize("template", ["T4", "test-v1", "../outside"])
def test_demo_never_silently_maps_an_unknown_template(demo, template):
    with pytest.raises(ValueError, match="invalid development example"):
        demo["development_example"](template)


def test_fixed_demo_is_reproducible_without_overwriting_existing_artifacts(demo, tmp_path, capsys):
    root = tmp_path / ".runtime" / "demo"
    root.mkdir(parents=True)
    assert demo["main"](["--output-root", str(root)]) == 0
    assert "PASS (3 pairs; not pilot/final)" in capsys.readouterr().out
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert len(list(root.iterdir())) == 3
    assert demo["main"](["--output-root", str(root)]) == 1
    assert "FAIL" in capsys.readouterr().out
    after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert after == before


def test_optional_pagination_example_produces_a_real_multipage_pdf(demo, tmp_path, capsys):
    from tcc_gateway.dataset_pdf_bundle import read_development_pair
    root = tmp_path / ".runtime" / "pagination"
    root.mkdir(parents=True)
    assert demo["main"](["--output-root", str(root), "--pagination-example"]) == 0
    assert "PASS (4 pairs; not pilot/final)" in capsys.readouterr().out
    pairs = [read_development_pair(root, directory.name) for directory in root.iterdir()]
    assert any(document.page_count > 1 for pair in pairs for document in pair.documents)


def test_demo_requires_an_existing_absolute_runtime_root(demo, capsys):
    assert demo["main"](["--output-root", "relative-output"]) == 1
    assert capsys.readouterr().out == "Development PDF generation: FAIL (local artifacts preserved)\n"
