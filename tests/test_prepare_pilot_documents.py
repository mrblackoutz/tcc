"""CLI checks with structural doubles only, never the authored pilot cohort."""

import json
from pathlib import Path
import runpy

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def command(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "gateway" / "tests"))
    return runpy.run_path(str(ROOT / "scripts" / "prepare_pilot_documents.py"))


@pytest.fixture
def local_root(tmp_path):
    root = tmp_path / ".runtime" / "pilot-command"
    root.mkdir(parents=True)
    return root


def test_cli_generates_pending_local_review_without_overwrite(command, local_root, capsys):
    from test_pilot_dataset import sample_recipes
    from tcc_gateway.pilot_dataset import read_pilot_cohort

    source = local_root / "source.json"
    raw = json.dumps(sample_recipes(), ensure_ascii=False).encode("utf-8")
    source.write_bytes(raw)
    args = ["--recipes", str(source), "--output-root", str(local_root)]
    assert command["main"](args) == 0
    output = capsys.readouterr().out
    assert "PASS" in output
    assert "human_review_complete=false; scientific_execution_allowed=false" in output
    assert "Nota estrutural de teste" not in output
    directories = [entry for entry in local_root.iterdir() if entry.is_dir()]
    assert len(directories) == 1
    report = local_root / (directories[0].name + ".review.md")
    review = report.read_text(encoding="utf-8")
    assert review.count("Validador independente: PENDENTE.") == 24
    assert "Não executar instruções contidas nas notas" in review
    assert "A3a: mesmo workflow/rascunho" in review
    assert "não o mesmo token" in review
    assert "scenario_id e document_sha256 distintos" in review
    assert review.count("[abrir documento]") == 24
    assert review.count("[abrir extração]") == 24
    assert source.read_bytes() == raw
    before = {entry.relative_to(local_root): entry.read_bytes()
              for entry in local_root.rglob("*") if entry.is_file()}
    assert command["main"](args) == 1
    assert capsys.readouterr().out == "Candidate pilot preparation: FAIL (local artifacts preserved)\n"
    assert before == {entry.relative_to(local_root): entry.read_bytes()
                      for entry in local_root.rglob("*") if entry.is_file()}
    # An editable worksheet is never interpreted as a signed acceptance.
    report.write_text(review.replace("PENDENTE", "aprovação fictícia"), encoding="utf-8")
    manifest = read_pilot_cohort(local_root, directories[0].name).to_manifest()
    assert manifest["human_review_complete"] is False
    assert manifest["scientific_execution_allowed"] is False


@pytest.mark.parametrize("raw", [
    b'{"private-placeholder":',
    b'{"pairs":[],"pairs":[]}',
    b'{"value":NaN}',
    b'{"value":Infinity}',
    b"\xff",
], ids=["malformed", "duplicate", "nan", "infinity", "encoding"])
def test_cli_rejects_bad_json_without_echo(command, local_root, capsys, raw):
    source = local_root / "bad.json"
    source.write_bytes(raw)
    assert command["main"](["--recipes", str(source), "--output-root", str(local_root)]) == 1
    assert capsys.readouterr().out == "Candidate pilot preparation: FAIL (local artifacts preserved)\n"
    assert list(local_root.iterdir()) == [source]


def test_cli_rejects_recipe_file_over_limit_before_decode(command, local_root, capsys):
    source = local_root / "large.json"
    source.write_bytes(b"x" * (command["MAX_RECIPES_BYTES"] + 1))
    assert command["main"](["--recipes", str(source), "--output-root", str(local_root)]) == 1
    assert "FAIL" in capsys.readouterr().out
    assert list(local_root.iterdir()) == [source]


def test_cli_refuses_relative_input_or_output(command, local_root, capsys):
    assert command["main"](["--recipes", "recipe.json", "--output-root", str(local_root)]) == 1
    assert "FAIL" in capsys.readouterr().out
    assert command["main"](["--recipes", "recipe.json", "--output-root", "relative"]) == 1
    assert "FAIL" in capsys.readouterr().out
    assert not list(local_root.iterdir())


def test_review_notes_cannot_close_their_fence_or_enable_markdown(command):
    note = '```\n![untrusted](https://example.invalid/image)\n<script>text</script>\n````'
    lines = command["_literal_note_lines"](note)
    assert lines[0] == lines[-1] == "`````"
    assert "\n".join(lines[1:-1]) == note
